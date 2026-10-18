"""Best-effort on-screen pointer and label for a running workflow. Never raises, never blocks a run."""
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

TITLE = 'Melon Agent Overlay'
ENV_PORT = 'MELON_OVERLAY_PORT'


def send_to(port, message):
    try:
        if port:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(json.dumps(message, ensure_ascii=False).encode('utf-8'), ('127.0.0.1', int(port)))
    except (OSError, ValueError):
        pass


def aim(bounds):
    """Used by the desktop worker: glide the pointer to the centre of a Zavora element. No-op without an overlay."""
    port = os.environ.get(ENV_PORT)
    if not port:
        return False
    try:
        send_to(port, {'at': [bounds['x'] + bounds['width'] / 2, bounds['y'] + bounds['height'] / 2],
                       'bounds': [bounds[k] for k in ('x', 'y', 'width', 'height')]})
        return True
    except (KeyError, TypeError):
        return False


class AgentOverlay:
    def __init__(self, enabled=True, mascot=True, mascot_path='assets/melonman_working', mascot_size=64, mascot_fps=4):
        self.enabled = enabled and sys.platform == 'win32'
        self.options = ['--mascot-path', str(mascot_path), '--mascot-size', str(mascot_size),
                        '--mascot-fps', str(mascot_fps)] if mascot else []
        self.process = None
        self.port = 0

    def start(self):
        if not self.enabled or (self.process and self.process.poll() is None):
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.bind(('127.0.0.1', 0))
                self.port = probe.getsockname()[1]
            self.process = subprocess.Popen(
                [sys.executable, '-m', 'backend.overlay_window', '--port', str(self.port), '--parent', str(os.getpid()), *self.options],
                cwd=str(Path(__file__).resolve().parent.parent), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)  # CREATE_NO_WINDOW
            os.environ[ENV_PORT] = str(self.port)  # desktop workers inherit it and aim the pointer at the real control
            return True
        except OSError:
            self.process, self.port = None, 0
            return False

    def send(self, message):
        if not (self.process and self.process.poll() is None):
            return
        send_to(self.port, message)

    def show(self, text, kind='act', ttl=25):
        self.send({'text': text, 'kind': kind, 'ttl': ttl})

    def hide(self):
        self.send({'hide': True})

    def close(self):
        self.hide()
        if self.process and self.process.poll() is None:
            self.process.terminate()
        self.process, self.port = None, 0
        os.environ.pop(ENV_PORT, None)
