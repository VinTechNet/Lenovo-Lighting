"""A live wallpaper spectrum that reacts to whatever is playing.

Draws over a dimmed copy of your real wallpaper, behind every application
window. Shares the audio pipeline with musiclight.py, so like the keyboard
sync it follows the default output device - Bluetooth included.

Settings live in settings.json and are applied while running, so the control
panel can change the animation or the target screen without a restart.

    python wallpaper.py                 # uses settings.json
    python wallpaper.py --style wave --monitor all
    python wallpaper.py --windowed      # normal window, for tweaking the look
"""

import argparse
import colorsys
import ctypes
import sys
import time
import tkinter as tk

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageTk

import capture_window
import deskwindow
import settings as settings_store
from musiclight import (FFT_SIZE, RingBuffer, SAMPLE_RATE, SpectrumAnalyzer,
                        LoopbackCapture, endpoint_is_bluetooth)

RING_SECONDS = 2.0

# Changing any of these means the panels have to be rebuilt from scratch.
STRUCTURAL_KEYS = ("style", "monitors", "bars", "band", "dim", "fade", "blur",
                   "height", "baseline", "hue_span", "reflection", "fill",
                   "cap_height")


# --------------------------------------------------------------------------
# background
# --------------------------------------------------------------------------
def grab_desktop_wallpaper():
    """Pixels of the real wallpaper, straight from Explorer's own window.

    Re-deriving it from the registry image means guessing at fill mode, DPI
    scaling and per-monitor wallpapers, which does not line up. Capturing what
    Explorer actually painted is exact by construction.
    Returns (image, (x, y, w, h)) or (None, None).
    """
    host, _how = deskwindow.find_wallpaper_host()
    if not host:
        return None, None
    try:
        img = capture_window.capture(host)
    except Exception:
        return None, None
    if img.getbbox() is None:      # all black - capture failed
        return None, None
    return img, deskwindow.window_rect(host)


def build_background(desktop, desktop_rect, x, y, w, h,
                     dim_pct, blur, fade_pct):
    """The slice of wallpaper our band covers, dimmed with a soft top edge."""
    img = None
    if desktop is not None:
        dx, dy = desktop_rect[0], desktop_rect[1]
        box = (x - dx, y - dy, x - dx + w, y - dy + h)
        if (box[0] >= 0 and box[1] >= 0
                and box[2] <= desktop.width and box[3] <= desktop.height):
            img = desktop.crop(box)

    if img is None:  # no usable wallpaper - fall back to a dark gradient
        ramp = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        base = np.zeros((h, w, 3), dtype=np.uint8)
        base[..., 0] = (10 + 22 * ramp).astype(np.uint8)
        base[..., 1] = (10 + 14 * ramp).astype(np.uint8)
        base[..., 2] = (24 + 40 * ramp).astype(np.uint8)
        img = Image.fromarray(base)

    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(blur))

    if dim_pct > 0:
        # Ramp the dimming in from the top edge, otherwise the band reads as a
        # rectangle pasted over the wallpaper instead of part of it.
        floor = max(0.0, 1.0 - dim_pct / 100)
        factor = np.full(h, floor, dtype=np.float32)
        fade = int(h * fade_pct / 100)
        if fade > 0:
            factor[:fade] = np.linspace(1.0, floor, fade, dtype=np.float32)
        arr = np.asarray(img, dtype=np.float32) * factor[:, None, None]
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return img


def _signature(img):
    """Cheap fingerprint so we only rebuild when the wallpaper really changed."""
    return img.resize((16, 8), Image.BILINEAR).tobytes()


def _hex(r, g, b):
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def shade_palette(hue, steps=24):
    """Colours for one band, dim through to bright, as Tk hex strings."""
    out = []
    for i in range(steps):
        t = i / (steps - 1)
        sat = 0.95 - 0.35 * t          # hot tips wash toward white
        val = 0.35 + 0.65 * t
        out.append(_hex(*colorsys.hsv_to_rgb(hue, sat, val)))
    return out


