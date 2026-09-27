"""Sync Legion keyboard RGB zones to whatever is playing - including Bluetooth.

Lenovo's own audio effect only reacts to the internal speakers. This captures
the default *render endpoint* via WASAPI loopback instead, so it follows the
audio wherever it goes: speakers, HDMI, or a Bluetooth headset.

Usage:
    python musiclight.py                  # spectrum effect, follows default device
    python musiclight.py --effect vu
    python musiclight.py --list-devices
"""

import argparse
import ctypes
import os
import signal
import sys
import threading
import time
import warnings

import numpy as np
import soundcard as sc

import contention
import settings as settings_store
from lamparray import LampArray, LampArrayError

# Bluetooth endpoints glitch often enough that this warning is pure noise.
warnings.filterwarnings("ignore", message="data discontinuity in recording")

SAMPLE_RATE = 48000
FFT_SIZE = 2048
BLOCK = 1024
RING_SECONDS = 2.0
DEVICE_POLL_SECONDS = 2.0


# --------------------------------------------------------------------------
# audio plumbing
# --------------------------------------------------------------------------
class RingBuffer:
    """Mono float32 ring buffer supporting delayed reads."""

    def __init__(self, capacity):
        self.buf = np.zeros(capacity, dtype=np.float32)
        self.cap = capacity
        self.write_pos = 0
        self.total = 0
        self.lock = threading.Lock()

    def write(self, data):
        n = len(data)
        if n >= self.cap:
            data = data[-self.cap:]
            n = len(data)
        with self.lock:
            end = self.write_pos + n
            if end <= self.cap:
                self.buf[self.write_pos:end] = data
            else:
                split = self.cap - self.write_pos
                self.buf[self.write_pos:] = data[:split]
                self.buf[:n - split] = data[split:]
            self.write_pos = end % self.cap
            self.total += n

    def read(self, n, delay=0):
        """Most recent `n` samples, ending `delay` samples in the past."""
        with self.lock:
            if self.total < n + delay or n + delay > self.cap:
                return None
            end = (self.write_pos - delay) % self.cap
            start = (end - n) % self.cap
            if start < end:
                return self.buf[start:end].copy()
            return np.concatenate((self.buf[start:], self.buf[:end]))


_cfgmgr32 = ctypes.WinDLL("cfgmgr32")
CR_SUCCESS = 0
CM_LOCATE_DEVNODE_NORMAL = 0
_BLUETOOTH_ENUMERATORS = ("BTHENUM", "BTHHFENUM", "BTHLE")


def _device_parent_id(instance_id):
    """Parent device instance id, via the config manager (no subprocess)."""
    devinst = ctypes.c_ulong()
    if _cfgmgr32.CM_Locate_DevNodeW(
            ctypes.byref(devinst), ctypes.c_wchar_p(instance_id),
            CM_LOCATE_DEVNODE_NORMAL) != CR_SUCCESS:
        return None
    parent = ctypes.c_ulong()
    if _cfgmgr32.CM_Get_Parent(
            ctypes.byref(parent), devinst, 0) != CR_SUCCESS:
        return None
    buf = ctypes.create_unicode_buffer(512)
    if _cfgmgr32.CM_Get_Device_IDW(parent, buf, len(buf), 0) != CR_SUCCESS:
        return None
    return buf.value


def endpoint_is_bluetooth(device_id):
    """True if a WASAPI endpoint id belongs to a Bluetooth radio device.

    Walks up to the endpoint's parent device and looks at which enumerator
    created it. This used to shell out to PowerShell, which was slow enough
    to time out when several copies started at once and silently report
    Bluetooth devices as wired.
    """
    parent = _device_parent_id(f"SWD\\MMDEVAPI\\{device_id}")
    if not parent:
        return False
    return parent.upper().startswith(_BLUETOOTH_ENUMERATORS)


