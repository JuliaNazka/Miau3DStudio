"""Servidor local do Miau 3D Studio (FastAPI em 127.0.0.1)."""
from __future__ import annotations

import io
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

ROOT = r'D:\Miau3DStudio'
APP = os.path.join(ROOT, 'app')
LIB = os.path.join(ROOT, 'library')
TRASH = os.path.join(ROOT, 'library-lixeira')
BLENDER = r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
IDLE_UNLOAD_S = 10 * 60  # descarrega os modelos depois de 10 min sem gerar
os.makedirs(LIB, exist_ok=True)

app = FastAPI(title='Miau 3D Studio')


@app.middleware('http')
async def no_cache(request, call_next):
    """A interface é local: sem cache, para cada atualização do app aparecer na hora."""
    resp = await call_next(request)
    resp.headers['Cache-Control'] = 'no-store'
    return resp
jobs: dict[str, dict] = {}
work: 'queue.Queue[tuple[str, dict]]' = queue.Queue()
_engine = None
_engine_error: Optional[str] = None


# ---------------- biblioteca ----------------
def item_dir(item_id: str) -> str:
    d = os.path.realpath(os.path.join(LIB, item_id))
    if not d.startswith(os.path.realpath(LIB) + os.sep):
        raise HTTPException(400, 'id inválido')
    return d


def read_meta(item_id: str) -> dict:
    with open(os.path.join(item_dir(item_id), 'meta.json'), encoding='utf-8') as f:
        return json.load(f)


def write_meta(meta: dict):
    path = os.path.join(item_dir(meta['id']), 'meta.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------- motor (fila única na GPU) ----------------
def worker():
    global _engine, _engine_error
    try:
        from engine.engine import Engine
        _engine = Engine()
    except Exception as e:  # noqa: BLE001
        _engine_error = f'{type(e).__name__}: {e}'
        traceback.print_exc()
        return
    while True:
        try:
            item_id, params = work.get(timeout=IDLE_UNLOAD_S)
        except queue.Empty:
            if _engine._models:  # ocioso: devolve a memória para o resto do PC
                print(f'[miau] {IDLE_UNLOAD_S // 60} min sem uso: descarregando os modelos', flush=True)
                _engine._free()
            continue
        job = jobs[item_id]
        meta = read_meta(item_id)
        d = item_dir(item_id)

        def progress(p: float, msg: str):
            job.update(progress=round(p, 3), message=msg)

        job.update(status='running', started=time.time())
        meta['status'] = 'running'
        write_meta(meta)
        try:
            images = None
            if params['mode'] == 'image':
                images = [Image.open(os.path.join(d, 'entrada', params['files'][0]))]
            elif params['mode'] == 'multiview':
                images = {k: Image.open(os.path.join(d, 'entrada', fn)) for k, fn in params['files'].items()}
            result = _engine.generate(mode=params['mode'], out_dir=d, progress=progress, images=images,
                                      prompt=params.get('prompt', ''), texture=params['texture'],
                                      quality=params['quality'], seed=params['seed'],
                                      project=params.get('project', False))
            meta.update(status='done', result=result)
            job.update(status='done', progress=1.0, message='Pronto!', result=result)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            msg = f'{type(e).__name__}: {e}'
            if 'out of memory' in msg.lower():
                msg = 'A placa de vídeo ficou sem memória. Feche programas pesados (ArchiCAD, Blender) ou use a qualidade "rápida".'
            meta.update(status='error', error=msg)
            job.update(status='error', message=msg)
            try:  # libera a placa para a próxima tentativa
                _engine._free()
            except Exception:  # noqa: BLE001
                pass
        finally:
            write_meta(meta)


threading.Thread(target=worker, daemon=True, name='miau-gpu').start()


# ---------------- API ----------------
@app.get('/api/status')
def status():
    eng = None
    if _engine is not None:
        try:
            eng = _engine.status()
        except Exception as e:  # noqa: BLE001
            eng = {'error': str(e)}
    busy = any(j.get('status') == 'running' for j in jobs.values())
    return {'ready': _engine is not None, 'error': _engine_error, 'engine': eng, 'busy': busy,
            'queue': work.qsize(), 'blender': os.path.exists(BLENDER)}


def _save_upload(up: UploadFile, folder: str, name: str) -> str:
    data = up.file.read()
    img = Image.open(io.BytesIO(data))
    img.load()
    fn = f'{name}.png'
    img.save(os.path.join(folder, fn))
    return fn


@app.post('/api/generate')
def generate(mode: str = Form(...), name: str = Form(''), prompt: str = Form(''),
             quality: str = Form('normal'), texture: bool = Form(True), seed: int = Form(1234),
             project: bool = Form(False),
             image: Optional[UploadFile] = File(None), front: Optional[UploadFile] = File(None),
             left: Optional[UploadFile] = File(None), back: Optional[UploadFile] = File(None),
             right: Optional[UploadFile] = File(None)):
    if mode not in ('image', 'multiview', 'text'):
        raise HTTPException(400, 'modo inválido')
    item_id = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    d = os.path.join(LIB, item_id)
    entrada = os.path.join(d, 'entrada')
    os.makedirs(entrada)
    files: object = None
    try:
        if mode == 'image':
            if image is None:
                raise HTTPException(400, 'Envie uma imagem.')
            files = [_save_upload(image, entrada, 'imagem')]
        elif mode == 'multiview':
            views = {k: v for k, v in (('front', front), ('left', left), ('back', back), ('right', right)) if v}
            if not views:
                raise HTTPException(400, 'Envie pelo menos uma foto.')
            files = {k: _save_upload(v, entrada, k) for k, v in views.items()}
        elif not prompt.strip():
            raise HTTPException(400, 'Escreva uma descrição.')
    except HTTPException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, f'Imagem inválida: {e}')

    params = {'mode': mode, 'prompt': prompt.strip(), 'quality': quality, 'texture': bool(texture),
              'seed': int(seed), 'files': files, 'project': bool(project) and bool(texture) and mode != 'text'}
    default_name = {'image': 'Imagem → 3D', 'multiview': 'Fotos → 3D', 'text': prompt.strip()[:40]}[mode]
    meta = {'id': item_id, 'name': name.strip() or default_name, 'mode': mode, 'params': params,
            'created': datetime.now().isoformat(timespec='seconds'), 'status': 'queued'}
    write_meta(meta)
    jobs[item_id] = {'status': 'queued', 'progress': 0.0, 'message': 'Na fila…'}
    work.put((item_id, params))
    return {'id': item_id}


