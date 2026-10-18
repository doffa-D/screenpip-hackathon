"""Native Melon window; the existing backend owns all product operations."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import threading
import time
import traceback
import sys
import logging


ROOT = Path(__file__).resolve().parent
PORT = 8765


def reserve_listener(port=PORT):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == 'nt':
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        listener.bind(('127.0.0.1', port))
        listener.listen(128)
        return listener
    except BaseException:
        listener.close()
        raise RuntimeError('Melon Desktop is already open, or its local port is occupied.') from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    # pythonw has no console streams. Give logging and MCP subprocesses valid handles.
    (ROOT / '.data').mkdir(exist_ok=True)
    log_stream = (ROOT / '.data/desktop-runtime.log').open('a', encoding='utf-8', buffering=1)
    if sys.stdout is None:
        sys.stdout = log_stream
    if sys.stderr is None:
        sys.stderr = log_stream
    logging.basicConfig(stream=log_stream, level=logging.WARNING)
    def thread_error(args):
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=log_stream)
    threading.excepthook = thread_error
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise RuntimeError('Build the interface first: npm.cmd --prefix frontend run build')
    listener = reserve_listener()
    server = thread = None
    try:
        import uvicorn
        import webview
        from backend.main import app, hotkeys
        url = f'http://127.0.0.1:{PORT}'
        app.state.desktop_origin = url
        window = webview.create_window('Melon', url + '/#/home', width=1440, height=940,
            min_size=(880, 640), background_color='#eef4ff', text_select=True,
            confirm_close=not args.smoke_test)

        def navigate(route):
            window.restore()
            window.show()
            window.evaluate_js('window.location.hash = ' + json.dumps('/' + route))
        hotkeys.navigate = navigate
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=PORT,
            log_level='warning', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]},
                                  name='melon-backend', daemon=True)
        thread.start()
        deadline = time.monotonic() + 30
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('Melon backend could not start. Check .data/desktop.log.')
            time.sleep(.05)
        print(f"Melon server ready at: {url} (API docs: {url}/docs)", flush=True)

        smoke_errors = []

        def smoke():
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    result = window.evaluate_js("document.querySelector('#root')?.innerText || ''")
                    if result and 'Melon' in result:
                        break
                    time.sleep(.2)
                else:
                    raise RuntimeError('React interface did not render')
                window.evaluate_js("""void Promise.all(['/health','/settings','/workflows','/recordings','/schedules','/runs'].map(async p => {const r=await fetch(p);return {path:p,status:r.status}})).then(r=>window.__smokeResult=JSON.stringify(r)).catch(()=>window.__smokeResult='error')""")
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    raw = window.evaluate_js("window.__smokeResult || null")
                    if raw:
                        break
                    time.sleep(.1)
                result = json.loads(raw or 'null')
                if not isinstance(result, list) or len(result) != 6 or any(item['status'] != 200 for item in result):
                    raise RuntimeError('Desktop API smoke check failed')
                pages = []
                for route in ('home', 'memories', 'workflows', 'record', 'schedule', 'runs', 'settings'):
                    navigate(route)
                    time.sleep(.5)
                    content = window.evaluate_js("document.querySelector('main')?.innerText || document.querySelector('#root').innerText")
                    if len(content) < 20:
                        raise RuntimeError('Empty desktop page: ' + route)
                    pages.append(route)
                report = {'renderer': 'edgechromium', 'rendered': True, 'pages': pages, 'endpoints': result}
                (ROOT / 'artifacts').mkdir(exist_ok=True)
                (ROOT / 'artifacts/desktop-smoke.json').write_text(json.dumps(report, indent=2))
            except Exception:
                smoke_errors.append(traceback.format_exc())
                (ROOT / 'artifacts').mkdir(exist_ok=True)
                (ROOT / 'artifacts/desktop-smoke-error.txt').write_text(traceback.format_exc())
            finally:
                window.destroy()

        icon_path = ROOT / 'melon.ico'
        webview.start(smoke if args.smoke_test else None, gui='edgechromium',
                      private_mode=False, storage_path=str(ROOT / '.data/webview'),
                      icon=str(icon_path) if icon_path.exists() else None)
        if smoke_errors:
            raise RuntimeError('Desktop smoke test failed; see artifacts/desktop-smoke-error.txt')
    finally:
        if server:
            server.should_exit = True
        if thread:
            thread.join(30)
        listener.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        (ROOT / '.data').mkdir(exist_ok=True)
        with (ROOT / '.data/desktop.log').open('a', encoding='utf-8') as log:
            log.write(traceback.format_exc())
        if os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None,
                'Melon could not start. See .data/desktop.log. Check that another Melon Desktop window is not already open.',
                'Melon', 0x10)
        raise
