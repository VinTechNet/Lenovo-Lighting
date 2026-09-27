"""Find the real HIDP_VALUE_CAPS stride by scanning the raw returned buffer."""

import ctypes

import hidraw
from probe_lamparray import find_lamparray

info = find_lamparray()
path = info["path"]

handle = hidraw._open(path, 0)
preparsed = hidraw.PHIDP_PREPARSED_DATA()
hidraw.hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed))
caps = hidraw.HIDP_CAPS()
hidraw.hid.HidP_GetCaps(preparsed, ctypes.byref(caps))
n = caps.NumberFeatureValueCaps
print(f"NumberFeatureValueCaps = {n}")
print(f"ctypes sizeof(HIDP_VALUE_CAPS) = {ctypes.sizeof(hidraw.HIDP_VALUE_CAPS)}")

# Over-allocate generously so a larger-than-expected stride can't overflow.
SLOT = 256
buf = ctypes.create_string_buffer(n * SLOT)
length = ctypes.c_ushort(n)
status = hidraw.hid.HidP_GetValueCaps(
    hidraw.HIDP_FEATURE,
    ctypes.cast(buf, ctypes.POINTER(hidraw.HIDP_VALUE_CAPS)),
    ctypes.byref(length),
    preparsed,
)
print(f"status = 0x{status & 0xFFFFFFFF:08X}, length = {length.value}")

raw = buf.raw
# UsagePage 0x0059 little-endian marks the start of each entry.
hits = [i for i in range(0, len(raw) - 1, 2) if raw[i] == 0x59 and raw[i + 1] == 0x00]
print(f"\noffsets with UsagePage=0x0059: {hits[:20]}")
if len(hits) > 1:
    diffs = [b - a for a, b in zip(hits, hits[1:])]
    print(f"deltas: {diffs[:20]}")

print(f"\nfirst 160 bytes:\n{raw[:160].hex(' ')}")
hidraw.hid.HidD_FreePreparsedData(preparsed)
hidraw.kernel32.CloseHandle(handle)