@app.get('/api/jobs/{item_id}')
def job(item_id: str):
    if item_id in jobs:
        return jobs[item_id]
    meta = read_meta(item_id)
    return {'status': meta.get('status'), 'progress': 1.0 if meta.get('status') == 'done' else 0,
            'message': meta.get('error', ''), 'result': meta.get('result')}


@app.get('/api/library')
def library():
    items = []
    for item_id in sorted(os.listdir(LIB), reverse=True):
        try:
            meta = read_meta(item_id)
        except Exception:  # noqa: BLE001
            continue
        if meta.get('status') in ('queued', 'running') and item_id not in jobs:
            meta['status'] = 'error'
            meta['error'] = 'Interrompido (o app foi fechado durante a geração).'
        items.append(meta)
    return items


@app.get('/api/library/{item_id}')
def library_item(item_id: str):
    meta = read_meta(item_id)
    d = item_dir(item_id)
    exp = os.path.join(d, 'exportados')
    meta['exports'] = sorted(os.listdir(exp)) if os.path.isdir(exp) else []
    return meta


@app.post('/api/library/{item_id}/rename')
def rename(item_id: str, body: dict):
    meta = read_meta(item_id)
    meta['name'] = str(body.get('name', '')).strip()[:80] or meta['name']
    write_meta(meta)
    return meta


@app.delete('/api/library/{item_id}')
def delete(item_id: str):
    """Move para a lixeira do app (D:\\Miau3DStudio\\library-lixeira), não apaga de vez."""
    if jobs.get(item_id, {}).get('status') in ('queued', 'running'):
        raise HTTPException(409, 'Esse modelo ainda está sendo gerado.')
    os.makedirs(TRASH, exist_ok=True)
    shutil.move(item_dir(item_id), os.path.join(TRASH, item_id))
    return {'ok': True}


