"""Control panel for the music visualisers.

Pick the spectrum animation, choose which screen it plays on, tune the look,
and start/stop either service. Changes are written to settings.json, which the
running visualisers pick up live - no restart.

Closing the window hides it to the system tray; quit from the tray menu.
"""

import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw

import deskwindow
import settings as settings_store
from musiclight import EFFECTS
from wallpaper import STYLES

KEYBOARD_TASK = "LenovoKeyboardMusicSync"
WALLPAPER_TASK = "DesktopMusicSpectrum"

KEYBOARD_EFFECTS = {
    "spectrum": "Spectrum - bass left to treble right",
    "vu": "VU meter - fills with loudness",
    "pulse": "Pulse - whole keyboard beats as one",
    "wave": "Wave - ripples out from the centre on bass",
}

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW, keeps console flashes away


# --------------------------------------------------------------------------
# scheduled task control
# --------------------------------------------------------------------------
def _run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=25, creationflags=NO_WINDOW)
    except Exception:
        return None


def task_state(name):
    result = _run(["schtasks", "/Query", "/TN", name])
    if not result or result.returncode != 0:
        return "not installed"
    text = result.stdout.lower()
    if "running" in text:
        return "running"
    if "ready" in text:
        return "stopped"
    if "disabled" in text:
        return "disabled"
    return "unknown"


def task_start(name):
    return _run(["schtasks", "/Run", "/TN", name])


def task_stop(name):
    return _run(["schtasks", "/End", "/TN", name])


