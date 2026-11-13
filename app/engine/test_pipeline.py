"""Teste do motor do Miau 3D Studio: imagem -> forma 3D -> textura, na GPU local."""
import gc
import os
import sys
import time

ROOT = r'D:\Miau3DStudio'
os.environ.setdefault('HY3DGEN_MODELS', os.path.join(ROOT, 'models'))
os.environ.setdefault('HF_HOME', os.path.join(ROOT, 'cache', 'hf'))
os.environ.setdefault('U2NET_HOME', os.path.join(ROOT, 'models', 'u2net'))
os.environ.setdefault('HF_HUB_OFFLINE', '1')
sys.path.insert(0, os.path.join(ROOT, 'vendor', 'Hunyuan3D-2'))

import torch  # noqa: E402
from PIL import Image  # noqa: E402

from hy3dgen.rembg import BackgroundRemover  # noqa: E402
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline  # noqa: E402
from hy3dgen.texgen import Hunyuan3DPaintPipeline  # noqa: E402

image_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'vendor', 'Hunyuan3D-2', 'assets', 'demo.png')
out_dir = os.path.join(ROOT, 'output', 'teste')
os.makedirs(out_dir, exist_ok=True)


def gb(n):
    return f'{n / 1024**3:.1f} GB'


t0 = time.time()
image = Image.open(image_path)
if image.mode != 'RGBA':
    image = BackgroundRemover()(image.convert('RGB'))
print(f'[1] imagem pronta ({time.time() - t0:.1f}s)', flush=True)

t = time.time()
shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
    'tencent/Hunyuan3D-2', subfolder='hunyuan3d-dit-v2-0-turbo', use_safetensors=True)
shape.enable_flashvdm()
print(f'[2] modelo de forma carregado ({time.time() - t:.1f}s)', flush=True)

t = time.time()
torch.cuda.reset_peak_memory_stats()
mesh = shape(image=image, num_inference_steps=5, octree_resolution=380, num_chunks=200000,
             generator=torch.manual_seed(12345), output_type='trimesh')[0]
mesh.export(os.path.join(out_dir, 'forma.glb'))
print(f'[3] forma gerada: {len(mesh.faces)} faces ({time.time() - t:.1f}s, pico VRAM {gb(torch.cuda.max_memory_allocated())})', flush=True)

del shape
gc.collect()
torch.cuda.empty_cache()

t = time.time()
paint = Hunyuan3DPaintPipeline.from_pretrained('tencent/Hunyuan3D-2', subfolder='hunyuan3d-paint-v2-0-turbo')
paint.enable_model_cpu_offload()
print(f'[4] modelo de textura carregado ({time.time() - t:.1f}s)', flush=True)

t = time.time()
torch.cuda.reset_peak_memory_stats()
textured = paint(mesh, image=image)
textured.export(os.path.join(out_dir, 'texturizado.glb'))
print(f'[5] textura aplicada ({time.time() - t:.1f}s, pico VRAM {gb(torch.cuda.max_memory_allocated())})', flush=True)
print(f'TOTAL {time.time() - t0:.1f}s -> {out_dir}', flush=True)
