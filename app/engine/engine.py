"""Motor do Miau 3D Studio: Hunyuan3D-2 rodando na GPU local.

Mantém um modelo por vez na placa de vídeo (RTX 3060, 12 GB): carrega, usa e
libera antes do próximo. Cada geração informa o progresso por etapa.
"""
from __future__ import annotations

import gc
import os
import sys
import threading
import time
from typing import Callable, Optional

ROOT = r'D:\Miau3DStudio'
os.environ.setdefault('HY3DGEN_MODELS', os.path.join(ROOT, 'models'))
os.environ.setdefault('HF_HOME', os.path.join(ROOT, 'cache', 'hf'))
os.environ.setdefault('U2NET_HOME', os.path.join(ROOT, 'models', 'u2net'))
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
VENDOR = os.path.join(ROOT, 'vendor', 'Hunyuan3D-2')
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

import torch  # noqa: E402
from PIL import Image  # noqa: E402

T2I_PATH = os.path.join(ROOT, 'models', 'Tencent-Hunyuan', 'HunyuanDiT-v1.1-Diffusers-Distilled')

Progress = Callable[[float, str], None]

QUALITY = {
    # passos de difusão, resolução do octree, faces máximas para texturizar
    'rapida': dict(steps=5, octree=256, faces=30000),
    'normal': dict(steps=5, octree=380, faces=40000),
    'alta': dict(steps=10, octree=512, faces=60000),
}


_INIT_FUNCS = ('uniform_', 'normal_', 'trunc_normal_', 'constant_', 'ones_', 'zeros_', 'eye_', 'dirac_',
               'xavier_uniform_', 'xavier_normal_', 'kaiming_uniform_', 'kaiming_normal_', 'orthogonal_', 'sparse_')


class _no_init:
    """Pula o preenchimento aleatório dos pesos ao montar um modelo.

    O código original monta o modelo em fp32 e o enche de números aleatórios na
    CPU (minutos, para ~2 bilhões de parâmetros) só para sobrescrever tudo com os
    pesos do arquivo logo depois. Só use em modelos carregados com strict=True,
    em que todo peso vem do arquivo.
    """

    def __enter__(self):
        self._saved = {n: getattr(torch.nn.init, n) for n in _INIT_FUNCS if hasattr(torch.nn.init, n)}
        for n in self._saved:
            setattr(torch.nn.init, n, lambda tensor, *a, **k: tensor)
        return self

    def __exit__(self, *exc):
        for n, f in self._saved.items():
            setattr(torch.nn.init, n, f)


def _prefetch(*paths: str, min_size: int = 50_000_000):
    """Lê os arquivos de pesos em sequência antes de carregar o modelo.

    O safetensors mapeia o arquivo e lê aos pedaços, fora de ordem, enquanto
    copia os pesos: num HD mecânico isso é muito mais lento que uma leitura
    contínua. Lido antes, o arquivo fica no cache do Windows (memória que o
    sistema libera sozinho) e o carregamento pega tudo de lá.
    """
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                files += [os.path.join(root, n) for n in names]
        elif os.path.isfile(p):
            files.append(p)
    buf = bytearray(16 * 1024 * 1024)
    for f in files:
        if os.path.getsize(f) < min_size or not f.endswith(('.safetensors', '.bin', '.ckpt')):
            continue
        with open(f, 'rb', buffering=0) as fh:
            while fh.readinto(buf):
                pass


def _patch_shape_loader():
    """Monta a DiT e o codificador de imagem da forma sem o preenchimento aleatório.

    Os dois são carregados com strict=True; a VAE (strict=False) segue o caminho original.
    """
    from hy3dgen.shapegen import pipelines as sp
    if getattr(sp, '_miau_patched', False):
        return
    original = sp.instantiate_from_config

    def instantiate(config, **kwargs):
        target = str(config.get('target', '')) if isinstance(config, dict) else ''
        if 'autoencoder' in target.lower() or 'vae' in target.lower():
            return original(config, **kwargs)
        with _no_init():
            return original(config, **kwargs)

    sp.instantiate_from_config = instantiate
    sp._miau_patched = True


