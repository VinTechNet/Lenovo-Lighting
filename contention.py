"""Suspend the other lighting controllers, and survive being killed hard.

Windows Dynamic Lighting is a registry setting, so if we are killed with no
chance to clean up it stays switched off across reboots. To avoid that we
record the user's original settings in a state file before touching anything.
A later run (or restore.py) finds that file and knows what to put back,
rather than mistaking the suspended state for the user's preference.
"""

import json
import os

import dynamic_lighting
import lenovo_service

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".suspend_state.json")


def _load():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _save(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def _clear():
    try:
        os.remove(STATE_FILE)
    except OSError:
        pass


def recover():
    """Restore settings left behind by a run that was killed. Returns a note."""
    state = _load()
    if not state:
        return None
    if state.get("dynamic_lighting"):
        dynamic_lighting.set_enabled(True)
    if state.get("lenovo_service") and not lenovo_service.is_running():
        lenovo_service.start()
    _clear()
    return state


class SuspendControllers:
    """Park Windows Dynamic Lighting and (optionally) Lenovo's agent."""

    def __init__(self, dynamic_lighting_off=True, suspend_lenovo=False):
        self.dynamic_lighting_off = dynamic_lighting_off
        self.suspend_lenovo = suspend_lenovo
        self.original = {}

    def __enter__(self):
        # A leftover file means the previous run died; its values are the real
        # user settings, so carry them forward instead of re-reading the
        # already-suspended state.
        leftover = _load()
        if leftover:
            self.original = leftover
        else:
            self.original = {
                "dynamic_lighting": dynamic_lighting.is_enabled(),
                "lenovo_service": lenovo_service.is_running(),
            }
        _save(self.original)

        if self.dynamic_lighting_off and dynamic_lighting.is_enabled():
            dynamic_lighting.set_enabled(False)
        if self.suspend_lenovo:
            lenovo_service.stop()
        return self

    def __exit__(self, *exc):
        if self.original.get("dynamic_lighting"):
            dynamic_lighting.set_enabled(True)
        if self.original.get("lenovo_service") and not lenovo_service.is_running():
            lenovo_service.start()
        _clear()