class LoopbackCapture(threading.Thread):
    """Continuously loopback-captures the default (or chosen) output device."""

    daemon = True

    def __init__(self, ring, device_id=None, follow=True, on_device_change=None):
        super().__init__(name="loopback-capture")
        self.ring = ring
        self.device_id = device_id
        self.follow = follow
        self.on_device_change = on_device_change
        self.current = None
        self.error = None
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _target_device(self):
        if self.device_id:
            return sc.get_speaker(self.device_id)
        return sc.default_speaker()

    def run(self):
        # soundcard talks COM; worker threads need their own apartment.
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0)
        except Exception:
            pass

        while not self._stop.is_set():
            try:
                speaker = self._target_device()
                if speaker is None:
                    time.sleep(1.0)
                    continue
                mic = sc.get_microphone(str(speaker.id), include_loopback=True)
                self.current = speaker
                self.error = None
                if self.on_device_change:
                    self.on_device_change(speaker)

                with mic.recorder(samplerate=SAMPLE_RATE, channels=2,
                                  blocksize=BLOCK // 2) as rec:
                    next_poll = time.monotonic() + DEVICE_POLL_SECONDS
                    while not self._stop.is_set():
                        data = rec.record(numframes=BLOCK)
                        if data.ndim > 1:
                            data = data.mean(axis=1)
                        self.ring.write(data.astype(np.float32))

                        if self.follow and time.monotonic() >= next_poll:
                            next_poll = time.monotonic() + DEVICE_POLL_SECONDS
                            try:
                                if sc.default_speaker().id != speaker.id:
                                    break  # default moved - reopen on it
                            except Exception:
                                break
            except Exception as exc:
                self.error = exc
                self.current = None
                time.sleep(1.0)


# --------------------------------------------------------------------------
# DSP
# --------------------------------------------------------------------------
class SpectrumAnalyzer:
    """Log-spaced band levels, loudness-normalised to 0..1."""

    def __init__(self, n_bands, sample_rate=SAMPLE_RATE, fft_size=FFT_SIZE,
                 fmin=40.0, fmax=14000.0, dynamic_range_db=45.0):
        self.fft_size = fft_size
        self.dynamic_range_db = dynamic_range_db
        self.window = np.hanning(fft_size).astype(np.float32)

        freqs = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
        edges = np.geomspace(fmin, fmax, n_bands + 1)
        self.bins = []
        for i in range(n_bands):
            idx = np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0]
            if idx.size == 0:  # band narrower than one FFT bin
                idx = np.array([int(np.argmin(np.abs(freqs - edges[i])))])
            self.bins.append(idx)

        # Music energy falls with frequency; tilt up so treble zones aren't dead.
        centers = np.sqrt(edges[:-1] * edges[1:])
        self.tilt = (centers / centers[0]) ** 0.5
        self.centers = centers
        self.ceiling = 1e-6

    def compute(self, samples):
        spectrum = np.abs(np.fft.rfft(samples * self.window))
        power = spectrum * spectrum
        bands = np.array([power[idx].mean() for idx in self.bins]) * self.tilt

        peak = float(bands.max())
        # AGC: jump up quickly, drift down slowly, so quiet tracks still light up.
        coef = 0.30 if peak > self.ceiling else 0.0015
        self.ceiling += (peak - self.ceiling) * coef
        self.ceiling = max(self.ceiling, 1e-10)

        db = 10.0 * np.log10(bands / self.ceiling + 1e-12)
        levels = np.clip(1.0 + db / self.dynamic_range_db, 0.0, 1.0)
        return levels, peak

    def centroid(self, levels):
        """Normalised spectral centroid, 0 (bass) .. 1 (treble)."""
        total = levels.sum()
        if total <= 1e-9:
            return 0.0
        idx = float((levels * np.arange(len(levels))).sum() / total)
        return idx / max(len(levels) - 1, 1)


def hsv_to_rgb(h, s, v):
    """Vectorised HSV -> RGB, all inputs/outputs 0..1."""
    h = np.asarray(h, dtype=np.float64) % 1.0
    s = np.clip(np.asarray(s, dtype=np.float64), 0, 1)
    v = np.clip(np.asarray(v, dtype=np.float64), 0, 1)
    i = np.floor(h * 6.0)
    f = h * 6.0 - i
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    i = i.astype(int) % 6
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return r, g, b


# --------------------------------------------------------------------------
# effects
# --------------------------------------------------------------------------
class Effect:
    name = "effect"

    def __init__(self, n_zones, analyzer):
        self.n = n_zones
        self.analyzer = analyzer

    def render(self, levels, peak, dt):
        raise NotImplementedError