# --------------------------------------------------------------------------
# animation styles
# --------------------------------------------------------------------------
class Style:
    """One way of drawing the spectrum onto a panel's canvas."""

    name = "base"
    label = "Base"
    description = ""

    def __init__(self, panel):
        self.p = panel
        self.items = []

    def build(self):
        raise NotImplementedError

    def render(self, levels, dt):
        raise NotImplementedError

    def destroy(self):
        for item in self.items:
            self.p.canvas.delete(item)
        self.items = []

    def _track(self, *items):
        self.items.extend(items)
        return items[0] if len(items) == 1 else items


class BarsStyle(Style):
    name = "bars"
    label = "Bars"
    description = "Classic analyser columns with falling peak caps"

    def build(self):
        p = self.p
        self.bars, self.reflections, self.caps = [], [], []
        self.shade_idx = [-1] * p.n
        self.peaks = np.zeros(p.n)
        for i in range(p.n):
            left, right = p.lefts[i], p.rights[i]
            colour = p.palettes[i][0]
            self.bars.append(self._track(p.canvas.create_rectangle(
                left, p.baseline, right, p.baseline, fill=colour, width=0)))
            if p.cfg["reflection"]:
                self.reflections.append(self._track(p.canvas.create_rectangle(
                    left, p.baseline, right, p.baseline, fill=colour,
                    width=0, stipple="gray25")))
            self.caps.append(self._track(p.canvas.create_rectangle(
                left, p.baseline, right, p.baseline, fill="#ffffff", width=0)))

    def render(self, levels, dt):
        p = self.p
        cv = p.canvas
        self.peaks = np.maximum(self.peaks - p.cfg["peak_fall"] * dt, levels)
        heights = (levels * p.max_bar).astype(int)
        peak_h = (self.peaks * p.max_bar).astype(int)
        shades = p.shade_index(levels)
        base = p.baseline
        cap_h = int(p.cfg["cap_height"])
        refl = 0.38

        for i in range(p.n):
            left, right = p.lefts[i], p.rights[i]
            h = int(heights[i])
            cv.coords(self.bars[i], left, base - h, right, base)
            if shades[i] != self.shade_idx[i]:
                colour = p.palettes[i][shades[i]]
                cv.itemconfig(self.bars[i], fill=colour)
                if self.reflections:
                    cv.itemconfig(self.reflections[i], fill=colour)
                self.shade_idx[i] = shades[i]
            if self.reflections:
                cv.coords(self.reflections[i], left, base,
                          right, base + int(h * refl))
            top = base - int(peak_h[i]) - cap_h
            cv.coords(self.caps[i], left, top, right, top + cap_h)


class MirrorStyle(Style):
    name = "mirror"
    label = "Mirror"
    description = "Bars growing out from a centre line, both ways"

    def build(self):
        p = self.p
        self.centre = p.baseline - p.max_bar // 2
        self.bars = []
        self.shade_idx = [-1] * p.n
        for i in range(p.n):
            self.bars.append(self._track(p.canvas.create_rectangle(
                p.lefts[i], self.centre, p.rights[i], self.centre,
                fill=p.palettes[i][0], width=0)))

    def render(self, levels, dt):
        p = self.p
        cv = p.canvas
        half = (levels * p.max_bar / 2).astype(int)
        shades = p.shade_index(levels)
        for i in range(p.n):
            h = int(half[i])
            cv.coords(self.bars[i], p.lefts[i], self.centre - h,
                      p.rights[i], self.centre + h)
            if shades[i] != self.shade_idx[i]:
                cv.itemconfig(self.bars[i], fill=p.palettes[i][shades[i]])
                self.shade_idx[i] = shades[i]


