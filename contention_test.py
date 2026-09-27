"""Do we actually need to suspend Lenovo's lighting agent / Dynamic Lighting?

Run with both of them restored. Only solid colours, which phases A and B
already proved are rock steady when we have the device to ourselves.
"""

import time

from lamparray import LampArray

la = LampArray()
la.set_autonomous(False)
try:
    print("PHASE X: solid MAGENTA, written once, untouched for 10 s", flush=True)
    la.set_all((255, 0, 255))
    time.sleep(10)

    print("PHASE Y: solid CYAN, refreshed 30x/sec for 10 s", flush=True)
    end = time.time() + 10
    while time.time() < end:
        la.set_all((0, 255, 255))
        time.sleep(1 / 30)

    print("Done.", flush=True)
    la.set_all((0, 0, 0))
finally:
    la.close()