@app.post('/api/library/{item_id}/open-folder')
def open_folder(item_id: str):
    os.startfile(item_dir(item_id))  # noqa: S606 - abre o Explorer na pasta do modelo
    return {'ok': True}


@app.post('/api/library/{item_id}/tool')
def tool(item_id: str, body: dict):
    """Ferramentas do Blender: body = {source, format, ops:{decimate, remesh, height_cm, base, ground}}."""
    if not os.path.exists(BLENDER):
        raise HTTPException(500, 'Blender 5.2 não encontrado.')
    d = item_dir(item_id)
    meta = read_meta(item_id)
    src = os.path.join(d, (meta.get('result') or {}).get('model', 'modelo.glb'))
    if body.get('source'):
        cand = os.path.realpath(os.path.join(d, body['source']))
        if cand.startswith(d + os.sep) and os.path.exists(cand):
            src = cand
    fmt = str(body.get('format', 'glb')).lower()
    if fmt not in ('glb', 'fbx', 'obj', 'stl', 'usdz', 'blend'):
        raise HTTPException(400, 'formato inválido')
    exp = os.path.join(d, 'exportados')
    os.makedirs(exp, exist_ok=True)
    safe = ''.join(c if c.isalnum() or c in '-_ ' else '_' for c in meta['name']).strip() or 'modelo'
    out = os.path.join(exp, f'{safe}_{datetime.now():%H%M%S}.{fmt}')
    ops_path = os.path.join(exp, '_ops.json')
    with open(ops_path, 'w', encoding='utf-8') as f:
        json.dump(body.get('ops') or {}, f)
    proc = subprocess.run([BLENDER, '-b', '--factory-startup', '-P', os.path.join(APP, 'engine', 'blender_ops.py'),
                           '--', src, out, ops_path], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=900, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    os.remove(ops_path)
    info = None
    for line in proc.stdout.splitlines():
        if line.startswith('MIAU_RESULT '):
            info = json.loads(line[len('MIAU_RESULT '):])
    if proc.returncode != 0 or not os.path.exists(out):
        tail = (proc.stdout + proc.stderr)[-800:]
        raise HTTPException(500, f'O Blender falhou: {tail}')
    return {'file': os.path.relpath(out, d).replace('\\', '/'), 'info': info}


@app.post('/api/library/{item_id}/project')
def project(item_id: str):
    """Projeta as fotos originais sobre o modelo texturizado (fidelidade às fotos)."""
    if _engine is None:
        raise HTTPException(503, 'O motor ainda está carregando.')
    d = item_dir(item_id)
    meta = read_meta(item_id)
    if meta.get('mode') not in ('image', 'multiview'):
        raise HTTPException(400, 'Só funciona em modelos criados a partir de fotos.')
    if not os.path.exists(os.path.join(d, 'modelo.glb')):
        raise HTTPException(400, 'Gere o modelo com textura antes de projetar as fotos.')
    f = meta['params']['files']
    files = {'front': f[0]} if isinstance(f, list) else dict(f)
    key = f'{item_id}:fotos'
    jobs[key] = {'status': 'running', 'progress': 0.0, 'message': 'Na fila da placa de vídeo…'}

    def progress(p: float, msg: str):
        jobs[key].update(progress=round(p, 3), message=msg)

    try:
        report = _engine.project(item_dir=d, files=files, progress=progress)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        jobs[key].update(status='error', message=str(e))
        raise HTTPException(500, str(e))
    meta.setdefault('result', {})['projected'] = 'modelo_fotos.glb'
    meta['result']['projection'] = report
    write_meta(meta)
    jobs[key].update(status='done', progress=1.0, message='Pronto!')
    return report


@app.get('/files/{item_id}/{path:path}')
def files(item_id: str, path: str):
    d = item_dir(item_id)
    p = os.path.realpath(os.path.join(d, path))
    if not p.startswith(d + os.sep) or not os.path.isfile(p):
        raise HTTPException(404)
    return FileResponse(p)


app.mount('/', StaticFiles(directory=os.path.join(APP, 'ui'), html=True), name='ui')


@app.exception_handler(Exception)
async def on_error(_, exc: Exception):
    return JSONResponse({'detail': f'{type(exc).__name__}: {exc}'}, status_code=500)