class SpectrumEffect(Effect):
    """Zones map left-to-right to bass -> treble, hue red -> violet."""

    name = "spectrum"

    def __init__(self, n_zones, analyzer, hue_span=0.75, gamma=1.15):
        super().__init__(n_zones, analyzer)
        self.hues = np.linspace(0.0, hue_span, n_zones)
        self.gamma = gamma

    def render(self, levels, peak, dt):
        v = np.clip(levels, 0, 1) ** self.gamma
        r, g, b = hsv_to_rgb(self.hues, np.ones(self.n), v)
        return np.stack([r, g, b], axis=1)


class VuEffect(Effect):
    """Zones fill from the left with loudness; green -> yellow -> red."""

    name = "vu"

    def __init__(self, n_zones, analyzer):
        super().__init__(n_zones, analyzer)
        # Hue 0.33 (green) down to 0.0 (red) across the bar.
        self.hues = np.linspace(0.33, 0.0, n_zones)

    def render(self, levels, peak, dt):
        loudness = float(np.clip(levels.mean() * 1.6, 0, 1))
        lit = loudness * self.n
        fill = np.clip(lit - np.arange(self.n), 0.0, 1.0)
        r, g, b = hsv_to_rgb(self.hues, np.ones(self.n), fill)
        return np.stack([r, g, b], axis=1)


class PulseEffect(Effect):
    """Whole keyboard one colour; brightness = loudness, hue = spectral centroid."""

    name = "pulse"

    def __init__(self, n_zones, analyzer):
        super().__init__(n_zones, analyzer)
        self.hue = 0.0

    def render(self, levels, peak, dt):
        target = self.analyzer.centroid(levels) * 0.75
        self.hue += (target - self.hue) * min(1.0, dt * 4.0)
        v = float(np.clip(levels.mean() * 1.8, 0, 1)) ** 0.7
        r, g, b = hsv_to_rgb(np.full(self.n, self.hue), np.ones(self.n),
                             np.full(self.n, v))
        return np.stack([r, g, b], axis=1)


