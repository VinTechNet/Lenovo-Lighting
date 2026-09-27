"""Isolate the cause of the flicker.

Each phase holds for 8 s and prints a banner first. Watch the keyboard and
note which phases are steady and which flicker.
"""

import struct
import time

import lamparray
from lamparray import LampArray

HOLD = 8.0


def banner(n, text):
    print(f"\n{'=' * 60}\nPHASE {n}: {text}\n{'=' * 60}", flush=True)


la = LampArray()
la.set_autonomous(False)
try:
    banner("A", "SOLID RED, written once, then untouched for 8 s. "
                "\n  Flicker here = firmware resuming its own effect.")
    la.set_all((255, 0, 0))
    time.sleep(HOLD)

    banner("B", "SOLID GREEN, rewritten 30x/sec via range-update. "
                "\n  Steady here but not in A = we just need continuous refresh.")
    end = time.time() + HOLD
    while time.time() < end:
        la.set_all((0, 255, 0))
        time.sleep(1 / 30)

    banner("C", "SOLID BLUE, re-asserting AutonomousMode=0 every frame, 30x/sec."
                "\n  Steady here but not in B = autonomous mode keeps reverting.")
    end = time.time() + HOLD
    while time.time() < end:
        la.set_autonomous(False)
        la.set_all((0, 0, 255))
        time.sleep(1 / 30)

    banner("D", "SOLID WHITE via multi-update (3 batches of 8), 30x/sec."
                "\n  Flicker here but not in B = the batched multi-update is the problem.")
    end = time.time() + HOLD
    while time.time() < end:
        la.update_lamps([(255, 255, 255)] * la.lamp_count)
        time.sleep(1 / 30)

    banner("E", "SOLID YELLOW via multi-update, every batch flagged COMPLETE."
                "\n  Steady here but not in D = the device latches per report.")
    end = time.time() + HOLD
    while time.time() < end:
        for start in range(0, la.lamp_count, 8):
            body = bytearray(51)
            body[0] = lamparray.REPORT_MULTI_UPDATE
            n = min(8, la.lamp_count - start)
            body[1] = n
            body[2] = lamparray.FLAG_UPDATE_COMPLETE
            for slot in range(n):
                struct.pack_into("<H", body, 3 + slot * 2, start + slot)
                body[19 + slot * 4: 23 + slot * 4] = bytes((255, 200, 0, 255))
            la.dev.set_feature(bytes(body))
        time.sleep(1 / 30)

    print("\nDone - going dark.")
    la.set_all((0, 0, 0))
finally:
    la.close()
