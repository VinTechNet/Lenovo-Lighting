"""Temporarily park Lenovo's lighting agent so it stops repainting the keyboard.

Optional - the service works without it by simply out-running the competition,
but on machines where Legion Space repaints aggressively this makes it clean.
Requires administrator rights; failures are reported, never fatal.
"""

import subprocess

SERVICE = "LenovoLightingService"
AGENT = "LenovoLighting"


def _run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=30)
    except Exception:
        return None


def is_running():
    r = _run(["sc", "query", SERVICE])
    return bool(r and "RUNNING" in r.stdout)


def stop():
    """Stop the service and its agent. Returns True if it had been running."""
    was_running = is_running()
    _run(["sc", "stop", SERVICE])
    _run(["taskkill", "/F", "/IM", f"{AGENT}.exe"])
    return was_running


def start():
    _run(["sc", "start", SERVICE])


class Suspended:
    """Context manager: stop Lenovo's lighting agent, restart it afterwards."""

    def __init__(self, active=False):
        self.active = active
        self.restore = False

    def __enter__(self):
        if self.active:
            self.restore = stop()
        return self

    def __exit__(self, *exc):
        if self.restore:
            start()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        print(f"was running: {stop()}")
    elif len(sys.argv) > 1 and sys.argv[1] == "start":
        start()
    print(f"{SERVICE} running: {is_running()}")
