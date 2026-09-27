"""Visual check that we can actually drive the keyboard zones.

Run it and watch the keyboard: solid red, green, blue, then a single zone
sweeping left to right, then back to the firmware's own lighting.
"""

import time

from lamparray import LampArray

la = LampArray()
print(f"{la.kind_name}: {la.lamp_count} zones, max {la.max_fps:.0f} fps")
print("Taking control (AutonomousMode=0)...")

with la:
    for name, color in (("RED", (255, 0, 0)), ("GREEN", (0, 255, 0)), ("BLUE", (0, 0, 255))):
        print(f"  all zones {name} ...")
        la.set_all(color)
        time.sleep(1.5)

    print("  sweeping one zone left -> right ...")
    for _ in range(2):
        for i in range(la.lamp_count):
            la.update_lamps([(255, 255, 255) if j == i else (0, 0, 0)
                             for j in range(la.lamp_count)])
            time.sleep(0.05)

    print("  fading white ...")
    for level in list(range(0, 256, 8)) + list(range(255, -1, -8)):
        la.set_all((level, level, level))
        time.sleep(0.01)

print("Released back to firmware.")
