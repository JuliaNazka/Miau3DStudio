"""Mede onde vai o tempo de carregar os modelos do Miau 3D Studio.

uso: python bench_load.py read|shape|paint|paint-mmap
"""
import os
import sys
import time

import engine as E  # noqa: E402  (engine.py ao lado: configura caminhos e variáveis)
import torch  # noqa: E402

M = os.path.join(E.ROOT, 'models', 'tencent', 'Hunyuan3D-2')
what = sys.argv[1]
t = time.time()

if what == 'read':
    for f in [os.path.join(M, 'hunyuan3d-dit-v2-0-turbo', 'model.fp16.safetensors'),
              os.path.join(M, 'hunyuan3d-paint-v2-0-turbo', 'unet', 'diffusion_pytorch_model.bin')]:
        t = time.time()
        n = 0
        with open(f, 'rb', buffering=0) as fh:
            while True:
                b = fh.read(64 * 1024 * 1024)
                if not b:
                    break
                n += len(b)
        dt = time.time() - t
        print(f'leitura {os.path.basename(f)}: {n / 1e9:.1f} GB em {dt:.1f}s = {n / 1e6 / dt:.0f} MB/s', flush=True)
elif what == 'shape':
    eng = E.Engine()
    eng._get('shape')
    print(f'forma carregada em {time.time() - t:.1f}s', flush=True)
elif what == 'paint':
    eng = E.Engine()
    t = time.time()
    eng._get('paint')
    print(f'textura carregada em {time.time() - t:.1f}s', flush=True)
import psutil  # noqa: E402
print(f'RAM do processo no pico (aprox.): {psutil.Process().memory_info().peak_wset / 1e9:.1f} GB', flush=True)
