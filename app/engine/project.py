"""Projeta as fotos originais sobre o modelo texturizado ("decalque").

Usa o mesmo renderizador e as mesmas câmeras do Hunyuan3D-Paint (ortográficas,
frente em azimute 0), então a foto cai onde a IA esperava aquela vista. Cada
foto é ajustada à silhueta do modelo naquele ângulo, projetada só onde há
objeto (alfa) e misturada com a textura da IA, que continua cobrindo o que
nenhuma foto mostra.
"""
from __future__ import annotations

import numpy as np
import torch
import trimesh
from PIL import Image

RES = 2048          # resolução de render e da textura (igual ao Hunyuan3D-Paint)
BAKE_EXP = 4        # peso pela inclinação da superfície (cos^4), igual ao Hunyuan
MIN_IOU = 0.6       # abaixo disso a foto não encaixa no modelo e é ignorada

# Azimutes a testar por foto. Frente/costas são fixos (a IA gera a frente em 0°);
# esquerda/direita dependem da convenção, então testamos os dois lados.
CANDIDATES = {'front': [0], 'back': [180], 'left': [90, 270], 'right': [270, 90]}


def _silhouette(render, azim: float, res: int) -> np.ndarray:
    _, pos_clip = render.get_pos_from_mvp(0, azim, None, None)
    rast, _ = render.raster_rasterize(pos_clip, render.pos_idx, resolution=(res, res))
    return (rast[0, ..., -1] > 0).cpu().numpy()


def _bbox(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def _fit(photo: Image.Image, target: np.ndarray, res: int):
    """Encaixa a foto (RGBA, sem fundo) no retângulo da silhueta do modelo."""
    alpha = np.array(photo)[..., 3] > 127
    if alpha.sum() < 100:
        return None, None
    px0, py0, px1, py1 = _bbox(alpha)
    tx0, ty0, tx1, ty1 = _bbox(target)
    crop = photo.crop((px0, py0, px1, py1)).resize((tx1 - tx0, ty1 - ty0), Image.LANCZOS)
    canvas = Image.new('RGBA', (res, res), (0, 0, 0, 0))
    canvas.paste(crop, (tx0, ty0))
    arr = np.array(canvas).astype(np.float32) / 255.0
    return arr, arr[..., 3] > 0.5


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    return float((a & b).sum() / max(1, (a | b).sum()))


def _base_texture(mesh: trimesh.Trimesh) -> Image.Image:
    mat = getattr(mesh.visual, 'material', None)
    img = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
    if img is None:
        raise RuntimeError('O modelo não tem textura para servir de base.')
    return img.convert('RGB')


@torch.no_grad()
def project_photos(model_path: str, photos: dict, out_path: str, progress=lambda p, m: None) -> dict:
    """photos: {'front'|'left'|'back'|'right': PIL RGBA já sem fundo}."""
    from hy3dgen.texgen.differentiable_renderer.mesh_render import MeshRender

    mesh = trimesh.load(model_path, force='mesh', process=False)
    base = _base_texture(mesh)
    render = MeshRender(default_resolution=RES, texture_size=RES)
    render.load_mesh(mesh)
    render.set_texture(base)
    base_tex = render.tex.clone()  # (H, W, 3) em 0..1

    acc = torch.zeros_like(base_tex)
    wsum = torch.zeros(base_tex.shape[:2] + (1,), device=base_tex.device)
    report = {}
    used_sides = set()
    for i, (view, photo) in enumerate(photos.items()):
        progress(0.1 + 0.8 * i / max(1, len(photos)), f'Projetando a foto "{view}"…')
        best = None
        for azim in CANDIDATES.get(view, [0]):
            if azim in used_sides and view in ('left', 'right'):
                continue
            target = _silhouette(render, azim, RES)
            if not target.any():
                continue
            arr, alpha = _fit(photo, target, RES)
            if arr is None:
                continue
            score = _iou(alpha, target)
            if best is None or score > best[0]:
                best = (score, azim, arr)
        if best is None or best[0] < MIN_IOU:
            report[view] = {'usada': False, 'encaixe': round(best[0], 2) if best else 0}
            continue
        score, azim, arr = best
        used_sides.add(azim)
        tex, cos_map, _ = render.back_project(torch.from_numpy(arr), 0, azim)
        w = (cos_map ** BAKE_EXP) * tex[..., 3:4]  # só onde a foto tem objeto
        acc += tex[..., :3] * w
        wsum += w
        report[view] = {'usada': True, 'encaixe': round(score, 2), 'azimute': azim}

    if not any(r['usada'] for r in report.values()):
        raise RuntimeError('Nenhuma foto encaixou no modelo. Tente fotos mais de frente/de lado, com o objeto inteiro.')

    progress(0.92, 'Misturando com a textura da IA…')
    photo_tex = acc / torch.clamp(wsum, min=1e-8)
    # Transição suave: onde a foto vê bem a superfície, vale a foto; nas bordas, a IA.
    blend = torch.clamp(wsum / 0.05, 0, 1)
    final = base_tex * (1 - blend) + photo_tex * blend
    render.set_texture(final.clamp(0, 1))
    out = render.save_mesh()
    out.export(out_path)
    coverage = float((wsum > 1e-6).float().mean())
    progress(1.0, 'Pronto!')
    return {'fotos': report, 'cobertura_uv': round(coverage, 3)}
