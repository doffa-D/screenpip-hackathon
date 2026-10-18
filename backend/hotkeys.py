"""Windows global shortcuts. Only timestamp bookmarks or review navigation."""
import asyncio
import ctypes
import sys
import threading
import webbrowser
from ctypes import wintypes


class Hotkeys:
    def __init__(self, recordings, workflows):
        self.recordings, self.workflows = recordings, workflows
        self.thread = None
        self.thread_id = None
        self.status = {}
        self.loop = None
        self.navigate = None
        self.bindings = {1: ('Ctrl+Shift+R', ord('R')), 2: ('Ctrl+Shift+M', ord('M')),
                         3: ('Ctrl+Shift+K', ord('K')), 4: ('Ctrl+Shift+Space', 0x20),
                         5: ('Ctrl+Shift+Enter', 0x0D)}

    def start(self):
        self.loop = asyncio.get_running_loop()
        if sys.platform != 'win32':
            self.status = {'platform': 'Global shortcuts require Windows'}
            return
        self.thread = threading.Thread(target=self.run, daemon=True, name='melon-hotkeys')
        self.thread.start()

    def dispatch(self, key):
        try:
            if key == 1:
                active = next((r for r in self.recordings.records.values() if r['status'] == 'recording'), None)
                if active:
                    from .recordings import now
                    active['ended_at'] = now()
                    self.recordings.process(active)
                else:
                    self.recordings.start('Recorded workflow')
            elif key == 2:
                active = next((r for r in self.recordings.records.values() if r['status'] == 'recording'), None)
                if active:
                    from .recordings import now
                    active['markers'].append({'timestamp': now(), 'label': 'Keyboard bookmark'})
                    self.recordings.persist()
            else:
                route = 'memories' if key == 3 else 'home'
                if key == 5:
                    library = self.workflows.list()
                    route = f'workflows/saved/{library[0].id}' if library else 'workflows'
                if self.navigate:
                    threading.Thread(target=self.navigate, args=(route,), daemon=True).start()
                else:
                    webbrowser.open('http://127.0.0.1:8000/#/' + route)
        except Exception:
            self.status['last_error'] = 'Shortcut could not complete. Check Melon.'

    def run(self):
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.thread_id = kernel32.GetCurrentThreadId()
        registered = []
        for key, (label, vk) in self.bindings.items():
            if user32.RegisterHotKey(None, key, 0x0002 | 0x0004 | 0x4000, vk):
                registered.append(key)
                self.status[label] = 'registered'
            else:
                self.status[label] = 'unavailable: another app may use this combination'
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == 0x0312:
                    self.loop.call_soon_threadsafe(self.dispatch, int(message.wParam))
        finally:
            for key in registered:
                user32.UnregisterHotKey(None, key)

    async def close(self):
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
        if self.thread:
            await asyncio.to_thread(self.thread.join, 2)
