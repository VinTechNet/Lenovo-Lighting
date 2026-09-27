"""Objective interference probe - no eyeballs needed for the first half.

1. Can we open the LampArray exclusively (locking every other process out)?
2. Does AutonomousMode flip back to 1 behind our back?
"""

import ctypes
import struct
import time

import hidraw
import lamparray
from probe_lamparray import find_lamparray

info = find_lamparray()
path = info["path"]

print("=== exclusive open ===")
h = hidraw._open(path, hidraw.GENERIC_READ | hidraw.GENERIC_WRITE, share=0)
if h == hidraw.INVALID_HANDLE_VALUE:
    err = ctypes.get_last_error()
    print(f"  DENIED (WinError {err}: {ctypes.FormatError(err).strip()})")
    print("  -> another process is holding the device open.")
    exclusive_ok = False
else:
    print("  GRANTED - we can lock every other process out of this device.")
    hidraw.kernel32.CloseHandle(h)
    exclusive_ok = True

print("\n=== AutonomousMode readback ===")
dev = hidraw.HidDevice(path, exclusive=exclusive_ok)
print(f"  opened {'EXCLUSIVELY' if dev.exclusive else 'shared'}")
try:
    try:
        before = dev.get_feature(lamparray.REPORT_CONTROL, 2)
        print(f"  initial AutonomousMode = {before[1]}")
        readable = True
    except OSError as exc:
        print(f"  report 6 not readable ({exc}) - cannot monitor")
        readable = False

    dev.set_feature(struct.pack("<BB", lamparray.REPORT_CONTROL, 0))
    print("  set AutonomousMode = 0; watching for 12 s ...")

    # Hold a solid colour so there is something to fight over.
    flips = 0
    last = 0
    end = time.time() + 12
    while time.time() < end:
        dev.set_feature(struct.pack(
            "<BBHHBBBB", lamparray.REPORT_RANGE_UPDATE,
            lamparray.FLAG_UPDATE_COMPLETE, 0, 23, 0, 255, 60, 255))
        if readable:
            now = dev.get_feature(lamparray.REPORT_CONTROL, 2)[1]
            if now != last:
                print(f"    t={time.time() % 100:6.2f}  AutonomousMode -> {now}")
                flips += 1
                last = now
        time.sleep(1 / 30)
    print(f"  autonomous-mode changes observed: {flips}")
finally:
    dev.close()

print("\nKeyboard should have been solid GREEN for those 12 s.")