# --------------------------------------------------------------------------
# tray icon
# --------------------------------------------------------------------------
def make_tray_image(size=64):
    """A small spectrum glyph for the notification area."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bars = [(0.18, "#ff4b3e"), (0.42, "#ffa63e"), (0.72, "#8ce03a"),
            (0.52, "#3ad1e0"), (0.30, "#5b6bff")]
    width = size // (len(bars) + 2)
    for i, (height, colour) in enumerate(bars):
        x = width + i * width
        top = int(size * (1 - height)) - 2
        draw.rectangle([x, top, x + width - 2, size - 6], fill=colour)
    return img


# --------------------------------------------------------------------------
# the panel
# --------------------------------------------------------------------------
class ControlPanel:
    def __init__(self):
        deskwindow.set_dpi_aware()
        self.data = settings_store.load()
        self.monitors = deskwindow.monitors()
        self.events = queue.Queue()
        self.tray = None
        self.style_name = self.data["wallpaper"]["style"]
        self._suspend_writes = True

        self.root = tk.Tk()
        self.root.title("Music Visualiser Control Panel")
        self.root.minsize(660, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        self._build_ui()
        self._load_into_widgets()
        self._suspend_writes = False

        self._start_tray()
        self.root.after(200, self._pump_events)
        self.refresh_status()

    # -- layout --------------------------------------------------------
    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        self.notebook = notebook

        self.screen_tab = ttk.Frame(notebook, padding=12)
        self.keyboard_tab = ttk.Frame(notebook, padding=12)
        notebook.add(self.screen_tab, text="  Screen spectrum  ")
        notebook.add(self.keyboard_tab, text="  Keyboard  ")

        self._build_screen_tab(self.screen_tab)
        self._build_keyboard_tab(self.keyboard_tab)

        bar = ttk.Frame(self.root, padding=(12, 4, 12, 10))
        bar.pack(fill="x")
        self.status = ttk.Label(bar, text="", foreground="#555")
        self.status.pack(side="left")
        ttk.Button(bar, text="Hide to tray",
                   command=self.hide_to_tray).pack(side="right")
        ttk.Button(bar, text="Reset defaults",
                   command=self.reset_defaults).pack(side="right", padx=6)

    def _build_screen_tab(self, tab):
        tab.columnconfigure(1, weight=1)

        # --- animation ---
        ttk.Label(tab, text="Animation", font=("Segoe UI", 10, "bold")
                  ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.style_var = tk.StringVar()
        frame = ttk.Frame(tab)
        frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 12))
        for i, (name, cls) in enumerate(sorted(STYLES.items())):
            ttk.Radiobutton(
                frame, text=f"{cls.label}  -  {cls.description}",
                value=name, variable=self.style_var,
                command=self.on_change,
            ).grid(row=i, column=0, sticky="w", pady=1)

        # --- screens ---
        ttk.Label(tab, text="Show on which screen",
                  font=("Segoe UI", 10, "bold")
                  ).grid(row=2, column=0, columnspan=2, sticky="w")
        screens = ttk.Frame(tab)
        screens.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 12))

        self.monitor_vars = []
        for index, (mx, my, mw, mh, primary) in enumerate(self.monitors):
            var = tk.BooleanVar(value=False)
            label = (f"Screen {index + 1}   {mw} x {mh}"
                     f"{'   (primary)' if primary else ''}"
                     f"    at {mx},{my}")
            ttk.Checkbutton(screens, text=label, variable=var,
                            command=self.on_change).grid(
                row=index, column=0, sticky="w", pady=1)
            self.monitor_vars.append(var)

        ttk.Button(screens, text="All screens",
                   command=self.select_all_screens).grid(
            row=len(self.monitors), column=0, sticky="w", pady=(6, 0))

        # --- sliders ---
        ttk.Label(tab, text="Appearance", font=("Segoe UI", 10, "bold")
                  ).grid(row=4, column=0, columnspan=2, sticky="w")
        sliders = ttk.Frame(tab)
        sliders.grid(row=5, column=0, columnspan=2, sticky="ew", pady=4)
        sliders.columnconfigure(1, weight=1)

        self.wp_sliders = {}
        rows = [
            ("band", "Strip height", 10, 100, "%"),
            ("bars", "Number of bars", 8, 128, ""),
            ("height", "Bar height", 10, 90, "%"),
            ("brightness", "Brightness", 10, 100, "%"),
            ("dim", "Wallpaper dimming", 0, 90, "%"),
            ("fps", "Frame rate", 15, 60, " fps"),
        ]
        for row, (key, label, lo, hi, suffix) in enumerate(rows):
            self._slider(sliders, row, key, label, lo, hi, suffix,
                         self.wp_sliders, integer=key in ("bars",))

    def _build_keyboard_tab(self, tab):
        tab.columnconfigure(1, weight=1)
        ttk.Label(tab, text="Keyboard effect", font=("Segoe UI", 10, "bold")
                  ).grid(row=0, column=0, columnspan=2, sticky="w")

        self.effect_var = tk.StringVar()
        frame = ttk.Frame(tab)
        frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 12))
        for i, name in enumerate(sorted(EFFECTS)):
            ttk.Radiobutton(
                frame, text=KEYBOARD_EFFECTS.get(name, name),
                value=name, variable=self.effect_var,
                command=self.on_change,
            ).grid(row=i, column=0, sticky="w", pady=1)

        sliders = ttk.Frame(tab)
        sliders.grid(row=2, column=0, columnspan=2, sticky="ew")
        sliders.columnconfigure(1, weight=1)
        self.kb_sliders = {}
        self._slider(sliders, 0, "brightness", "Brightness", 10, 100, "%",
                     self.kb_sliders)

        ttk.Separator(tab, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=14)

        ttk.Label(tab, text="Services", font=("Segoe UI", 10, "bold")
                  ).grid(row=4, column=0, columnspan=2, sticky="w")
        services = ttk.Frame(tab)
        services.grid(row=5, column=0, columnspan=2, sticky="ew", pady=6)

        self.kb_state = ttk.Label(services, text="keyboard: ?", width=28)
        self.kb_state.grid(row=0, column=0, sticky="w", pady=3)
        ttk.Button(services, text="Start",
                   command=lambda: self.toggle_task(KEYBOARD_TASK, True)
                   ).grid(row=0, column=1, padx=4)
        ttk.Button(services, text="Stop",
                   command=lambda: self.toggle_task(KEYBOARD_TASK, False)
                   ).grid(row=0, column=2, padx=4)

        self.wp_state = ttk.Label(services, text="screen: ?", width=28)
        self.wp_state.grid(row=1, column=0, sticky="w", pady=3)
        ttk.Button(services, text="Start",
                   command=lambda: self.toggle_task(WALLPAPER_TASK, True)
                   ).grid(row=1, column=1, padx=4)
        ttk.Button(services, text="Stop",
                   command=lambda: self.toggle_task(WALLPAPER_TASK, False)
                   ).grid(row=1, column=2, padx=4)

    def _slider(self, parent, row, key, label, lo, hi, suffix, store,
                integer=False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
                                           pady=3)
        var = tk.DoubleVar()
        readout = ttk.Label(parent, text="", width=8, anchor="e")

        def on_move(_value):
            value = var.get()
            readout.configure(
                text=f"{int(round(value))}{suffix}" if integer or suffix
                else f"{value:.2f}")
            self.on_change()

        scale = ttk.Scale(parent, from_=lo, to=hi, variable=var,
                          command=on_move)
        scale.grid(row=row, column=1, sticky="ew", padx=8)
        readout.grid(row=row, column=2, sticky="e")
        store[key] = (var, readout, suffix, integer)

    # -- settings <-> widgets ------------------------------------------
    def _load_into_widgets(self):
        wp = self.data["wallpaper"]
        kb = self.data["keyboard"]

        self.style_var.set(wp["style"] if wp["style"] in STYLES else "bars")
        self.style_name = self.style_var.get()
        self.effect_var.set(kb["effect"] if kb["effect"] in EFFECTS
                            else "spectrum")

        spec = wp["monitors"]
        if spec == "all":
            chosen = list(range(len(self.monitors)))
        elif spec == "primary":
            chosen = [i for i, m in enumerate(self.monitors) if m[4]] or [0]
        elif isinstance(spec, (list, tuple)):
            chosen = [int(i) for i in spec]
        else:
            try:
                chosen = [int(spec)]
            except (TypeError, ValueError):
                chosen = [0]
        for i, var in enumerate(self.monitor_vars):
            var.set(i in chosen)

        for key, (var, readout, suffix, integer) in self.wp_sliders.items():
            var.set(float(wp[key]))
            readout.configure(text=f"{int(round(var.get()))}{suffix}")
        for key, (var, readout, suffix, integer) in self.kb_sliders.items():
            var.set(float(kb[key]))
            readout.configure(text=f"{int(round(var.get()))}{suffix}")

    def _collect(self):
        wp = dict(self.data["wallpaper"])
        kb = dict(self.data["keyboard"])

        wp["style"] = self.style_var.get()
        kb["effect"] = self.effect_var.get()

        chosen = [i for i, var in enumerate(self.monitor_vars) if var.get()]
        if not chosen:
            chosen = [i for i, m in enumerate(self.monitors) if m[4]] or [0]
        if len(chosen) == len(self.monitors) and len(chosen) > 1:
            wp["monitors"] = "all"
        else:
            wp["monitors"] = chosen

        for key, (var, _r, _s, integer) in self.wp_sliders.items():
            wp[key] = int(round(var.get())) if integer else round(var.get(), 2)
        for key, (var, _r, _s, integer) in self.kb_sliders.items():
            kb[key] = int(round(var.get())) if integer else round(var.get(), 2)

        return {"wallpaper": wp, "keyboard": kb}

    def on_change(self, *_args):
        if self._suspend_writes:
            return
        self.data = self._collect()
        # Mirror for the tray thread, which must not touch Tk variables.
        self.style_name = self.data["wallpaper"]["style"]
        settings_store.save(self.data)
        self.status.configure(text="Applied", foreground="#207020")
        self.root.after(1200, lambda: self.status.configure(text=""))

    def select_all_screens(self):
        for var in self.monitor_vars:
            var.set(True)
        self.on_change()

    def reset_defaults(self):
        self._suspend_writes = True
        self.data = settings_store._merge(settings_store.DEFAULTS, {})
        self._load_into_widgets()
        self._suspend_writes = False
        self.on_change()

    # -- services -------------------------------------------------------
    def toggle_task(self, name, start):
        def work():
            (task_start if start else task_stop)(name)
            self.events.put(("status", None))
        threading.Thread(target=work, daemon=True).start()
        self.status.configure(text=f"{'Starting' if start else 'Stopping'} "
                                   f"{name}...", foreground="#555")

    def refresh_status(self):
        def work():
            states = (task_state(KEYBOARD_TASK), task_state(WALLPAPER_TASK))
            self.events.put(("states", states))
        threading.Thread(target=work, daemon=True).start()
        self.root.after(4000, self.refresh_status)

    def _pump_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "states":
                    kb, wp = payload
                    self.kb_state.configure(text=f"Keyboard sync: {kb}")
                    self.wp_state.configure(text=f"Screen spectrum: {wp}")
                elif kind == "status":
                    pass
                elif kind == "style":
                    # Posted from the tray thread; apply it here on the main one.
                    self.style_var.set(payload)
                    self.on_change()
                elif kind == "show":
                    self._show_window()
                elif kind == "quit":
                    self._quit()
        except queue.Empty:
            pass
        self.root.after(200, self._pump_events)

    # -- tray -----------------------------------------------------------
    def _start_tray(self):
        try:
            import pystray
        except ImportError:
            self.tray = None
            return

        def show(_icon=None, _item=None):
            self.events.put(("show", None))

        def quit_all(_icon=None, _item=None):
            self.events.put(("quit", None))

        # pystray runs its menu on its own thread, and Tk objects may only be
        # touched from the main thread - so the menu reads a plain string
        # mirror of the style and posts changes back through the queue.
        def set_style(name):
            def handler(_icon=None, _item=None):
                self.events.put(("style", name))
            return handler

        style_menu = pystray.Menu(*[
            pystray.MenuItem(
                cls.label, set_style(name),
                checked=(lambda n: lambda _i: self.style_name == n)(name),
                radio=True)
            for name, cls in sorted(STYLES.items())
        ])

        menu = pystray.Menu(
            pystray.MenuItem("Open control panel", show, default=True),
            pystray.MenuItem("Animation", style_menu),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_all),
        )
        self.tray = pystray.Icon("music_visualiser", make_tray_image(),
                                 "Music Visualiser", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def hide_to_tray(self):
        if self.tray is None:
            self._quit()
            return
        self.root.withdraw()

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _quit(self):
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self, start_hidden=False):
        if start_hidden and self.tray is not None:
            self.root.withdraw()
        self.root.mainloop()


def main():
    if "--log" in sys.argv:
        from musiclight import _start_log
        _start_log(sys.argv[sys.argv.index("--log") + 1])
    ControlPanel().run(start_hidden="--hidden" in sys.argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
