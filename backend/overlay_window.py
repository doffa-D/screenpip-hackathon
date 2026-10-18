"""Glowing agent pointer with a short label, drawn on screen while a workflow runs.

Runs as its own process (python -m backend.overlay_window --port N --parent PID) so a drawing failure can never
affect a run. It listens for JSON datagrams on 127.0.0.1:N:
  {"text": "Clicking Compose", "kind": "act"|"think"|"wait"|"done"|"stop", "ttl": 25, "at": [x, y]}
  {"hide": true}
"at" is a screen point in the coordinates Zavora reports; the pointer glides there. Missing fields keep their
previous value. The window is click-through, never takes focus and is drawn with per-pixel alpha (no dependencies).
"""
import argparse
import ctypes
import json
import math
import queue
import socket
import sys
import threading
import time
from ctypes import wintypes
from .overlay_mascot import load_frames, frame_index, place_near, yellow_glow

TITLE = 'Melon Agent Overlay'
PALETTE = {  # accent, glow
    'act': ((31, 111, 235), (59, 130, 246)), 'think': ((107, 140, 199), (120, 150, 210)),
    'wait': ((240, 160, 32), (245, 180, 60)), 'done': ((46, 160, 67), (60, 190, 90)), 'stop': ((209, 69, 59), (230, 90, 80))}
LABEL_BG, ARROW_FILL, ARROW_EDGE = (13, 27, 52), (255, 255, 255), (8, 28, 70)
ARROW = [(0, 0), (0, 20), (5, 15.5), (9, 24), (12.5, 22.5), (8.5, 14), (15, 14)]  # classic pointer, tip at the origin

user32, gdi32, kernel32 = ctypes.WinDLL('user32'), ctypes.WinDLL('gdi32'), ctypes.WinDLL('kernel32')
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('style', wintypes.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HANDLE),
                ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HANDLE), ('lpszMenuName', wintypes.LPCWSTR),
                ('lpszClassName', wintypes.LPCWSTR), ('hIconSm', wintypes.HANDLE)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD),
                ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [('BlendOp', ctypes.c_ubyte), ('BlendFlags', ctypes.c_ubyte), ('SourceConstantAlpha', ctypes.c_ubyte), ('AlphaFormat', ctypes.c_ubyte)]


