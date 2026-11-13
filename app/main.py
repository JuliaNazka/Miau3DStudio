"""Miau 3D Studio — abre o servidor local e a janela do app."""
import os
import socket
import sys
import threading
import time

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
os.chdir(APP)
LOG = os.path.join(r'D:\Miau3DStudio', 'logs', 'app.log')
os.makedirs(os.path.dirname(LOG), exist_ok=True)
if sys.stdout is None or not sys.stdout.isatty():  # pythonw: sem console, manda tudo para o log
    sys.stdout = sys.stderr = open(LOG, 'a', encoding='utf-8', buffering=1)

HOST, PORT = '127.0.0.1', 47833


def port_busy() -> bool:
    with socket.socket() as s:
        return s.connect_ex((HOST, PORT)) == 0


def run_server():
    import uvicorn
    from server import app
    uvicorn.run(app, host=HOST, port=PORT, log_level='warning')


_server_started = threading.Event()


def ensure_server():
    """Garante um motor na porta: se não houver nenhum (ou se ele cair), sobe o próprio."""
    while True:
        if not port_busy() and not _server_started.is_set():
            _server_started.set()
            threading.Thread(target=run_server, daemon=True).start()
        time.sleep(3)


def main():
    import webview
    threading.Thread(target=ensure_server, daemon=True).start()
    for _ in range(100):
        if port_busy():
            break
        time.sleep(0.1)
    webview.create_window('Miau 3D Studio', f'http://{HOST}:{PORT}/', width=1400, height=900,
                          min_size=(1050, 700), background_color='#0f1115')
    webview.start(gui='edgechromium', private_mode=False,
                  storage_path=os.path.join(r'D:\Miau3DStudio', 'cache', 'webview'))


if __name__ == '__main__':
    if '--server' in sys.argv:  # só o servidor, para testes no navegador
        run_server()
    else:
        main()
