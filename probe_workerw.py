"""Dump the desktop window tree so we can see where the wallpaper layer lives."""

import ctypes
from ctypes import wintypes

from deskwindow import (WNDENUMPROC, SMTO_NORMAL, SPAWN_WORKERW, _class_name,
                        set_dpi_aware, user32)

set_dpi_aware()


def children(hwnd, indent="    "):
    out = []
    child = None
    while True:
        child = user32.FindWindowExW(hwnd, child, None, None)
        if not child:
            break
        r = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(child), ctypes.byref(r))
        out.append(f"{indent}{child} {_class_name(child)!r} "
                   f"({r.left},{r.top})-({r.right},{r.bottom})")
        out.extend(children(child, indent + "    "))
    return out


def dump(tag):
    print(f"\n===== {tag} =====")
    progman = user32.FindWindowW("Progman", None)
    print(f"Progman = {progman}")
    for line in children(progman):
        print(line)

    print("top-level WorkerW windows:")
    found = []

    def cb(hwnd, _l):
        if _class_name(hwnd) == "WorkerW":
            r = wintypes.RECT()
            user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
            has_view = bool(user32.FindWindowExW(hwnd, None,
                                                 "SHELLDLL_DefView", None))
            found.append(
                f"    {hwnd} ({r.left},{r.top})-({r.right},{r.bottom}) "
                f"defview={has_view}")
            for line in children(hwnd, "        "):
                found.append(line)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    print("\n".join(found) if found else "    (none)")


dump("before poking Progman")

for wparam, lparam in ((0, 0), (0xD, 0x1), (0xD, 0x0)):
    res = wintypes.DWORD()
    user32.SendMessageTimeoutW(user32.FindWindowW("Progman", None),
                               SPAWN_WORKERW, wparam, lparam,
                               SMTO_NORMAL, 1000, ctypes.byref(res))
    dump(f"after 0x052C wparam={wparam:#x} lparam={lparam:#x}")