class Engine:
    """Mantém forma + textura carregadas entre gerações (cabem juntas em 12 GB).

    Só o texto→imagem, que é grande, descarrega os outros; e as duas variantes
    de forma (uma imagem / várias fotos) se revezam.
    """
    EXCLUSIVE = {'t2i'}
    SHAPES = {'shape', 'shape_mv'}

    def __init__(self):
        self._lock = threading.Lock()
        self._models: dict = {}
        self._rembg = None

    # ---------- gerenciamento de VRAM ----------
    def _drop(self, *names):
        for n in names:
            self._models.pop(n, None)
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _free(self):
        self._drop(*list(self._models))

    def _get(self, name: str):
        if name in self._models:
            return self._models[name]
        if name in self.EXCLUSIVE:
            self._free()
        else:
            self._drop(*[n for n in self._models if n in self.EXCLUSIVE or (name in self.SHAPES and n in self.SHAPES)])
        models = os.environ['HY3DGEN_MODELS']
        if name in self.SHAPES:
            _patch_shape_loader()
            sub = (r'tencent\Hunyuan3D-2\hunyuan3d-dit-v2-0-turbo' if name == 'shape'
                   else r'tencent\Hunyuan3D-2mv\hunyuan3d-dit-v2-mv-turbo')
            _prefetch(os.path.join(models, sub, 'model.fp16.safetensors'))
        elif name == 'paint':
            _prefetch(os.path.join(models, 'miau-fp16', 'Hunyuan3D-2'))
        elif name == 't2i':
            _prefetch(T2I_PATH)
        if name == 'shape':
            from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
            p = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
                'tencent/Hunyuan3D-2', subfolder='hunyuan3d-dit-v2-0-turbo', use_safetensors=True)
            p.enable_flashvdm()
        elif name == 'shape_mv':
            from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
            p = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
                'tencent/Hunyuan3D-2mv', subfolder='hunyuan3d-dit-v2-mv-turbo', use_safetensors=True)
            p.enable_flashvdm()
        elif name == 'paint':
            from hy3dgen.texgen import Hunyuan3DPaintPipeline
            # Cópia fp16 feita por convert_fp16.py: mesmos valores que o pipeline usa, metade da leitura do HD.
            fp16 = os.path.join(ROOT, 'models', 'miau-fp16', 'Hunyuan3D-2')
            ready = all(os.path.isfile(os.path.join(fp16, f)) for f in (
                r'hunyuan3d-paint-v2-0-turbo\unet\diffusion_pytorch_model.bin',
                r'hunyuan3d-delight-v2-0\unet\diffusion_pytorch_model.safetensors'))
            p = Hunyuan3DPaintPipeline.from_pretrained(fp16 if ready else 'tencent/Hunyuan3D-2',
                                                       subfolder='hunyuan3d-paint-v2-0-turbo')
            gc.collect()
            p.enable_model_cpu_offload()
        elif name == 't2i':
            from hy3dgen.text2image import HunyuanDiTPipeline
            if not os.path.isdir(T2I_PATH):
                raise RuntimeError('O modelo de texto para imagem ainda não foi baixado.')
            p = HunyuanDiTPipeline(T2I_PATH, device='cuda')
        else:
            raise ValueError(name)
        self._models[name] = p
        return p

    def _remove_bg(self, img: Image.Image) -> Image.Image:
        if img.mode == 'RGBA' and img.getextrema()[3][0] < 250:
            return img  # já tem fundo transparente
        if self._rembg is None:
            from hy3dgen.rembg import BackgroundRemover
            self._rembg = BackgroundRemover()
        return self._rembg(img.convert('RGB'))

    # ---------- etapas ----------
    def _shape(self, image, multiview: bool, quality: str, seed: int, progress: Progress):
        q = QUALITY.get(quality, QUALITY['normal'])
        progress(0.25, 'Carregando o modelo de forma…')
        pipe = self._get('shape_mv' if multiview else 'shape')
        progress(0.35, 'Gerando a forma 3D…')
        mesh = pipe(image=image, num_inference_steps=q['steps'], octree_resolution=q['octree'],
                    num_chunks=200000, generator=torch.manual_seed(seed), output_type='trimesh')[0]
        progress(0.5, 'Limpando a malha…')
        from hy3dgen.shapegen import DegenerateFaceRemover, FaceReducer, FloaterRemover
        mesh = FloaterRemover()(mesh)
        mesh = DegenerateFaceRemover()(mesh)
        return mesh, q

    def _texture(self, mesh, image, q, progress: Progress):
        from hy3dgen.shapegen import FaceReducer
        progress(0.55, f'Reduzindo para {q["faces"]:,} faces antes da textura…'.replace(',', '.'))
        mesh = FaceReducer()(mesh, max_facenum=q['faces'])
        progress(0.6, 'Carregando o modelo de textura…')
        pipe = self._get('paint')
        n = len(image) if isinstance(image, list) else 1
        progress(0.65, f'Pintando a textura com {n} foto{"s" if n > 1 else ""} (etapa mais demorada)…')
        return pipe(mesh, image=image)

    # ---------- tarefas públicas ----------
    def generate(self, *, mode: str, out_dir: str, progress: Progress, images=None, prompt: str = '',
                 texture: bool = True, quality: str = 'normal', seed: int = 1234,
                 project: bool = False) -> dict:
        """mode: 'image' (images=[PIL]), 'multiview' (images={'front':PIL,...}), 'text' (prompt)."""
        with self._lock:
            t0 = time.time()
            os.makedirs(out_dir, exist_ok=True)
            torch.cuda.reset_peak_memory_stats()
            if mode == 'text':
                progress(0.02, 'Carregando o modelo de texto → imagem…')
                t2i = self._get('t2i')
                progress(0.1, 'Criando a imagem de referência a partir do texto…')
                ref = t2i(prompt, seed=seed)
                ref.save(os.path.join(out_dir, 'referencia.png'))
                image, main, multiview = None, None, False
                progress(0.2, 'Removendo o fundo…')
                image = main = self._remove_bg(ref)
            elif mode == 'multiview':
                progress(0.05, 'Removendo o fundo das fotos…')
                image = {k: self._remove_bg(v) for k, v in images.items()}
                main = image.get('front') or next(iter(image.values()))
                # A textura também usa todas as fotos (frente primeiro), não só a da frente.
                tex_images = [image[k] for k in ('front', 'left', 'back', 'right') if k in image]
                multiview = True
                main.save(os.path.join(out_dir, 'referencia.png'))
            else:
                progress(0.05, 'Removendo o fundo da imagem…')
                image = main = self._remove_bg(images[0])
                multiview = False
                main.save(os.path.join(out_dir, 'referencia.png'))

            mesh, q = self._shape(image, multiview, quality, seed, progress)
            mesh.export(os.path.join(out_dir, 'forma.glb'))
            result = {'shape': 'forma.glb', 'faces': int(len(mesh.faces))}

            if texture:
                textured = self._texture(mesh, tex_images if mode == 'multiview' else main, q, progress)
                textured.export(os.path.join(out_dir, 'modelo.glb'))
                result['model'] = 'modelo.glb'
                result['faces'] = int(len(textured.faces))
                if project and mode in ('image', 'multiview'):
                    from engine.project import project_photos
                    photos = image if mode == 'multiview' else {'front': main}
                    try:
                        result['projection'] = project_photos(
                            os.path.join(out_dir, 'modelo.glb'), photos, os.path.join(out_dir, 'modelo_fotos.glb'),
                            lambda p, m: progress(0.9 + 0.09 * p, m))
                        result['projected'] = 'modelo_fotos.glb'
                    except Exception as e:  # noqa: BLE001 - a projeção é um extra; o modelo da IA já está salvo
                        result['projection_error'] = str(e)
            else:
                result['model'] = 'forma.glb'

            result['seconds'] = round(time.time() - t0, 1)
            result['vram_peak_gb'] = round(torch.cuda.max_memory_allocated() / 1024**3, 1)
            progress(1.0, 'Pronto!')
            return result

    def project(self, *, item_dir: str, files: dict, progress: Progress) -> dict:
        """Projeta as fotos originais (entrada/) sobre modelo.glb e grava modelo_fotos.glb."""
        from engine.project import project_photos
        with self._lock:
            progress(0.02, 'Removendo o fundo das fotos…')
            photos = {view: self._remove_bg(Image.open(os.path.join(item_dir, 'entrada', fn)))
                      for view, fn in files.items()}
            src = os.path.join(item_dir, 'modelo.glb')
            out = os.path.join(item_dir, 'modelo_fotos.glb')
            try:
                return project_photos(src, photos, out, progress)
            except torch.cuda.OutOfMemoryError:
                progress(0.05, 'Liberando a placa de vídeo…')
                self._free()
                return project_photos(src, photos, out, progress)

    def status(self) -> dict:
        ok = torch.cuda.is_available()
        return {
            'gpu': torch.cuda.get_device_name(0) if ok else None,
            'vram_total_gb': round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1) if ok else 0,
            'loaded': sorted(self._models),
            'text_to_3d': os.path.isdir(os.path.join(T2I_PATH, 'transformer')),
        }
