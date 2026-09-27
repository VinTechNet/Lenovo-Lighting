# Session notes — resume here

Working notes for picking this project back up. `README.md` is the user-facing
manual; this file is the "what happened and why" so nothing has to be
re-derived.

**Last worked on:** 2026-09-24/25
**Machine:** Lenovo Legion 5 15IPH11 (83RW), Windows 11, Python 3.14.6 at
`C:\Python314`
**Status:** complete and running. All three logon tasks installed and healthy.

---

## 1. What exists

Three things sharing one audio pipeline. All follow the **default Windows
output device**, which is the whole point — Lenovo's own audio effect only
reacts to the internal speakers, so it does nothing over Bluetooth.

| Component | File | Scheduled task |
| --- | --- | --- |
| Keyboard RGB sync (24 zones) | `musiclight.py` | `LenovoKeyboardMusicSync` (admin) |
| Desktop spectrum visualiser | `wallpaper.py` | `DesktopMusicSpectrum` |
| Tray control panel | `control_panel.py` | `MusicVisualiserPanel` (hidden) |

Data flow:

```
WASAPI loopback (soundcard)  ->  RingBuffer  ->  FFT / log bands / AGC
                                                   |
                    +------------------------------+-------------------+
                    v                                                  v
        musiclight effects -> HID LampArray            wallpaper styles -> Tk canvas
```

`settings.json` is the single source of truth for animation style, target
screens and keyboard effect. Both services poll its mtime and **reload live**,
so the control panel never restarts anything. The installers deliberately do
*not* pin style/effect on the command line — otherwise they would override the
panel.

## 2. Resuming in 30 seconds

```powershell
cd C:\Projects\ai\lenovo-light
Get-ScheduledTask -TaskName LenovoKeyboardMusicSync,DesktopMusicSpectrum,MusicVisualiserPanel |
    Select-Object TaskName,State
Get-Content musiclight.log -Tail 10 ; Get-Content wallpaper.log -Tail 10
python control_panel.py            # open the panel directly
```

Both services run under `pythonw`, which **discards output**, so `--log` is
wired into every task. If something misbehaves, the logs are the first stop —
that is how the Bluetooth-detection bug below was caught.

**Careful:** `Start-ScheduledTask` on an already-running task is a silent no-op.
After changing code or arguments you must `Stop-ScheduledTask` *then* start, or
you will keep testing the old process. This cost real time once.

## 3. Hard-won findings — do not re-derive these

### 3.1 Keyboard: three controllers fight, last writer wins

The keyboard only obeys us if **all three** of these are handled at once.
Leaving any one out reverts it to Lenovo's default animation, which looks
exactly like "the code doesn't work":

1. Turn **Windows Dynamic Lighting off**
   (`HKCU\Software\Microsoft\Lighting\AmbientLightingEnabled`)
2. Stop **`LenovoLightingService` + `LenovoLighting.exe`** (Legion Space's
   effect engine)
3. Re-assert **`AutonomousMode = 0` every frame**, not just at startup

This took many rounds to isolate because each variable alone looks like total
failure. `contention.py` does 1 and 2 crash-safely; `musiclight.py` does 3.

### 3.2 Keyboard dead ends

- **Exclusive HID open (`share=0`) is always denied** — Windows holds every HID
  collection open. This is *not* evidence of a lighting competitor. It looked
  like a smoking gun and wasn't.
- **WinRT `Windows.Devices.Lights`** reports `is_available = False`; Windows
  only grants app control to the foreground app. Writes still land but are
  fought over, so it is no better than raw HID. (`winrt_probe.py`)

### 3.3 The keyboard is a standard HID LampArray

Usage page `0x59`, device `048D:C615` interface `MI_01`. 24 zones, 255 levels
per channel, 2400 µs minimum update interval. No vendor protocol reversing was
needed. Descriptor gotchas:

- `HidP_GetValueCaps` lists fields **reversed within each run of equally-sized
  fields** — a naive offset accumulation produces garbage.
- `HIDP_VALUE_CAPS.DataIndexMin/Max` are `USHORT`, not `ULONG`; the struct is
  **72 bytes, not 76**. Wrong size = entries silently drift after the first.
- In `LampMultiUpdateReport`, flag **only the final batch** `UPDATE_COMPLETE`.
  Flagging every batch latches partial frames and visibly flickers.

### 3.4 Windows 11 killed the live-wallpaper trick

The classic approach re-parents a window into Explorer's `WorkerW` so it draws
*behind the desktop icons*. **On this build nothing re-parented is ever
painted** — verified by screenshot in every variant: inside `WorkerW`, inside
`Progman`, as `WS_POPUP`, and converted to `WS_CHILD`
(`probe_layers.py`, `probe_wschild.py`). Z-order was provably correct while
still invisible, which ruled out layering. This is why several live-wallpaper
tools broke on recent builds.

Also note: **on Win11 the wallpaper `WorkerW` is a child of `Progman`**, not a
top-level sibling as on Win10, so the usual `EnumWindows` lookup finds nothing.

