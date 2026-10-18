"""Opt-in live overlay diagnostics; never imported by the product or pytest.

Run: python -m scripts.melonman_overlay_smoke
Uses the existing fixture-only real Azure/Zavora smoke harness. The child draws
with the production renderer; saves its own surface (not a desktop screenshot),
placement, focus and capture-exclusion observations. Does not alter real storage.
"""
import argparse
import ctypes
import json
from pathlib import Path
import struct
import sys
import time
import zlib

OUT = Path(__file__).resolve().parent.parent / 'artifacts/melonman-overlay-smoke'


def png_surface(path, width, height, pixels):
    # Convert the renderer's premultiplied BGRA into straight RGBA for inspection.
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            b,g,r,a = pixels[(y*width+x)*4:(y*width+x+1)*4]
            row.extend((min(255,round(r*255/a)) if a else 0,
                        min(255,round(g*255/a)) if a else 0,
                        min(255,round(b*255/a)) if a else 0,a))
        rows.append(row)
    def chunk(name,data):
        return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+
                     chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b''))


def window(args):
    from backend.overlay_window import Pointer, user32, wintypes
    overlay = Pointer(args.port,args.parent,args.mascot_path,args.mascot_size,args.mascot_fps)
    user32.GetForegroundWindow.restype=wintypes.HWND
    user32.GetWindowLongPtrW.argtypes=[wintypes.HWND,ctypes.c_int]
    user32.GetWindowLongPtrW.restype=ctypes.c_ssize_t
    user32.GetWindowDisplayAffinity.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    affinity=wintypes.DWORD()
    user32.GetWindowDisplayAffinity(overlay.hwnd,ctypes.byref(affinity))
    observations=[]; seen=set(); last=None; changing_frames=set()
    try:
        while True:
            foreground=user32.GetForegroundWindow()
            if not overlay.tick():
                break
            if overlay.visible:
                changing_frames.add(overlay.last_frame)
                key=(overlay.text,tuple(overlay.bounds or []))
                if key!=last:
                    last=key
                    observations.append(dict(text=overlay.text,kind=overlay.kind,bounds=overlay.bounds,
                        target=overlay.target,size=overlay.size,mascot_loaded=bool(overlay.mascot),
                        foreground_before=foreground,foreground_after=user32.GetForegroundWindow(),
                        style=user32.GetWindowLongPtrW(overlay.hwnd,-20),capture_affinity=affinity.value))
                if overlay.kind not in seen and overlay.bitmap:
                    seen.add(overlay.kind)
                    png_surface(OUT/f'{overlay.kind}.png',*overlay.size,
                        ctypes.string_at(overlay.bits.value,overlay.size[0]*overlay.size[1]*4))
            (OUT/'observations.json').write_text(json.dumps(dict(observations=observations,
                animated_frames=sorted(changing_frames)),indent=2),encoding='utf-8')
    finally:
        overlay.sock.close()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if '--window' in sys.argv:
        parser=argparse.ArgumentParser()
        parser.add_argument('--window',action='store_true')
        parser.add_argument('--port',type=int,required=True)
        parser.add_argument('--parent',type=int,required=True)
        parser.add_argument('--mascot-path',default='assets/melonman_working')
        parser.add_argument('--mascot-size',type=int,default=64)
        parser.add_argument('--mascot-fps',type=float,default=4)
        window(parser.parse_args())
        return
    import backend.overlay as overlay
    original=overlay.subprocess.Popen
    class DiagnosticChild(original):
        def __init__(self,command,*args,**kwargs):
            if '-m' in command and 'backend.overlay_window' in command:
                command=list(command)
                command[command.index('backend.overlay_window')]='scripts.melonman_overlay_smoke'
                command.insert(command.index('--port'),'--window')
            super().__init__(command,*args,**kwargs)
    overlay.subprocess.Popen=DiagnosticChild
    from scripts.live_seeded_pipeline_test import main as workflow
    workflow()


if __name__=='__main__':
    main()
