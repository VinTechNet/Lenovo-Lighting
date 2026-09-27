"""Is our visualiser window actually parented and visible in the wallpaper layer?"""

import ctypes
from ctypes import wintypes

import deskwindow
from deskwindow import _class_name, user32

deskwindow.set_dpi_aware()

host, how = deskwindow.find_wallpaper_host()
print(f"host {host} ({how}) rect={deskwindow.window_rect(host)}")
print("children of the wallpaper host:")

child = None
while True:
    child = user32.FindWindowExW(wintypes.HWND(host), child, None, None)
    if not child:
        break
    visible = bool(user32.IsWindowVisible(wintypes.HWND(child)))
    style = user32.GetWindowLongW(wintypes.HWND(child), -16)   # GWL_STYLE
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(child), ctypes.byref(pid))
    print(f"  {child} {_class_name(child)!r} visible={visible} "
          f"pid={pid.value} style=0x{style & 0xFFFFFFFF:08X} "
          f"rect={deskwindow.window_rect(child)}")