class WaveEffect(Effect):
    """Bass hits launch a colour ripple outward from the centre."""

    name = "wave"

    def __init__(self, n_zones, analyzer, speed=18.0, decay=1.6):
        super().__init__(n_zones, analyzer)
        self.speed = speed
        self.decay = decay
        self.energy = np.zeros(n_zones)
        self.hue = 0.0
        self.bass_avg = 0.0
        self.ripples = []  # (radius, strength, hue)

    def render(self, levels, peak, dt):
        n_bass = max(1, self.n // 6)
        bass = float(levels[:n_bass].mean())
        self.bass_avg += (bass - self.bass_avg) * min(1.0, dt * 2.0)

        if bass > self.bass_avg * 1.35 and bass > 0.25:
            self.hue = (self.hue + 0.17) % 1.0
            self.ripples.append([0.0, min(1.0, bass), self.hue])
            self.bass_avg = bass

        centre = (self.n - 1) / 2.0
        positions = np.arange(self.n)
        rgb = np.zeros((self.n, 3))
        alive = []
        for ripple in self.ripples:
            radius, strength, hue = ripple
            radius += self.speed * dt
            strength -= self.decay * dt
            if strength <= 0.01 or radius > self.n:
                continue
            ripple[0], ripple[1] = radius, strength
            band = np.exp(-((np.abs(positions - centre) - radius) ** 2) / 2.0)
            r, g, b = hsv_to_rgb(np.full(self.n, hue), np.ones(self.n),
                                 np.clip(band * strength, 0, 1))
            rgb += np.stack([r, g, b], axis=1)
            alive.append(ripple)
        self.ripples = alive[-12:]

        # Keep a dim floor so the keyboard never looks broken mid-track.
        rgb += 0.06 * float(np.clip(levels.mean() * 2, 0, 1))
        return np.clip(rgb, 0, 1)


EFFECTS = {e.name: e for e in (SpectrumEffect, VuEffect, PulseEffect, WaveEffect)}


# --------------------------------------------------------------------------
# service
# --------------------------------------------------------------------------
def _start_log(path):
    """Send stdout/stderr to a file, trimming it if it has grown large."""
    try:
        if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
            os.replace(path, path + ".old")
        stream = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        return
    sys.stdout = stream
    sys.stderr = stream
    print(f"\n=== started {time.strftime('%Y-%m-%d %H:%M:%S')} ===")


def _install_signal_handlers():
    """Make service-manager / taskkill shutdowns unwind like Ctrl+C.

    Without this a stop would leave Dynamic Lighting and Lenovo's service
    switched off, because the restore happens in a finally block.
    """
    def handler(signum, frame):
        raise KeyboardInterrupt

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass


def run(args):
    _install_signal_handlers()

    recovered = contention.recover() if args.recover_only else None
    if args.recover_only:
        print(f"recovered settings: {recovered}" if recovered
              else "nothing to recover")
        return 0

    with contention.SuspendControllers(
            dynamic_lighting_off=not args.keep_dynamic_lighting,
            suspend_lenovo=args.suspend_lenovo):
        if not args.keep_dynamic_lighting:
            print("Windows Dynamic Lighting suspended (restored on exit)")
        if args.suspend_lenovo:
            print("Lenovo lighting agent suspended (restarted on exit)")
        time.sleep(0.5)  # let the other controllers let go
        return _run_loop(args)


def _run_loop(args):
    try:
        lamps = LampArray()
    except LampArrayError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    n = lamps.lamp_count
    fps = min(args.fps, lamps.max_fps)
    print(f"{lamps.kind_name} LampArray: {n} zones, driving at {fps:.0f} fps")

    # settings.json is the live source of truth; CLI flags override it.
    kb = settings_store.load()["keyboard"]
    effect_name = args.effect or kb["effect"]
    if effect_name not in EFFECTS:
        effect_name = "spectrum"
    brightness_pct = (args.brightness if args.brightness is not None
                      else kb["brightness"])
    print(f"effect={effect_name} brightness={brightness_pct:.0f}%")

    analyzer = SpectrumAnalyzer(n, dynamic_range_db=args.dynamic_range)
    effect = EFFECTS[effect_name](n, analyzer)
    watcher = settings_store.Watcher()
    ring = RingBuffer(int(SAMPLE_RATE * RING_SECONDS))

    state = {"delay_samples": 0, "device": None}

    def on_device(speaker):
        state["device"] = speaker
        if args.delay_ms == "auto":
            bt = endpoint_is_bluetooth(str(speaker.id))
            ms = args.bluetooth_delay_ms if bt else 0
            tag = "Bluetooth" if bt else "wired"
            print(f"\n-> capturing '{speaker.name}' ({tag}), "
                  f"light delay {ms} ms")
        else:
            ms = int(args.delay_ms)
            print(f"\n-> capturing '{speaker.name}', light delay {ms} ms")
        state["delay_samples"] = int(SAMPLE_RATE * ms / 1000)

    capture = LoopbackCapture(
        ring, device_id=args.device, follow=not args.no_follow,
        on_device_change=on_device,
    )
    capture.start()

    smoothed = np.zeros(n)
    attack = 1.0 - np.exp(-1.0 / max(args.attack_ms / 1000.0 * fps, 1e-6))
    decay = 1.0 - np.exp(-1.0 / max(args.decay_ms / 1000.0 * fps, 1e-6))
    brightness = brightness_pct / 100.0

    silent_since = None
    handed_back = False
    frame_time = 1.0 / fps
    idle_enabled = args.idle_timeout > 0

    lamps.set_autonomous(False)
    try:
        while True:
            start = time.monotonic()

            if args.live:
                changed = watcher.poll()
                if changed is not None:
                    kb = changed["keyboard"]
                    if kb["effect"] in EFFECTS and kb["effect"] != effect_name:
                        effect_name = kb["effect"]
                        effect = EFFECTS[effect_name](n, analyzer)
                    brightness = kb["brightness"] / 100.0
                    print(f"\nsettings reloaded: effect={effect_name} "
                          f"brightness={kb['brightness']:.0f}%")

            samples = ring.read(FFT_SIZE, state["delay_samples"])

            if samples is None:
                time.sleep(0.05)
                continue

            levels, peak = analyzer.compute(samples)
            loud = float(np.abs(samples).max())

            # Idle handling: give the keyboard back to its normal lighting,
            # but only after a sustained silence, so pauses between tracks
            # don't cause it to flap in and out of the system animation.
            if loud < args.silence_threshold:
                if silent_since is None:
                    silent_since = start
                elif (idle_enabled and not handed_back
                        and start - silent_since > args.idle_timeout):
                    lamps.set_all((0, 0, 0))
                    lamps.set_autonomous(True)
                    handed_back = True
                    print("\nidle - released keyboard to system lighting")
            else:
                silent_since = None
                if handed_back:
                    lamps.set_autonomous(False)
                    handed_back = False
                    print("\naudio resumed - keyboard reclaimed")

            if handed_back:
                time.sleep(0.1)
                continue

            coef = np.where(levels > smoothed, attack, decay)
            smoothed += (levels - smoothed) * coef

            rgb = effect.render(smoothed, peak, frame_time) * brightness
            colors = (np.clip(rgb, 0, 1) * 255).astype(int).tolist()

            # Re-assert host control every frame. Other lighting controllers
            # flip the device back to its own animation; out-writing them is
            # what keeps the visualiser stable.
            if args.reassert:
                lamps.set_autonomous(False)
            lamps.update_lamps([tuple(c) for c in colors])

            if args.meter:
                bar = "".join("#" if v > 0.66 else "+" if v > 0.33 else
                              "." if v > 0.08 else " " for v in smoothed)
                dev = state["device"].name[:24] if state["device"] else "no device"
                print(f"\r[{bar}] {dev:<24}", end="", flush=True)

            elapsed = time.monotonic() - start
            if elapsed < frame_time:
                time.sleep(frame_time - elapsed)
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        capture.stop()
        lamps.close()
    return 0


def list_devices():
    default = sc.default_speaker()
    print("Output devices (loopback sources):")
    for spk in sc.all_speakers():
        mark = "  <== DEFAULT" if spk.id == default.id else ""
        bt = " [Bluetooth]" if endpoint_is_bluetooth(str(spk.id)) else ""
        print(f"  {spk.name}{bt}{mark}\n      id: {spk.id}")


def main():
    p = argparse.ArgumentParser(
        description="Sync Legion keyboard lighting to music on any output "
                    "device, including Bluetooth.")
    # effect/brightness default to settings.json so the control panel governs.
    p.add_argument("--effect", choices=sorted(EFFECTS), default=None)
    p.add_argument("--fps", type=float, default=60.0)
    p.add_argument("--brightness", type=float, default=None,
                   help="overall brightness percent (default from settings)")
    p.add_argument("--no-live", dest="live", action="store_false",
                   help="ignore later edits to settings.json")
    p.add_argument("--delay-ms", default="auto",
                   help="delay lights to match output latency; "
                        "'auto' uses --bluetooth-delay-ms on BT devices")
    p.add_argument("--bluetooth-delay-ms", type=int, default=180,
                   help="delay applied to Bluetooth endpoints (default 180)")
    p.add_argument("--attack-ms", type=float, default=35.0)
    p.add_argument("--decay-ms", type=float, default=320.0)
    p.add_argument("--dynamic-range", type=float, default=32.0,
                   help="dB below peak that maps to unlit; lower = more contrast")
    p.add_argument("--silence-threshold", type=float, default=0.0008)
    p.add_argument("--idle-timeout", type=float, default=20.0,
                   help="seconds of silence before handing the keyboard back; "
                        "0 disables handing back entirely")
    p.add_argument("--no-reassert", dest="reassert", action="store_false",
                   help="don't re-assert host control every frame")
    p.add_argument("--keep-dynamic-lighting", action="store_true",
                   help="leave Windows Dynamic Lighting on (it will fight us)")
    p.add_argument("--suspend-lenovo", action="store_true",
                   help="stop Lenovo's lighting agent while running "
                        "(needs admin; restarted on exit)")
    p.add_argument("--device", default=None,
                   help="pin to a specific output device id (see --list-devices)")
    p.add_argument("--no-follow", action="store_true",
                   help="don't switch when the default output device changes")
    p.add_argument("--meter", action="store_true",
                   help="draw a live spectrum meter in the console")
    p.add_argument("--recover-only", action="store_true",
                   help="restore settings left behind by a killed run, then exit")
    p.add_argument("--log", default=None,
                   help="append output here; needed under pythonw, which "
                        "otherwise discards crashes silently")
    p.add_argument("--list-devices", action="store_true")
    args = p.parse_args()

    if args.log:
        _start_log(args.log)

    if args.list_devices:
        list_devices()
        return 0
    if args.delay_ms != "auto":
        try:
            int(args.delay_ms)
        except ValueError:
            p.error("--delay-ms must be an integer or 'auto'")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
