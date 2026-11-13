"""Compara, em arquivos fora do cache, safetensors via mmap x leitura sequencial."""
import os
import time

from safetensors.torch import load, load_file

M = r'D:\Miau3DStudio\models'
seq = os.path.join(M, r'tencent\Hunyuan3D-2mv\hunyuan3d-dit-v2-mv-turbo\model.fp16.safetensors')
mm = os.path.join(M, r'Tencent-Hunyuan\HunyuanDiT-v1.1-Diffusers-Distilled\transformer\diffusion_pytorch_model.safetensors')

t = time.time()
with open(seq, 'rb') as f:
    sd = load(f.read())
dt = time.time() - t
print(f'sequencial: {os.path.getsize(seq) / 1e9:.1f} GB em {dt:.1f}s = {os.path.getsize(seq) / 1e6 / dt:.0f} MB/s', flush=True)
del sd

t = time.time()
sd = load_file(mm, device='cpu')
dt = time.time() - t
print(f'mmap (load_file): {os.path.getsize(mm) / 1e9:.1f} GB em {dt:.1f}s = {os.path.getsize(mm) / 1e6 / dt:.0f} MB/s', flush=True)
