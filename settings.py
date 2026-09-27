"""Shared, live-reloadable settings for the visualisers and the control panel.

The control panel writes this file; the running visualisers poll its
modification time and apply changes without being restarted.
"""

import json
import os
import tempfile

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

DEFAULTS = {
    "wallpaper": {
        "style": "bars",
        # "primary", "all", or a list of monitor indices.
        "monitors": "primary",
        "bars": 64,
        "band": 38.0,
        "fps": 45.0,
        "brightness": 100.0,
        "dim": 55.0,
        "fade": 55.0,
        "blur": 0.0,
        "height": 42.0,
        "baseline": 88.0,
        "hue_span": 0.75,
        "reflection": True,
        "peak_fall": 0.55,
        "cap_height": 3,
        "fill": 0.62,
        "attack_ms": 25.0,
        "decay_ms": 220.0,
        "dynamic_range": 38.0,
    },
    "keyboard": {
        "effect": "spectrum",
        "brightness": 100.0,
    },
}


def _merge(base, override):
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load():
    """Settings from disk, merged over the defaults."""
    try:
        with open(PATH, "r", encoding="utf-8") as fh:
            return _merge(DEFAULTS, json.load(fh))
    except (OSError, ValueError):
        return _merge(DEFAULTS, {})


def save(data):
    """Write atomically, so a reader never sees a half-written file."""
    directory = os.path.dirname(PATH)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def mtime():
    try:
        return os.path.getmtime(PATH)
    except OSError:
        return 0.0


class Watcher:
    """Polls the settings file and hands back the new contents when it changes."""

    def __init__(self):
        self.stamp = mtime()

    def poll(self):
        current = mtime()
        if current == self.stamp:
            return None
        self.stamp = current
        return load()