class BlocksStyle(Style):
    name = "blocks"
    label = "Blocks"
    description = "Segmented LED columns, like a hi-fi level meter"

    SEGMENTS = 14

    def build(self):
        p = self.p
        seg = max(3, p.max_bar // self.SEGMENTS)
        gap = max(1, seg // 5)
        self.height = seg - gap
        self.cells = []
        self.lit = [0] * p.n
        self.unlit = [_hex(*colorsys.hsv_to_rgb(h, 0.7, 0.13)) for h in p.hues]
        for i in range(p.n):
            column = []
            for s in range(self.SEGMENTS):
                bottom = p.baseline - s * seg
                column.append(self._track(p.canvas.create_rectangle(
                    p.lefts[i], bottom - self.height, p.rights[i], bottom,
                    fill=self.unlit[i], width=0)))
            self.cells.append(column)

    def render(self, levels, dt):
        p = self.p
        cv = p.canvas
        target = np.clip((levels * self.SEGMENTS).astype(int),
                         0, self.SEGMENTS)
        for i in range(p.n):
            want = int(target[i])
            have = self.lit[i]
            if want == have:
                continue
            # Only repaint the segments that actually changed state.
            if want > have:
                bright = p.palettes[i][-1]
                for s in range(have, want):
                    cv.itemconfig(self.cells[i][s], fill=bright)
            else:
                for s in range(want, have):
                    cv.itemconfig(self.cells[i][s], fill=self.unlit[i])
            self.lit[i] = want


class WaveStyle(Style):
    name = "wave"
    label = "Wave"
    description = "A smooth filled curve with a colour gradient"

    def build(self):
        p = self.p
        self.quads, self.reflections = [], []
        self.shade_idx = [-1] * p.n
        for i in range(p.n - 1):
            self.quads.append(self._track(p.canvas.create_polygon(
                0, 0, 0, 0, 0, 0, 0, 0, fill=p.palettes[i][0], width=0)))
            if p.cfg["reflection"]:
                self.reflections.append(self._track(p.canvas.create_polygon(
                    0, 0, 0, 0, 0, 0, 0, 0, fill=p.palettes[i][0],
                    width=0, stipple="gray25")))

    def render(self, levels, dt):
        p = self.p
        cv = p.canvas
        base = p.baseline
        xs = p.centres
        ys = base - (levels * p.max_bar).astype(int)
        shades = p.shade_index(levels)
        refl = 0.38
        for i in range(p.n - 1):
            x0, x1 = xs[i], xs[i + 1]
            y0, y1 = int(ys[i]), int(ys[i + 1])
            cv.coords(self.quads[i], x0, y0, x1, y1, x1, base, x0, base)
            if shades[i] != self.shade_idx[i]:
                colour = p.palettes[i][shades[i]]
                cv.itemconfig(self.quads[i], fill=colour)
                if self.reflections:
                    cv.itemconfig(self.reflections[i], fill=colour)
                self.shade_idx[i] = shades[i]
            if self.reflections:
                r0 = base + int((base - y0) * refl)
                r1 = base + int((base - y1) * refl)
                cv.coords(self.reflections[i],
                          x0, r0, x1, r1, x1, base, x0, base)


class DotsStyle(Style):
    name = "dots"
    label = "Dots"
    description = "A floating dot per band over a dim column"

    def build(self):
        p = self.p
        self.dots, self.columns = [], []
        self.shade_idx = [-1] * p.n
        self.size = max(3, int((p.rights[0] - p.lefts[0]) * 0.9))
        self.dim = [_hex(*colorsys.hsv_to_rgb(h, 0.8, 0.22)) for h in p.hues]
        for i in range(p.n):
            self.columns.append(self._track(p.canvas.create_rectangle(
                p.lefts[i], p.baseline, p.rights[i], p.baseline,
                fill=self.dim[i], width=0, stipple="gray50")))
            self.dots.append(self._track(p.canvas.create_oval(
                p.lefts[i], p.baseline, p.rights[i], p.baseline,
                fill=p.palettes[i][-1], width=0)))

    def render(self, levels, dt):
        p = self.p
        cv = p.canvas
        base = p.baseline
        heights = (levels * p.max_bar).astype(int)
        shades = p.shade_index(levels)
        half = self.size // 2
        for i in range(p.n):
            left, right = p.lefts[i], p.rights[i]
            y = base - int(heights[i])
            cv.coords(self.columns[i], left, y, right, base)
            cv.coords(self.dots[i], left, y - half, right, y + half)
            if shades[i] != self.shade_idx[i]:
                cv.itemconfig(self.dots[i], fill=p.palettes[i][shades[i]])
                self.shade_idx[i] = shades[i]


STYLES = {s.name: s for s in
          (BarsStyle, MirrorStyle, BlocksStyle, WaveStyle, DotsStyle)}


# --------------------------------------------------------------------------
# one monitor's worth of visualiser
# --------------------------------------------------------------------------
class Panel:
    def __init__(self, root, monitor, cfg, desktop, desktop_rect,
                 windowed=False):
        mon_x, mon_y, mon_w, mon_h = monitor
        # Occupy only the bottom `band` percent of the monitor, so desktop
        # icons higher up stay visible.
        band_h = max(80, int(mon_h * cfg["band"] / 100))
        band_top = mon_h - band_h
        self.x, self.y = mon_x, mon_y + band_top
        self.w, self.h = mon_w, band_h
        self.cfg = cfg
        self.n = max(4, int(cfg["bars"]))

        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.geometry(f"{self.w}x{self.h}+{self.x}+{self.y}")
        self.top.configure(bg="black")
        if windowed:
            self.top.attributes("-topmost", True)

        self.canvas = tk.Canvas(self.top, width=self.w, height=self.h,
                                highlightthickness=0, bd=0, bg="black")
        self.canvas.pack(fill="both", expand=True)

        bg = build_background(desktop, desktop_rect, self.x, self.y,
                              self.w, self.h, cfg["dim"], cfg["blur"],
                              cfg["fade"])
        self.bg_image = ImageTk.PhotoImage(bg)
        self.bg_item = self.canvas.create_image(0, 0, anchor="nw",
                                                image=self.bg_image)
        self.bg_signature = _signature(bg)

        self.baseline = int(self.h * cfg["baseline"] / 100)
        self.max_bar = max(8, int(self.h * cfg["height"] / 100))
        step = self.w / self.n
        bar_w = max(1, int(step * cfg["fill"]))
        pad = (step - bar_w) / 2
        self.lefts = [int(i * step + pad) for i in range(self.n)]
        self.rights = [x + bar_w for x in self.lefts]
        self.centres = [(a + b) // 2 for a, b in zip(self.lefts, self.rights)]

        span = float(cfg["hue_span"])
        self.hues = [i / max(self.n - 1, 1) * span for i in range(self.n)]
        self.palettes = [shade_palette(h) for h in self.hues]
        self.shades = len(self.palettes[0])

        self.style = STYLES.get(cfg["style"], BarsStyle)(self)
        self.style.build()

    def shade_index(self, levels):
        return np.clip((levels * (self.shades - 1)).astype(int),
                       0, self.shades - 1)

    def render(self, levels, dt):
        self.style.render(levels, dt)

    def refresh_background(self, desktop, desktop_rect):
        """Re-cut the background; wallpaper slideshows change under us."""
        bg = build_background(desktop, desktop_rect, self.x, self.y,
                              self.w, self.h, self.cfg["dim"],
                              self.cfg["blur"], self.cfg["fade"])
        signature = _signature(bg)
        if signature == self.bg_signature:
            return False
        self.bg_image = ImageTk.PhotoImage(bg)
        self.canvas.itemconfig(self.bg_item, image=self.bg_image)
        self.canvas.tag_lower(self.bg_item)
        self.bg_signature = signature
        return True

    def pin(self, click_through=True):
        self.top.update_idletasks()
        self.hwnd = int(self.top.wm_frame(), 16)
        deskwindow.pin_above_wallpaper(self.hwnd, self.x, self.y,
                                       self.w, self.h, click_through)

    def restack(self):
        """Drop back to the desktop layer if something re-ordered us."""
        deskwindow.user32.SetWindowPos(
            deskwindow.wintypes.HWND(self.hwnd),
            deskwindow.wintypes.HWND(deskwindow.HWND_BOTTOM), 0, 0, 0, 0,
            deskwindow.SWP_NOMOVE | deskwindow.SWP_NOSIZE
            | deskwindow.SWP_NOACTIVATE)

    def destroy(self):
        try:
            self.top.destroy()
        except tk.TclError:
            pass


# --------------------------------------------------------------------------
# service
# --------------------------------------------------------------------------
def choose_monitors(spec):
    """Resolve a monitor spec to a list of (x, y, w, h)."""
    mons = deskwindow.monitors()
    if not mons:
        return []
    if spec == "all":
        chosen = mons
    elif spec == "primary":
        chosen = [m for m in mons if m[4]] or [mons[0]]
    elif isinstance(spec, (list, tuple)):
        chosen = [mons[i] for i in spec if 0 <= int(i) < len(mons)]
        if not chosen:
            chosen = [m for m in mons if m[4]] or [mons[0]]
    else:
        try:
            chosen = [mons[int(spec)]]
        except (ValueError, IndexError):
            chosen = [m for m in mons if m[4]] or [mons[0]]
    return [(m[0], m[1], m[2], m[3]) for m in chosen]


class Visualiser:
    """Owns the panels and rebuilds them when the settings change."""

    def __init__(self, root, cfg, windowed, click_through):
        self.root = root
        self.cfg = cfg
        self.windowed = windowed
        self.click_through = click_through
        self.panels = []
        self.desktop = None
        self.desktop_rect = None
        self.build()

    def build(self):
        self.desktop, self.desktop_rect = grab_desktop_wallpaper()
        geometries = choose_monitors(self.cfg["monitors"])
        self.panels = [
            Panel(self.root, g, self.cfg, self.desktop, self.desktop_rect,
                  windowed=self.windowed)
            for g in geometries
        ]
        if not self.windowed:
            for panel in self.panels:
                panel.pin(click_through=self.click_through)
        print(f"style={self.cfg['style']} monitors={self.cfg['monitors']} "
              f"panels={[(p.x, p.y, p.w, p.h) for p in self.panels]}",
              flush=True)

    def teardown(self):
        for panel in self.panels:
            panel.destroy()
        self.panels = []

    def apply(self, new_cfg):
        """Adopt new settings, rebuilding the panels only if we have to."""
        structural = any(new_cfg.get(k) != self.cfg.get(k)
                         for k in STRUCTURAL_KEYS)
        self.cfg = new_cfg
        if structural:
            self.teardown()
            self.build()
        else:
            for panel in self.panels:
                panel.cfg = new_cfg
        return structural

    def render(self, levels, dt):
        for panel in self.panels:
            panel.render(levels, dt)

    def restack(self):
        for panel in self.panels:
            panel.restack()

    def refresh_background(self):
        shot, rect = grab_desktop_wallpaper()
        if shot is None:
            return False
        self.desktop, self.desktop_rect = shot, rect
        return any(p.refresh_background(shot, rect) for p in self.panels)


def run(args):
    deskwindow.set_dpi_aware()

    # Tk's after() rounds up to the system timer tick (~15.6 ms), which caps
    # a nominal 30 fps at about 21. Asking for 1 ms resolution, as media
    # players do, lets us actually hit the requested frame rate.
    winmm = ctypes.WinDLL("winmm")
    winmm.timeBeginPeriod(1)

    cfg = settings_store.load()["wallpaper"]
    for key, value in vars(args).items():
        if value is not None and key in cfg:
            cfg[key] = value

    root = tk.Tk()
    root.withdraw()
    vis = Visualiser(root, cfg, args.windowed, not args.no_click_through)

    analyzer = [SpectrumAnalyzer(vis.cfg["bars"],
                                 dynamic_range_db=vis.cfg["dynamic_range"])]
    ring = RingBuffer(int(SAMPLE_RATE * RING_SECONDS))
    state = {"delay": 0}

    def on_device(speaker):
        bt = endpoint_is_bluetooth(str(speaker.id))
        ms = args.bluetooth_delay_ms if bt else 0
        if args.delay_ms is not None:
            ms = int(args.delay_ms)
        print(f"-> capturing '{speaker.name}' "
              f"({'Bluetooth' if bt else 'wired'}), delay {ms} ms", flush=True)
        state["delay"] = int(SAMPLE_RATE * ms / 1000)

    capture = LoopbackCapture(ring, device_id=args.device,
                              follow=not args.no_follow,
                              on_device_change=on_device)
    capture.start()

    smoothed = [np.zeros(vis.cfg["bars"])]
    watcher = settings_store.Watcher()
    last = [time.monotonic()]
    frames = [0]
    started = time.monotonic()

    def coefficients():
        fps = max(1.0, float(vis.cfg["fps"]))
        attack = 1.0 - np.exp(-1.0 / max(vis.cfg["attack_ms"] / 1000.0 * fps,
                                         1e-6))
        decay = 1.0 - np.exp(-1.0 / max(vis.cfg["decay_ms"] / 1000.0 * fps,
                                        1e-6))
        return fps, attack, decay

    def tick():
        now = time.monotonic()
        dt = min(now - last[0], 0.25)
        last[0] = now

        if args.live:
            changed = watcher.poll()
            if changed is not None:
                new_cfg = changed["wallpaper"]
                rebuilt = vis.apply(new_cfg)
                if rebuilt:
                    analyzer[0] = SpectrumAnalyzer(
                        new_cfg["bars"],
                        dynamic_range_db=new_cfg["dynamic_range"])
                    smoothed[0] = np.zeros(new_cfg["bars"])
                    if not args.windowed:
                        vis.restack()
                print("settings reloaded", flush=True)

        fps, attack, decay = coefficients()
        samples = ring.read(FFT_SIZE, state["delay"])
        if samples is not None:
            levels, _peak = analyzer[0].compute(samples)
            current = smoothed[0]
            coef = np.where(levels > current, attack, decay)
            current += (levels - current) * coef
            vis.render(current * (vis.cfg["brightness"] / 100.0), dt)

        frames[0] += 1
        # Clicking the desktop can raise it above us; drop back periodically.
        if not args.windowed and frames[0] % int(max(fps, 1) * 2) == 0:
            vis.restack()
        if args.fps_report and frames[0] % 120 == 0:
            print(f"  {frames[0] / (now - started):.1f} fps rendered",
                  flush=True)
        root.after(max(1, int(1000 / fps)), tick)

    def refresh_wallpaper():
        if not args.windowed and args.bg_refresh > 0:
            if vis.refresh_background():
                print("wallpaper changed - background re-synced", flush=True)
            root.after(int(args.bg_refresh * 1000), refresh_wallpaper)

    if args.bg_refresh > 0:
        root.after(int(args.bg_refresh * 1000), refresh_wallpaper)
    root.after(10, tick)

    print("running - Ctrl+C in this console to stop", flush=True)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        capture.stop()
        try:
            root.destroy()
        except tk.TclError:
            pass
        winmm.timeEndPeriod(1)
        deskwindow.refresh_desktop()
    return 0


def main():
    p = argparse.ArgumentParser(
        description="Live wallpaper spectrum that follows the default audio "
                    "output, Bluetooth included. Reads settings.json.")
    # Anything left as None falls back to settings.json.
    p.add_argument("--style", choices=sorted(STYLES), default=None)
    p.add_argument("--monitor", dest="monitors", default=None,
                   help="'primary', 'all', or a monitor index")
    p.add_argument("--bars", type=int, default=None)
    p.add_argument("--fps", type=float, default=None)
    p.add_argument("--brightness", type=float, default=None)
    p.add_argument("--band", type=float, default=None,
                   help="strip height as %% of the screen, from the bottom")
    p.add_argument("--dim", type=float, default=None)
    p.add_argument("--fade", type=float, default=None)
    p.add_argument("--blur", type=float, default=None)
    p.add_argument("--height", type=float, default=None)
    p.add_argument("--baseline", type=float, default=None)
    p.add_argument("--hue-span", dest="hue_span", type=float, default=None)
    p.add_argument("--dynamic-range", dest="dynamic_range", type=float,
                   default=None)

    p.add_argument("--windowed", action="store_true",
                   help="draw in a normal on-top window instead")
    p.add_argument("--no-click-through", action="store_true")
    p.add_argument("--no-live", dest="live", action="store_false",
                   help="ignore later edits to settings.json")
    p.add_argument("--bg-refresh", type=float, default=20.0,
                   help="seconds between wallpaper re-checks; 0 disables")
    p.add_argument("--delay-ms", default=None)
    p.add_argument("--bluetooth-delay-ms", type=int, default=180)
    p.add_argument("--device", default=None)
    p.add_argument("--no-follow", action="store_true")
    p.add_argument("--fps-report", action="store_true")
    p.add_argument("--log", default=None,
                   help="append output here; needed under pythonw, which "
                        "otherwise discards crashes silently")
    args = p.parse_args()

    if args.log:
        from musiclight import _start_log
        _start_log(args.log)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
