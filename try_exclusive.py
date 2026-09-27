"""One-line answer: can we claim the LampArray exclusively right now?"""

import ctypes

import hidraw
from probe_lamparray import find_lamparray

info = find_lamparray()
h = hidraw._open(info["path"], hidraw.GENERIC_READ | hidraw.GENERIC_WRITE, share=0)
if h == hidraw.INVALID_HANDLE_VALUE:
    print(f"DENIED (still held by another process)")
else:
    hidraw.kernel32.CloseHandle(h)
    print("GRANTED (nothing else holds the device)")
