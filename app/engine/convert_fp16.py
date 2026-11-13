"""Cria uma cópia em meia precisão (fp16) dos modelos de textura.

Os pipelines de textura já rodam em fp16 (torch_dtype=float16): converter os
pesos uma vez no disco dá os mesmos valores e corta pela metade o que o HD lê
a cada abertura do app. Os originais ficam intactos.
"""
import os
import shutil
import sys
import time

import torch
from safetensors.torch import load_file, save_file

SRC = r'D:\Miau3DStudio\models\tencent\Hunyuan3D-2'
DST = r'D:\Miau3DStudio\models\miau-fp16\Hunyuan3D-2'
FOLDERS = ['hunyuan3d-delight-v2-0', 'hunyuan3d-paint-v2-0-turbo']


def half(sd):
    return {k: (v.half() if torch.is_floating_point(v) else v).contiguous() for k, v in sd.items()}


def convert(src, dst):
    if src.endswith('.safetensors'):
        save_file(half(load_file(src)), dst, metadata={'format': 'pt'})
    elif src.endswith('.bin'):
        torch.save(half(torch.load(src, map_location='cpu', weights_only=True)), dst)
    else:
        shutil.copy2(src, dst)


for folder in FOLDERS:
    for root, _, files in os.walk(os.path.join(SRC, folder)):
        rel = os.path.relpath(root, SRC)
        os.makedirs(os.path.join(DST, rel), exist_ok=True)
        for f in files:
            s, d = os.path.join(root, f), os.path.join(DST, rel, f)
            if os.path.exists(d) and os.path.getmtime(d) >= os.path.getmtime(s):
                continue
            t = time.time()
            tmp = d + '.part'
            convert(s, tmp)
            os.replace(tmp, d)
            if os.path.getsize(s) > 50e6:
                print(f'{os.path.join(rel, f)}: {os.path.getsize(s) / 1e9:.2f} -> {os.path.getsize(d) / 1e9:.2f} GB '
                      f'({time.time() - t:.0f}s)', flush=True)
print('OK', flush=True)
sys.exit(0)