def declare():
    H, U, W, L, D, I, P = wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.DWORD, ctypes.c_int, ctypes.POINTER
    for fn, args, res in (
            (user32.DefWindowProcW, [H, U, W, L], LRESULT), (user32.RegisterClassExW, [P(WNDCLASSEXW)], wintypes.ATOM),
            (user32.CreateWindowExW, [D, wintypes.LPCWSTR, wintypes.LPCWSTR, D, I, I, I, I, H, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p], H),
            (user32.UpdateLayeredWindow, [H, wintypes.HDC, P(wintypes.POINT), P(wintypes.SIZE), wintypes.HDC, P(wintypes.POINT), wintypes.COLORREF, P(BLENDFUNCTION), D], wintypes.BOOL),
            (user32.GetDC, [H], wintypes.HDC), (user32.ShowWindow, [H, I], wintypes.BOOL),
            (user32.SetWindowPos, [H, H, I, I, I, I, U], wintypes.BOOL), (user32.PeekMessageW, [P(wintypes.MSG), H, U, U, U], wintypes.BOOL),
            (user32.DispatchMessageW, [P(wintypes.MSG)], LRESULT), (gdi32.CreateCompatibleDC, [wintypes.HDC], wintypes.HDC),
            (gdi32.CreateDIBSection, [wintypes.HDC, P(BITMAPINFOHEADER), U, P(ctypes.c_void_p), wintypes.HANDLE, D], wintypes.HBITMAP),
            (gdi32.SelectObject, [wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ), (gdi32.DeleteObject, [wintypes.HGDIOBJ], wintypes.BOOL),
            (gdi32.CreateFontW, [I] * 5 + [D] * 8 + [wintypes.LPCWSTR], wintypes.HFONT), (gdi32.SetBkMode, [wintypes.HDC, I], I),
            (gdi32.SetTextColor, [wintypes.HDC, wintypes.COLORREF], wintypes.COLORREF),
            (gdi32.GetTextExtentPoint32W, [wintypes.HDC, wintypes.LPCWSTR, I, P(wintypes.SIZE)], wintypes.BOOL),
            (gdi32.TextOutW, [wintypes.HDC, I, I, wintypes.LPCWSTR, I], wintypes.BOOL),
            (kernel32.OpenProcess, [D, wintypes.BOOL, D], wintypes.HANDLE), (kernel32.GetExitCodeProcess, [wintypes.HANDLE, P(D)], wintypes.BOOL),
            (kernel32.CloseHandle, [wintypes.HANDLE], wintypes.BOOL), (kernel32.GetModuleHandleW, [wintypes.LPCWSTR], wintypes.HMODULE)):
        fn.argtypes, fn.restype = args, res


def parent_alive(pid):
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = wintypes.DWORD()
    ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    kernel32.CloseHandle(handle)
    return bool(ok) and code.value == 259  # STILL_ACTIVE


def over(buf, i, rgb, a):
    """Composite rgb at coverage a onto a premultiplied BGRA pixel."""
    if a <= 0:
        return
    keep = 1 - a
    buf[i] = min(255, int(rgb[2] * a + buf[i] * keep))
    buf[i + 1] = min(255, int(rgb[1] * a + buf[i + 1] * keep))
    buf[i + 2] = min(255, int(rgb[0] * a + buf[i + 2] * keep))
    buf[i + 3] = min(255, int(255 * a + buf[i + 3] * keep))


def inside(poly, x, y):
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def edge_distance(poly, x, y):
    best = 1e9
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        dx, dy = x2 - x1, y2 - y1
        t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy or 1)))
        best = min(best, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return best


class Pointer:
    def __init__(self, port, parent, mascot_path=None, mascot_size=64, mascot_fps=4):
        self.parent = parent
        self.inbox = queue.Queue()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', port))
        threading.Thread(target=self.listen, daemon=True).start()
        user32.SetProcessDPIAware()
        declare()
        try:
            self.scale = ctypes.WinDLL('user32').GetDpiForSystem() / 96
        except (AttributeError, OSError):
            self.scale = 1
        self.mascot = load_frames(mascot_path, round(mascot_size * self.scale)) if mascot_path else None
        if self.mascot:
            self.mascot = yellow_glow(self.mascot, round(10*self.scale))
        self.mascot_fps = mascot_fps
        self.animation_epoch = time.monotonic()
        self.last_frame = -1
        self.bounds = None
        self.base_pixels = None
        self.screen = (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77), user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))
        self.proc = WNDPROC(lambda hwnd, msg, w, l: user32.DefWindowProcW(hwnd, msg, w, l))  # keep a reference
        instance = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSEXW(ctypes.sizeof(WNDCLASSEXW), 0, self.proc, 0, 0, instance, None, None, None, None, 'MelonAgentOverlay', None)
        user32.RegisterClassExW(ctypes.byref(cls))
        # layered | transparent | topmost | toolwindow | noactivate: visible, but invisible to the mouse and keyboard
        self.hwnd = user32.CreateWindowExW(0x80000 | 0x20 | 0x8 | 0x80 | 0x08000000, 'MelonAgentOverlay', TITLE, 0x80000000,
                                           0, 0, 1, 1, None, None, instance, None)
        # Keep the existing tool-window/title exclusion; also omit from capture on
        # supported Windows versions. Failure is harmless on older Windows.
        try:
            user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.SetWindowDisplayAffinity(self.hwnd, 0x11)  # WDA_EXCLUDEFROMCAPTURE
        except (AttributeError, OSError):
            pass
        self.screen_dc = user32.GetDC(None)
        self.mem = gdi32.CreateCompatibleDC(self.screen_dc)
        gdi32.SelectObject(self.mem, gdi32.CreateFontW(-round(11 * self.scale), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 4, 0, 'Segoe UI'))
        gdi32.SetBkMode(self.mem, 1)
        gdi32.SetTextColor(self.mem, 0xFFFFFF)
        self.bitmap = None
        self.text, self.kind, self.expires, self.visible, self.dirty = '', 'act', 0, False, True
        cx, cy = self.screen[0] + self.screen[2] / 2, self.screen[1] + self.screen[3] / 2
        self.target = self.cur = [cx, cy]
        self.flags, self.size, self.offset = (False, False), (0, 0), (0, 0)
        self.last_check = 0
        self.pill = (0, 0)

    def listen(self):
        while True:
            try:
                data, _ = self.sock.recvfrom(65535)
                self.inbox.put(json.loads(data.decode('utf-8')))
            except (OSError, ValueError):
                continue

    def apply(self, message):
        if message.get('hide'):
            self.expires, self.text = 0, ''
            return
        if 'text' in message and str(message['text']).strip() and str(message['text']).strip()[:200] != self.text:
            self.text, self.dirty = str(message['text']).strip()[:200], True
        if message.get('kind') in PALETTE and message['kind'] != self.kind:
            self.kind, self.dirty = message['kind'], True
        at = message.get('at')
        bounds = message.get('bounds')
        if isinstance(at, list) and len(at) == 2 and all(isinstance(v, (float, int)) and math.isfinite(v) for v in at):
            if self.mascot:
                if not (isinstance(bounds, list) and len(bounds) == 4 and
                        all(isinstance(v, (float, int)) and math.isfinite(v) for v in bounds)):
                    bounds = [*at, 0, 0]
                self.bounds = [v * self.scale for v in bounds]
                self.dirty = True
                return_to_target = self.mascot_position()
            else:
                return_to_target = [float(v) * self.scale for v in at]
            self.target = list(return_to_target)
            if not self.visible:
                self.cur = list(self.target)
        at = None  # target coordinates have been handled above
        if isinstance(at, list) and len(at) == 2:
            self.target = [float(at[0]) * self.scale, float(at[1]) * self.scale]
            if not self.visible:
                self.cur = list(self.target)
        self.expires = max(self.expires, time.monotonic() + float(message.get('ttl', 25))) if 'text' not in message \
            else time.monotonic() + float(message.get('ttl', 25))

    def mascot_position(self):
        if not self.bounds or not self.mascot:
            return self.target
        # Work area of the monitor containing the actual target (not the union
        # of monitors, which may include gaps between displays).
        point = wintypes.POINT(round(self.bounds[0]), round(self.bounds[1]))
        class MonitorInfo(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                        ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        monitor = user32.MonitorFromPoint(point, 2)
        area = self.screen
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.work
            area = r.left, r.top, r.right-r.left, r.bottom-r.top
        mw, mh, _ = self.mascot
        size = self.size if self.size != (0, 0) else (mw, mh + 48*self.scale)
        return place_near(self.bounds, size, area, 18*self.scale)

    def want_flags(self, pill_w, pill_h):
        if self.mascot:
            return False, False
        s, (sx, sy, sw, sh) = self.scale, self.screen
        return (self.target[0] + 16 * s + pill_w > sx + sw - 8, self.target[1] + 34 * s + pill_h > sy + sh - 8)

    def render(self):
        s, kind = self.scale, self.kind
        accent, glow = PALETTE[kind]
        text, size = self.text, wintypes.SIZE()
        gdi32.GetTextExtentPoint32W(self.mem, text, len(text), ctypes.byref(size))
        while size.cx > 320 * s and len(text) > 8:
            text = text[:-4].rstrip() + '…'
            gdi32.GetTextExtentPoint32W(self.mem, text, len(text), ctypes.byref(size))
        padx, pady = 10 * s, 5 * s
        pw, ph = size.cx + 2 * padx, size.cy + 2 * pady
        flip_x, flip_y = self.flags = self.want_flags(pw, ph)
        px = (22 * s - pw) if flip_x else 16 * s
        py = -(ph + 10 * s) if flip_y else 32 * s
        gx, gy, radius = 10 * s, 14 * s, 54 * s
        margin = 4 * s
        left = min(gx - radius, 0, px) - margin
        top = min(gy - radius, 0, py) - margin
        width = math.ceil(max(gx + radius, 16 * s, px + pw) + margin - left)
        height = math.ceil(max(gy + radius, 26 * s, py + ph) + margin - top)
        ox, oy = -left, -top
        buf = bytearray(width * height * 4)
        if self.mascot:
            mw, mh, _ = self.mascot
            width, height = math.ceil(max(mw, pw) + 8*s), math.ceil(mh + ph + 12*s)
            ox = oy = 0
            px, py = (width-pw)/2, mh + 6*s
            buf = bytearray(width * height * 4)
            self.mascot_xy = (round((width-mw)/2), 0)
        else:
            # soft glow
            cx, cy = ox + gx, oy + gy
            for y in range(max(0, int(cy - radius)), min(height, int(cy + radius) + 1)):
                for x in range(max(0, int(cx - radius)), min(width, int(cx + radius) + 1)):
                    d = math.hypot(x + .5 - cx, y + .5 - cy) / radius
                    if d < 1:
                        over(buf, (y * width + x) * 4, glow, (1 - d) ** 1.5 * 0.95)
            # pointer arrow (white, dark edge), 3x3 supersampled
            poly = [(ox + a * 1.25 * s, oy + b * 1.25 * s) for a, b in ARROW]
            edge = 1.5 * s
            for y in range(max(0, int(oy - edge)), min(height, int(oy + 31 * s))):
                for x in range(max(0, int(ox - edge)), min(width, int(ox + 21 * s))):
                    fill = ring = 0
                    for sy in (1 / 6, .5, 5 / 6):
                        for sx in (1 / 6, .5, 5 / 6):
                            inn = inside(poly, x + sx, y + sy)
                            fill += inn
                            ring += inn or edge_distance(poly, x + sx, y + sy) <= edge
                    if ring:
                        over(buf, (y * width + x) * 4, ARROW_EDGE, ring / 9)
                        over(buf, (y * width + x) * 4, ARROW_FILL, fill / 9)
        # label pill
        lx, ly = ox + px, oy + py
        half_w, half_h, r = pw / 2, ph / 2, ph / 2
        for y in range(max(0, int(ly) - 1), min(height, int(ly + ph) + 2)):
            for x in range(max(0, int(lx) - 1), min(width, int(lx + pw) + 2)):
                qx, qy = abs(x + .5 - (lx + half_w)) - (half_w - r), abs(y + .5 - (ly + half_h)) - (half_h - r)
                sdf = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r
                i = (y * width + x) * 4
                over(buf, i, accent, min(1, max(0, .5 - sdf)))
                over(buf, i, LABEL_BG, min(1, max(0, .5 - (sdf + 1.3 * s))))
        # text via GDI straight into the bitmap, then restore the alpha GDI does not write
        info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(self.screen_dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(self.mem, bitmap)
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
        self.bitmap = bitmap
        self.bits = bits
        ctypes.memmove(bits.value, bytes(buf), len(buf))
        tx, ty = round(lx + padx), round(ly + pady)
        gdi32.TextOutW(self.mem, tx, ty, text, len(text))
        ctypes.windll.gdi32.GdiFlush()
        buf[:] = ctypes.string_at(bits.value, len(buf))
        for y in range(max(0, ty), min(height, ty + size.cy)):
            for x in range(max(0, tx), min(width, tx + size.cx)):
                buf[(y * width + x) * 4 + 3] = 255
        ctypes.memmove(bits.value, bytes(buf), len(buf))
        self.size, self.offset, self.dirty = (width, height), (ox, oy), False
        self.pill = (pw, ph)
        if self.mascot:
            self.base_pixels = bytes(buf)
            self.target = list(self.mascot_position())
            self.last_frame = -1
            self.animate(time.monotonic())
        pos = wintypes.POINT(round(self.cur[0] - ox), round(self.cur[1] - oy))
        user32.UpdateLayeredWindow(self.hwnd, self.screen_dc, ctypes.byref(pos), ctypes.byref(wintypes.SIZE(width, height)), self.mem,
                                   ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(BLENDFUNCTION(0, 0, 255, 1)), 2)

    def animate(self, now):
        if not self.mascot or self.base_pixels is None:
            return
        mw, mh, frames = self.mascot
        index = frame_index(now-self.animation_epoch, len(frames), self.mascot_fps)
        if index == self.last_frame:
            return
        self.last_frame = index
        buf = bytearray(self.base_pixels)
        mx, my = self.mascot_xy
        # Frames are already premultiplied, and occupy a transparent region
        # above the label. Copy complete rows without per-pixel Python work.
        for y in range(mh):
            dest = ((my+y)*self.size[0]+mx)*4
            buf[dest:dest+mw*4] = frames[index][y*mw*4:(y+1)*mw*4]
        ctypes.memmove(self.bits.value, bytes(buf), len(buf))
        user32.UpdateLayeredWindow(self.hwnd, self.screen_dc,
            ctypes.byref(wintypes.POINT(round(self.cur[0]), round(self.cur[1]))),
            ctypes.byref(wintypes.SIZE(*self.size)), self.mem, ctypes.byref(wintypes.POINT()),
            0, ctypes.byref(BLENDFUNCTION(0, 0, 255, 1)), 2)

    def tick(self):
        msg = wintypes.MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.DispatchMessageW(ctypes.byref(msg))
        try:
            while True:
                self.apply(self.inbox.get_nowait())
        except queue.Empty:
            pass
        now = time.monotonic()
        if self.parent and now - self.last_check > 1:
            self.last_check = now
            if not parent_alive(self.parent):
                return False
        if self.expires > now and self.text:
            if not self.dirty and self.flags != self.want_flags(*self.pill):
                self.dirty = True
            if self.dirty:
                self.render()
            self.animate(now)
            for axis in (0, 1):  # glide toward the target
                delta = self.target[axis] - self.cur[axis]
                self.cur[axis] = self.target[axis] if abs(delta) < .6 else self.cur[axis] + delta * .22
            user32.SetWindowPos(self.hwnd, -1, round(self.cur[0] - self.offset[0]), round(self.cur[1] - self.offset[1]), 0, 0, 0x0001 | 0x0010)
            if not self.visible:
                user32.ShowWindow(self.hwnd, 4)  # SW_SHOWNOACTIVATE
                self.visible = True
            time.sleep(0.016)
        else:
            if self.visible:
                user32.ShowWindow(self.hwnd, 0)
                self.visible = False
            time.sleep(0.06)
        return True

    def run(self):
        while self.tick():
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--parent', type=int, default=0)
    parser.add_argument('--mascot-path')
    parser.add_argument('--mascot-size', type=int, default=64)
    parser.add_argument('--mascot-fps', type=float, default=4)
    args = parser.parse_args()
    try:
        Pointer(args.port, args.parent, args.mascot_path, args.mascot_size, args.mascot_fps).run()
    except Exception:
        sys.exit(1)


if __name__ == '__main__':
    main()
