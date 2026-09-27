"""Host a window *behind the desktop icons* - i.e. as a live wallpaper.

Explorer paints the wallpaper in a "WorkerW" window that sits underneath the
icon view. Sending the undocumented 0x052C message to Progman asks it to spawn
that WorkerW; re-parenting our own window into it puts our drawing exactly
where the wallpaper normally is, with the icons still on top.
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
shcore = None
try:
    shcore = ctypes.WinDLL("shcore")
except OSError:
    pass

SPAWN_WORKERW = 0x052C
SMTO_NORMAL = 0x0000

user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                 wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.SetParent.restype = wintypes.HWND
user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(wintypes.DWORD),
]

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]


def set_dpi_aware():
    """Report real pixels instead of DPI-virtualised ones."""
    try:  # per-monitor v2, Windows 10 1703+
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return "per-monitor-v2"
    except Exception:
        pass
    if shcore is not None:
        try:
            shcore.SetProcessDpiAwareness(2)
            return "per-monitor"
        except Exception:
            pass
    try:
        user32.SetProcessDPIAware()
        return "system"
    except Exception:
        return "none"


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def find_wallpaper_host():
    """HWND of the window to parent into, and how it was found."""
    progman = user32.FindWindowW("Progman", None)
    if progman:
        result = wintypes.DWORD()
        user32.SendMessageTimeoutW(progman, SPAWN_WORKERW, 0, 0,
                                   SMTO_NORMAL, 1000, ctypes.byref(result))

    # Windows 11: Explorer keeps the wallpaper WorkerW as a *child* of Progman,
    # sitting just below SHELLDLL_DefView, so the icons stay on top of us.
    if progman:
        worker = user32.FindWindowExW(progman, None, "WorkerW", None)
        if worker:
            return worker, "WorkerW (child of Progman)"

    # Windows 10: the WorkerW is a top-level sibling that follows the window
    # owning the icon view.
    found = []

    def callback(hwnd, _lparam):
        if user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
            sibling = user32.FindWindowExW(None, hwnd, "WorkerW", None)
            if sibling:
                found.append(sibling)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    if found:
        return found[0], "WorkerW (sibling)"
    if progman:
        return progman, "Progman (fallback)"
    return None, "not found"


HWND_TOP = 0
HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002

user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND, wintypes.COLORREF, ctypes.c_ubyte, wintypes.DWORD,
]


def _as_long(value):
    """Window style fields are signed 32-bit."""
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def pin_above_wallpaper(hwnd, x, y, w, h, click_through=True):
    """Park a top-level window on the desktop layer.

    Newer Windows 11 builds composite the desktop in a way that never paints
    re-parented foreign windows, so instead of living inside Progman we stay a
    normal top-level window and simply sit at the very bottom of the z-order,
    with the desktop pushed below us. The result draws above the wallpaper and
    behind every application window.
    """
    ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE) & 0xFFFFFFFF
    ex |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED
    if click_through:
        # Let clicks fall through to the desktop icons underneath.
        ex |= WS_EX_TRANSPARENT
    user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, _as_long(ex))
    user32.SetLayeredWindowAttributes(wintypes.HWND(hwnd), 0, 255, LWA_ALPHA)
    user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_BOTTOM),
                        x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
    sink_desktop()


def sink_desktop():
    """Push the desktop (and its wallpaper) below everything else."""
    progman = user32.FindWindowW("Progman", None)
    if progman:
        user32.SetWindowPos(wintypes.HWND(progman), wintypes.HWND(HWND_BOTTOM),
                            0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

user32.SetWindowPos.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]


def attach_above_wallpaper(hwnd, x, y, w, h):
    """Slot a window between the desktop icons and the wallpaper.

    Windows 11 paints the wallpaper into a WorkerW child of Progman, and that
    painting covers any child window we add to it. Becoming a sibling instead -
    a child of Progman ordered just below SHELLDLL_DefView - puts us above the
    wallpaper but still underneath the icons.
    """
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return False, "no Progman"
    defview = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None)

    user32.SetParent(wintypes.HWND(hwnd), wintypes.HWND(progman))
    ox, oy = window_rect(progman)[:2]
    user32.SetWindowPos(
        wintypes.HWND(hwnd), wintypes.HWND(defview or HWND_TOP),
        x - ox, y - oy, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )
    return True, "Progman (below icons, above wallpaper)"


def window_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def move(hwnd, x, y, w, h):
    user32.MoveWindow(wintypes.HWND(hwnd), x, y, w, h, True)


def attach(hwnd, host=None):
    """Re-parent `hwnd` into the wallpaper layer."""
    if host is None:
        host, _ = find_wallpaper_host()
    if not host:
        return False
    user32.SetParent(wintypes.HWND(hwnd), wintypes.HWND(host))
    return True


def refresh_desktop():
    """Ask Explorer to repaint the wallpaper after we go away."""
    progman = user32.FindWindowW("Progman", None)
    if progman:
        user32.InvalidateRect(wintypes.HWND(progman), None, True)
    user32.UpdateWindow(wintypes.HWND(progman))


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
    ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
)


def monitors():
    """Real-pixel geometry of every monitor: (x, y, w, h, is_primary)."""
    out = []

    def callback(hmon, _hdc, _rect, _lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        r = info.rcMonitor
        out.append((r.left, r.top, r.right - r.left, r.bottom - r.top,
                    bool(info.dwFlags & 1)))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
    return out


def virtual_desktop():
    """Bounding box of all monitors: (x, y, w, h)."""
    mons = monitors()
    if not mons:
        return (0, 0, 1920, 1080)
    left = min(m[0] for m in mons)
    top = min(m[1] for m in mons)
    right = max(m[0] + m[2] for m in mons)
    bottom = max(m[1] + m[3] for m in mons)
    return (left, top, right - left, bottom - top)


if __name__ == "__main__":
    print(f"DPI awareness set to: {set_dpi_aware()}")
    host, how = find_wallpaper_host()
    print(f"wallpaper host: {host} via {how}"
          f"{' class=' + _class_name(host) if host else ''}")
    print(f"virtual desktop: {virtual_desktop()}")
    for i, m in enumerate(monitors()):
        print(f"  monitor {i}: x={m[0]} y={m[1]} {m[2]}x{m[3]}"
              f"{' PRIMARY' if m[4] else ''}")
