"""Windows 11 Dynamic Lighting toggle.

When Dynamic Lighting is on, Windows claims every HID LampArray and keeps
pushing its own frames, which fight anything we write. This flips the same
setting the Settings app writes (Personalization > Dynamic Lighting >
"Use Dynamic Lighting on my devices") so we can own the keyboard, and puts
it back afterwards.
"""

import winreg

KEY_PATH = r"Software\Microsoft\Lighting"
VALUE_NAME = "AmbientLightingEnabled"


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool):
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, KEY_PATH, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_DWORD, 1 if enabled else 0)


class Suspended:
    """Context manager: turn Dynamic Lighting off, restore the old value after."""

    def __init__(self, enabled=True):
        self.active = enabled
        self.previous = None

    def __enter__(self):
        if self.active:
            self.previous = is_enabled()
            if self.previous:
                set_enabled(False)
        return self

    def __exit__(self, *exc):
        if self.active and self.previous:
            set_enabled(True)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in ("on", "off"):
        set_enabled(sys.argv[1] == "on")
    print(f"Dynamic Lighting: {'ON' if is_enabled() else 'OFF'}")
