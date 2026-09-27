# Legion music visualisers (Bluetooth included)

Two things that react to whatever is playing, sharing one audio pipeline:

- **`musiclight.py`** — the keyboard's 24 RGB zones
- **`wallpaper.py`** — a spectrum across the bottom of the desktop

Both follow the *default Windows output device*, so unlike Lenovo's built-in
audio effect they work over Bluetooth. **`control_panel.py`** drives both from
the system tray.

---

# Control panel (`control_panel.py`)

```powershell
python control_panel.py            # opens the window
python control_panel.py --hidden   # starts minimised to the tray
```

Pick the animation, choose which screens it plays on, tune the look, and
start/stop either service. Every change is written to `settings.json` and
applied **live** — the running visualisers reload within a second, nothing
restarts.

**It hides to the tray, not the taskbar.** Closing the window (or "Hide to
tray") leaves it running in the notification area; right-click the tray icon to
reopen it, switch animation, or quit. Windows 11 files new tray icons under the
`^` overflow arrow by default — drag it down onto the taskbar to pin it.

Start it hidden at every logon (no admin needed):

```powershell
powershell -ExecutionPolicy Bypass -File install_panel_task.ps1
```

### Animation styles

| Style | Looks like |
| --- | --- |
| `bars` | Classic analyser columns with falling peak caps |
| `blocks` | Segmented LED columns, like a hi-fi level meter |
| `mirror` | Bars growing out from a centre line, both ways |
| `wave` | A smooth filled curve with a colour gradient |
| `dots` | A floating dot per band over a dim column |

### Which screen

The panel lists every monitor with its resolution and position; tick any
combination. Ticking all of them stores `"all"`, so newly attached monitors are
picked up too. The same thing from the command line:

```powershell
python wallpaper.py --monitor all
python wallpaper.py --monitor 1
```

Settings live in `settings.json`; delete it to return to defaults. The CLI
flags still work and override the file at startup, and `--no-live` makes a
process ignore later edits.

---

# Lenovo Legion keyboard music sync (Bluetooth included)

Lenovo's built-in audio lighting effect only reacts to the internal speakers.
This service captures the **default Windows render endpoint** via WASAPI
loopback instead, so it follows the audio wherever it goes — speakers, HDMI,
or a Bluetooth headset — and drives the keyboard's 24 RGB zones in time.

Verified on: **Legion 5 15IPH11 (83RW)**, ITE controller `048D:C615`,
24-zone HID LampArray, 255 levels per channel, 417 fps ceiling.

## Quick start

```powershell
python musiclight.py                    # spectrum effect, follows default device
python musiclight.py --meter            # plus a live console spectrum meter
python musiclight.py --effect vu
python musiclight.py --list-devices
```

Stop with Ctrl+C — it restores everything it changed.

### Run automatically at logon

From an **elevated** PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File install_task.ps1
Start-ScheduledTask -TaskName LenovoKeyboardMusicSync
```

Remove it again with `install_task.ps1 -Uninstall`.

`Stop-ScheduledTask` terminates the process outright rather than letting it
clean up, so after stopping the task put the lighting settings back with:

```powershell
python musiclight.py --recover-only
```

## How it works

1. **Audio** — `soundcard` opens a WASAPI **loopback** capture on whatever the
   current default output device is. Because it taps the render endpoint rather
   than a soundcard input, Bluetooth works exactly like the speakers. The
   capture thread polls the default device every 2 s and reopens itself when it
   changes, so plugging in or connecting headphones is picked up automatically.
2. **DSP** — a 2048-point FFT is folded into 24 log-spaced bands (40 Hz –
   14 kHz), tilted to compensate for music's falling energy at high frequency,
   then normalised by a slow AGC so quiet tracks still light up. Per-zone
   attack/decay smoothing keeps it musical rather than twitchy.
3. **Lighting** — the keyboard is a standard **HID LampArray** (HID usage page
   `0x59`), so it's driven through the public spec rather than a
   reverse-engineered vendor protocol. `hidraw.py` is a dependency-free ctypes
   binding to the Win32 HID API; `lamparray.py` implements the LampArray
   reports.

## Bluetooth latency

Loopback capture taps the audio *before* it is transmitted, so over Bluetooth
the lights would otherwise run ahead of what you hear. The service detects
Bluetooth endpoints automatically (their PnP parent is `BTHENUM`/`BTHHFENUM`)
and delays the lights to compensate.

```powershell
python musiclight.py --bluetooth-delay-ms 220   # lights still early? raise it
python musiclight.py --delay-ms 0               # force a fixed delay instead
```

## Contention: why it needs to suspend other controllers

Three things want to drive this keyboard, and the last writer wins:

| Controller | Effect |
| --- | --- |
| Windows Dynamic Lighting | Claims every HID LampArray and repaints over us |
| Lenovo `LenovoLightingService` + `LenovoLighting.exe` | Legion Space's effect engine repaints over us |
| The keyboard firmware | Runs its own animation unless `AutonomousMode = 0` |

So the service, by default, turns Windows Dynamic Lighting off for the duration
and re-asserts `AutonomousMode = 0` on every frame. Suspending Lenovo's agent
as well (`--suspend-lenovo`, needs admin) is what makes it fully stable on this
machine — that's what the scheduled task installs.

Everything is put back on exit. Because Dynamic Lighting is a *registry*
setting, a hard kill would otherwise leave it switched off across reboots — so
the service records your original settings to `.suspend_state.json` before
touching anything. The next run restores them automatically; you can also do it
by hand:

```powershell
python restore.py                  # full reset, also hands zones back to firmware
python musiclight.py --recover-only  # just put the suspended settings back
```

## Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--effect` | from `settings.json` | `spectrum`, `vu`, `pulse`, `wave` |
| `--fps` | `60` | Frame rate (device allows up to 417) |
| `--brightness` | `100` | Overall brightness percent |
| `--delay-ms` | `auto` | Light delay; `auto` applies the Bluetooth value on BT devices |
| `--bluetooth-delay-ms` | `180` | Delay used for Bluetooth endpoints |
| `--attack-ms` / `--decay-ms` | `35` / `320` | Per-zone response; raise decay for a calmer look |
| `--dynamic-range` | `32` | dB below peak that reads as unlit; **lower = more contrast** |
| `--idle-timeout` | `20` | Seconds of silence before handing the keyboard back; `0` never hands back |
| `--device` | default | Pin to one output device (see `--list-devices`) |
| `--no-follow` | off | Don't switch when the default output device changes |
| `--suspend-lenovo` | off | Stop Lenovo's lighting agent while running (admin) |
| `--keep-dynamic-lighting` | off | Leave Windows Dynamic Lighting on (it will fight) |
| `--no-reassert` | off | Stop re-asserting host control each frame |
| `--meter` | off | Live console spectrum meter |
| `--recover-only` | off | Restore settings left by a killed run, then exit |

## Tuning the look

- **Too washed out / everything lit** — lower `--dynamic-range` (try `30`).
- **Too dim** — raise `--brightness`, or raise `--dynamic-range`.
- **Too twitchy** — raise `--decay-ms` (try `300`).
- **Lights ahead of the sound** — raise `--bluetooth-delay-ms`.

## Files

| File | Purpose |
| --- | --- |
| `control_panel.py` | Tray control panel for both visualisers |
| `settings.py` | Shared, live-reloadable settings store |
| `musiclight.py` | Keyboard service: capture → DSP → effects → lamps |
| `wallpaper.py` | Desktop spectrum visualiser and its animation styles |
| `deskwindow.py` | Desktop window placement, DPI and monitor geometry |
| `capture_window.py` | Screenshot a window by HWND, even when covered |
| `lamparray.py` | HID LampArray driver (reports 1–6) |
| `hidraw.py` | Dependency-free ctypes binding to the Win32 HID API |
| `dynamic_lighting.py` | Windows Dynamic Lighting on/off |
| `lenovo_service.py` | Suspend/restore Lenovo's lighting agent |
| `contention.py` | Suspends both, with crash-safe recording of your originals |
| `restore.py` | Put everything back after a hard kill |
| `install_task.ps1` | Register/remove the logon task |
| `enum_hid.py`, `probe_*.py`, `winrt_probe.py`, `diagnose.py` | Hardware investigation tools used to work the protocol out; kept for future debugging |

---

# Desktop wallpaper spectrum (`wallpaper.py`)

A spectrum analyser drawn across the bottom of the desktop, over a dimmed copy
of your own wallpaper, so it looks like the wallpaper itself is reacting.

```powershell
python wallpaper.py                   # primary monitor
python wallpaper.py --monitor all
python wallpaper.py --band 60         # taller strip
python wallpaper.py --windowed        # normal window, handy for tweaking
```

### Run automatically at logon

No admin needed — it only draws on the desktop:

```powershell
powershell -ExecutionPolicy Bypass -File install_wallpaper_task.ps1
Start-ScheduledTask -TaskName DesktopMusicSpectrum
```

Remove with `install_wallpaper_task.ps1 -Uninstall`.

### Where it sits, and the one compromise

The classic live-wallpaper trick re-parents a window into Explorer's `WorkerW`
so it draws *behind the desktop icons*. On this Windows 11 build that no longer
works — the desktop is composited in a way that never paints a re-parented
foreign window, whether it is added to `WorkerW`, to `Progman`, as `WS_POPUP`
or converted to `WS_CHILD`. (This is why several live-wallpaper tools broke on
recent builds. `probe_layers.py` and `probe_wschild.py` demonstrate it.)

So instead it is a normal top-level window pinned to the **bottom of the
z-order**, with the desktop pushed below it:

- it draws above the wallpaper and behind every application window
- it is invisible while you work, and appears when you show the desktop
- it never takes focus and stays out of the taskbar and Alt+Tab
- clicks pass straight through it to the desktop underneath

The compromise: it covers desktop icons within its strip (they remain
clickable). `--band` controls how much of the screen it uses — lower it if it
covers icons you need to see.

The background is captured from Explorer's own wallpaper window rather than
re-rendered from the image file, because re-deriving it means guessing at fill
mode, DPI scaling and per-monitor wallpapers — which does not line up. It is
re-checked every `--bg-refresh` seconds so wallpaper slideshows stay in sync.

### Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--monitor` | `primary` | `primary`, `all`, or a monitor index |
| `--band` | `38` | Strip height as %% of the screen, from the bottom |
| `--bars` | `64` | Number of spectrum bars |
| `--fps` | `45` | Frame rate |
| `--dim` | `55` | How much to darken the wallpaper behind the bars |
| `--fade` | `55` | %% of the band over which dimming ramps in, hiding the seam |
| `--blur` | `0` | Blur radius for the background |
| `--height` | `42` | Max bar height as %% of screen height |
| `--baseline` | `88` | Where bars stand, as %% down the screen |
| `--hue-span` | `0.75` | Colour range across the spectrum |
| `--no-reflection` | off | Drop the mirrored reflection under the bars |
| `--peak-fall` | `0.55` | How fast the peak caps drop |
| `--bg-refresh` | `20` | Seconds between wallpaper re-checks; `0` disables |
| `--no-click-through` | off | Stop clicks passing through to the desktop |
| `--windowed` | off | Draw in a normal window instead |
| `--log` | — | Append output to a file (needed under `pythonw`) |

## Requirements

Python 3.14 on Windows 11, plus `numpy`, `soundcard`. The WinRT probe
additionally uses `winrt-Windows.Devices.Lights` (not needed by the service).

```powershell
python -m pip install numpy soundcard
```
