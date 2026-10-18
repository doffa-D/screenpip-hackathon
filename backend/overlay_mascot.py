"""Mascot frame decoding and placement. No windows are created by this module."""
import ctypes
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ASSET = 'assets/melonman_working'


def asset_path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def frame_index(elapsed, count, fps=8):
    return int(max(0, elapsed) * fps) % count


def yellow_glow(animation, padding=10):
    """Add a soft yellow halo behind premultiplied frames; preserve their colors."""
    width, height, frames = animation
    out_width, out_height = width + padding*2, height + padding*2
    halo = bytearray(out_width*out_height*4)
    for y in range(out_height):
        for x in range(out_width):
            distance = math.hypot((x+.5-out_width/2)/(out_width/2),
                                  (y+.5-out_height/2)/(out_height/2))
            alpha = round(90 * max(0, 1-distance)**1.4)
            i = (y*out_width+x)*4
            halo[i:i+4] = bytes((round(38*alpha/255), round(212*alpha/255), alpha, alpha))
    result = []
    for frame in frames:
        pixels = bytearray(halo)
        for y in range(height):
            for x in range(width):
                src = (y*width+x)*4
                dest = ((y+padding)*out_width+x+padding)*4
                alpha = frame[src+3]
                for channel in range(4):
                    pixels[dest+channel] = min(255, frame[src+channel] + round(pixels[dest+channel]*(255-alpha)/255))
        result.append(bytes(pixels))
    return out_width, out_height, result


def place_near(bounds, size, screen, gap=18):
    """Place the entire mascot/label outside the target; prefer the right side.

    screen is the target monitor work area, including negative monitor origins.
    For a control filling the screen no non-overlapping solution exists: choose
    the clamped candidate with least overlap.
    """
    x, y, w, h = bounds
    width, height = size
    sx, sy, sw, sh = screen
    candidates = [(x+w+gap, y+h/2-height/2), (x-gap-width, y+h/2-height/2),
                  (x+w/2-width/2, y-gap-height), (x+w/2-width/2, y+h+gap)]
    def clamp(p):
        return (max(sx, min(p[0], sx+sw-width)), max(sy, min(p[1], sy+sh-height)))
    def overlap(p):
        return max(0, min(p[0]+width, x+w+gap)-max(p[0], x-gap)) * max(0, min(p[1]+height, y+h+gap)-max(p[1], y-gap))
    return min((clamp(p) for p in candidates), key=overlap)


def load_frames(path, width):
    """Decode PNG frames to premultiplied BGRA with native GDI+; fail closed.

    The supplied source is a transparent PNG sequence, so it needs neither an
    animated-WebP decoder nor a lossy intermediate conversion. All frames load
    before the overlay is shown; a bad frame falls back to the original pointer.
    """
    if not 32 <= width <= 512:
        return None
    try:
        files = sorted(asset_path(path).glob('*.png'))
        if not files or len(files) > 120:
            return None
        gdip = ctypes.WinDLL('gdiplus')
        P, U, I = ctypes.c_void_p, ctypes.c_uint, ctypes.c_int
        class Startup(ctypes.Structure):
            _fields_ = [('version', U), ('callback', P), ('thread', I), ('codecs', I)]
        class Rect(ctypes.Structure):
            _fields_ = [('x', I), ('y', I), ('width', I), ('height', I)]
        class BitmapData(ctypes.Structure):
            _fields_ = [('width', U), ('height', U), ('stride', I), ('format', I), ('scan', P), ('reserved', ctypes.c_size_t)]
        for name, args in {
            'GdiplusStartup': [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(Startup), P],
            'GdiplusShutdown': [ctypes.c_size_t], 'GdipCreateBitmapFromFile': [ctypes.c_wchar_p, ctypes.POINTER(P)],
            'GdipGetImageWidth': [P, ctypes.POINTER(U)], 'GdipGetImageHeight': [P, ctypes.POINTER(U)],
            'GdipGetImageThumbnail': [P, U, U, ctypes.POINTER(P), P, P],
            'GdipBitmapLockBits': [P, ctypes.POINTER(Rect), U, I, ctypes.POINTER(BitmapData)],
            'GdipBitmapUnlockBits': [P, ctypes.POINTER(BitmapData)], 'GdipDisposeImage': [P],
        }.items():
            getattr(gdip, name).argtypes = args
        def check(result):
            if result:
                raise ValueError('GDI+ image decode failed')
        token = ctypes.c_size_t()
        check(gdip.GdiplusStartup(ctypes.byref(token), ctypes.byref(Startup(1, None, 0, 0)), None))
        frames, dimensions = [], None
        try:
            for file in files:
                image, thumb = P(), P()
                try:
                    check(gdip.GdipCreateBitmapFromFile(str(file), ctypes.byref(image)))
                    iw, ih = U(), U()
                    check(gdip.GdipGetImageWidth(image, ctypes.byref(iw)))
                    check(gdip.GdipGetImageHeight(image, ctypes.byref(ih)))
                    if not iw.value or not ih.value or iw.value*ih.value > 16_000_000:
                        raise ValueError('Invalid image dimensions')
                    height = max(1, round(width * ih.value / iw.value))
                    if height > 1024 or (dimensions and dimensions != (width, height)):
                        raise ValueError('Inconsistent frame dimensions')
                    dimensions = width, height
                    check(gdip.GdipGetImageThumbnail(image, width, height, ctypes.byref(thumb), None, None))
                    data = BitmapData()
                    check(gdip.GdipBitmapLockBits(thumb, ctypes.byref(Rect(0, 0, width, height)), 1, 0xE200B, ctypes.byref(data)))
                    try:
                        frames.append(b''.join(ctypes.string_at(data.scan+y*data.stride, width*4) for y in range(height)))
                    finally:
                        gdip.GdipBitmapUnlockBits(thumb, ctypes.byref(data))
                finally:
                    if thumb:
                        gdip.GdipDisposeImage(thumb)
                    if image:
                        gdip.GdipDisposeImage(image)
        finally:
            gdip.GdiplusShutdown(token)
        return (*dimensions, frames)
    except (OSError, AttributeError, ValueError, OverflowError):
        return None
