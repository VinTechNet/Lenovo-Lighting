"""Multi-update vs range-update, at frame rate, with Lenovo's agent running.

Phase D proved multi-update is steady when we own the device; phase Y proved
range-update wins against Lenovo. The combination multi-update + Lenovo
running was never tested, and that is exactly what the service does.
"""

import time

from lamparray import LampArray

HOLD = 10.0

la = LampArray()
la.set_autonomous(False)
try:
    print("PHASE 1: solid ORANGE via update_lamps (multi-update, 3 batches) "
          "at 60 fps for 10 s", flush=True)
    end = time.time() + HOLD
    while time.time() < end:
        la.update_lamps([(255, 90, 0)] * la.lamp_count)
        time.sleep(1 / 60)

    print("PHASE 2: solid PURPLE via set_all (range-update) at 60 fps for 10 s",
          flush=True)
    end = time.time() + HOLD
    while time.time() < end:
        la.set_all((160, 0, 255))
        time.sleep(1 / 60)

    print("PHASE 3: per-zone GRADIENT via update_lamps at 60 fps for 10 s",
          flush=True)
    n = la.lamp_count
    end = time.time() + HOLD
    while time.time() < end:
        la.update_lamps([(int(255 * i / (n - 1)), 0, int(255 * (1 - i / (n - 1))))
                         for i in range(n)])
        time.sleep(1 / 60)

    print("Done.", flush=True)
    la.set_all((0, 0, 0))
finally:
    la.close()
