"""Screenshot a window by HWND, even when it's covered by other windows.

Used to verify the wallpaper layer without minimising the user's windows.
    python capture_window.py workerw out.png
"""

import ctypes
import sys
from ctypes import wintypes

from PIL import Image

import deskwindow

user32 = ctypes.WinDLL("user32")
gdi32 = ctypes.WinDLL("gdi32")

PW_RENDERFULLCONTENT = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def capture(hwnd):
    x, y, w, h = deskwindow.window_rect(hwnd)
    if w <= 0 or h <= 0:
        raise ValueError(f"window {hwnd} has no area ({w}x{h})")

    hdc = user32.GetWindowDC(wintypes.HWND(hwnd))
    memdc = gdi32.CreateCompatibleDC(hdc)
    bitmap = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bitmap)

    user32.PrintWindow(wintypes.HWND(hwnd), memdc, PW_RENDERFULLCONTENT)

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h          # negative = top-down rows
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bitmap, 0, h, buf, ctypes.byref(info), DIB_RGB_COLORS)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(wintypes.HWND(hwnd), hdc)

    return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")


def main():
    deskwindow.set_dpi_aware()
    target = sys.argv[1] if len(sys.argv) > 1 else "workerw"
    out = sys.argv[2] if len(sys.argv) > 2 else "capture.png"
    scale = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5

    if target == "workerw":
        hwnd, how = deskwindow.find_wallpaper_host()
        print(f"capturing wallpaper host {hwnd} ({how})")
    else:
        hwnd = int(target)

    img = capture(hwnd)
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)),
                         Image.LANCZOS)
    img.save(out)
    print(f"saved {out} ({img.width}x{img.height})")


if __name__ == "__main__":
    main()
