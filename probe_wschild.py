"""Does converting the window to WS_CHILD before SetParent make it render?

phase A  GREEN  - WS_CHILD, parented into the wallpaper WorkerW
phase B  ORANGE - WS_CHILD, parented into Progman below the icon view
"""

import time
import tkinter as tk
from ctypes import wintypes

from PIL import Image, ImageGrab

import deskwindow
from deskwindow import (HWND_TOP, SWP_NOACTIVATE, SWP_SHOWWINDOW, user32)

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
HOLD = 7.0

import ctypes

user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]


def as_long(value):
    """Window styles are a signed 32-bit field."""
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


deskwindow.set_dpi_aware()

mons = deskwindow.monitors()
x, y, w, h = next(((m[0], m[1], m[2], m[3]) for m in mons if m[4]),
                  (mons[0][0], mons[0][1], mons[0][2], mons[0][3]))

progman = user32.FindWindowW("Progman", None)
defview = user32.FindWindowExW(wintypes.HWND(progman), None,
                               "SHELLDLL_DefView", None)
workerw = user32.FindWindowExW(wintypes.HWND(progman), None, "WorkerW", None)

root = tk.Tk()
root.overrideredirect(True)
root.geometry(f"{w}x{h}+{x}+{y}")
canvas = tk.Canvas(root, width=w, height=h, highlightthickness=0, bd=0)
canvas.pack(fill="both", expand=True)
root.update_idletasks()
hwnd = int(root.wm_frame(), 16)

# Turn the top-level popup into a genuine child window first; a WS_POPUP
# window that has merely been re-parented never gets painted by the shell.
style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE) & 0xFFFFFFFF
style = (style & ~WS_POPUP) | WS_CHILD | WS_VISIBLE
user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE, as_long(style))
ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE) & 0xFFFFFFFF
user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE,
                      as_long(ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW))


def phase(parent, insert_after, colour, label, shot):
    canvas.configure(bg=colour)
    root.configure(bg=colour)
    user32.SetParent(wintypes.HWND(hwnd), wintypes.HWND(parent))
    ox, oy = deskwindow.window_rect(parent)[:2]
    user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(insert_after),
                        x - ox, y - oy, w, h,
                        SWP_NOACTIVATE | SWP_SHOWWINDOW)
    print(f"  {label}", flush=True)
    end = time.time() + HOLD
    grabbed = False
    while time.time() < end:
        root.update()
        time.sleep(0.02)
        if not grabbed and time.time() > end - HOLD + 2.0:
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
            img.resize((img.width // 3, img.height // 3),
                       Image.LANCZOS).save(shot)
            print(f"    saved {shot}", flush=True)
            grabbed = True


try:
    if workerw:
        phase(workerw, HWND_TOP, "#00ff00",
              "phase A GREEN - WS_CHILD inside the wallpaper WorkerW",
              "child_a.png")
    phase(progman, defview or HWND_TOP, "#ff8800",
          "phase B ORANGE - WS_CHILD inside Progman, below the icons",
          "child_b.png")
finally:
    root.destroy()
    deskwindow.refresh_desktop()
    print("done")
