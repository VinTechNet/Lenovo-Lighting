"""Work out which desktop layer is covering us.

Shows a solid colour over the primary monitor in three placements, 8 s each.
Watch the desktop (Win+D) and note which colours you actually see.

  phase 1  MAGENTA - child of Progman, just below the icon view (current)
  phase 2  CYAN    - child of Progman, above the icon view
  phase 3  YELLOW  - as phase 1, but Explorer's wallpaper window hidden
"""

import ctypes
import time
import tkinter as tk
from ctypes import wintypes

from PIL import Image, ImageGrab

import deskwindow
from deskwindow import (HWND_TOP, SWP_NOACTIVATE, SWP_SHOWWINDOW, user32)

SW_HIDE, SW_SHOW = 0, 5
HOLD = 8.0

deskwindow.set_dpi_aware()

mons = deskwindow.monitors()
x, y, w, h = next(((m[0], m[1], m[2], m[3]) for m in mons if m[4]),
                  (mons[0][0], mons[0][1], mons[0][2], mons[0][3]))

progman = user32.FindWindowW("Progman", None)
defview = user32.FindWindowExW(wintypes.HWND(progman), None,
                               "SHELLDLL_DefView", None)
workerw = user32.FindWindowExW(wintypes.HWND(progman), None, "WorkerW", None)
ox, oy = deskwindow.window_rect(progman)[:2]
print(f"progman={progman} defview={defview} workerw={workerw}")

root = tk.Tk()
root.overrideredirect(True)
root.geometry(f"{w}x{h}+{x}+{y}")
canvas = tk.Canvas(root, width=w, height=h, highlightthickness=0, bd=0)
canvas.pack(fill="both", expand=True)
root.update_idletasks()
hwnd = int(root.wm_frame(), 16)
user32.SetParent(wintypes.HWND(hwnd), wintypes.HWND(progman))


def place(insert_after, colour, label, shot):
    canvas.configure(bg=colour)
    root.configure(bg=colour)
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
    place(defview or HWND_TOP, "#ff00ff",
          "phase 1 MAGENTA - below the icon view", "layer1.png")
    place(HWND_TOP, "#00ffff",
          "phase 2 CYAN - above the icon view", "layer2.png")

    if workerw:
        user32.ShowWindow(wintypes.HWND(workerw), SW_HIDE)
    place(defview or HWND_TOP, "#ffff00",
          "phase 3 YELLOW - below icon view, Explorer wallpaper window hidden",
          "layer3.png")
finally:
    if workerw:
        user32.ShowWindow(wintypes.HWND(workerw), SW_SHOW)
    root.destroy()
    deskwindow.refresh_desktop()
    print("restored")