**What works instead:** a normal top-level window pinned to `HWND_BOTTOM` with
the desktop sunk below it (`deskwindow.pin_above_wallpaper`). Draws above the
wallpaper, behind every app, never takes focus, out of the taskbar and Alt+Tab,
click-through. The cost is that it covers icons inside its strip — `--band`
trades height against that.

### 3.5 Wallpaper background must be *captured*, not re-rendered

Re-deriving the background from the registry image (`TranscodedWallpaper`)
misaligned badly: fill mode, DPI scaling and **per-monitor wallpapers** all have
to be guessed. Capturing what Explorer actually painted, via `PrintWindow` on
the wallpaper window, is exact by construction. The user runs a **wallpaper
slideshow**, so it is re-checked every `--bg-refresh` seconds (default 20).

Also: a hard-edged dim looks like a rectangle pasted on the desktop. The dim
ramps in over `--fade` percent of the band so it blends.

### 3.6 Tk frame rate is capped by the system timer

`after()` rounds up to the ~15.6 ms tick, so a nominal 30 fps renders at ~21.
Bar count and band size made **no** difference, which is what pointed at the
timer rather than the drawing. `winmm.timeBeginPeriod(1)` fixes it; measured
29.1 fps at 30 and 57.6 at 60. Default is 45.

### 3.7 Bluetooth detection must not shell out

The first version ran `Get-PnpDeviceProperty` via PowerShell. When two copies
started at once it **timed out and silently reported Bluetooth as "wired"**
(delay 0). Replaced with `cfgmgr32` `CM_Locate_DevNodeW` → `CM_Get_Parent` →
`CM_Get_Device_IDW`, checking for a `BTHENUM`/`BTHHFENUM` enumerator: ~23 ms
for all endpoints, no subprocess, no console flash.

Loopback capture taps audio *before* transmission, so over Bluetooth the lights
would run ahead of the sound; `--bluetooth-delay-ms` (180) compensates.

### 3.8 pystray and Tk threading

The tray menu runs on **its own thread and must never touch Tk variables** —
doing so throws `RuntimeError: main thread is not in main loop` and kills the
tray icon at startup. Keep a plain-string mirror (`self.style_name`) for
`checked`, and post actions back through `self.events` for the main thread.

Windows 11 files new tray icons under the `^` overflow by default; that is
expected, not a bug. Drag it onto the taskbar to pin.

## 4. How things were verified

Screenshots, not guesswork — the user explicitly asked for this after several
rounds of ambiguous visual descriptions.

- **Covered windows:** `capture_window.py` uses `PrintWindow` with
  `PW_RENDERFULLCONTENT` to grab a window by HWND even when obscured. Note it
  does **not** render cross-process child windows, which made one early capture
  misleading.
- **Desktop:** `Shell.Application` `MinimizeAll()` → `ImageGrab` →
  `UndoMinimizeAll()`.
- **GUI:** do **not** use synthetic `SendKeys`/clicks. They landed on the wrong
  widgets and silently mutated radio/checkbox state twice. Instead drive
  `notebook.select(i)` from inside Python and capture by HWND.
- The keyboard has no colour readback, so those checks needed the user's eyes.
  Phased tests (hold colour A 8 s, colour B 8 s, …) with one multi-select
  question were far more efficient than one question per trial.

## 5. Known limitations / open ideas

- **Icons covered** by the visualiser strip (click-through, so still usable).
  Only fixable if Microsoft restores behind-icon rendering, or by moving to a
  DirectComposition approach.
- **Keyboard sync suspends Lenovo's lighting service while it runs.** Restored
  on clean exit; `.suspend_state.json` + `--recover-only` handle hard kills,
  since Dynamic Lighting is a registry setting that would otherwise persist off.
- **Stopping via `Stop-ScheduledTask` is a hard kill** — no clean unwind. Run
  `python musiclight.py --recover-only` (or `restore.py`) afterwards.
- `run_hidden.py`-style console flashing: not an issue here, the subprocess that
  could have caused it was removed in 3.7.
- Not in git — `C:\Projects\ai` shows `?? lenovo-light/`. Worth committing.
- Ideas not pursued: per-app/media-aware colour themes, beat-locked animation,
  a spectrum on the Legion's rear light bar (if it exposes one), and an
  `--effect` that mirrors the keyboard hue onto the wallpaper.

## 6. Recovery cheatsheet

```powershell
python restore.py                     # full reset of the lighting stack
python musiclight.py --recover-only   # just restore suspended settings
python enum_hid.py                    # is the LampArray still present?
python musiclight.py --list-devices   # audio endpoints + Bluetooth flags
python test_bt_detect.py              # Bluetooth detection sanity check
python wallpaper.py --windowed        # visualiser in a normal window
Remove-Item settings.json             # back to defaults
```

Uninstall any task: `install_task.ps1 -Uninstall`,
`install_wallpaper_task.ps1 -Uninstall`, `install_panel_task.ps1 -Uninstall`.

## 7. Dependencies

```powershell
python -m pip install numpy soundcard pillow pystray
```

`winrt-*` packages are only used by `winrt_probe.py` (a dead end, kept as
evidence). `hidraw.py` is dependency-free ctypes over the Win32 HID API.
