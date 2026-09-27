"""Put the lighting stack back to stock.

Run this if musiclight.py was killed hard (Task Manager, reboot mid-run) and
left Windows Dynamic Lighting or Lenovo's lighting service switched off.
"""

import time

import contention
import dynamic_lighting
import lenovo_service
from lamparray import LampArray, LampArrayError

print("Restoring stock lighting behaviour ...")

recovered = contention.recover()
if recovered:
    print(f"  recovered the settings recorded before the last run: {recovered}")

try:
    la = LampArray()
    la.set_autonomous(True)   # hand the zones back to the firmware
    la.close(restore=False)
    print("  keyboard returned to firmware control")
except LampArrayError as exc:
    print(f"  keyboard: {exc}")

if not lenovo_service.is_running():
    lenovo_service.start()
    time.sleep(1.5)
print(f"  {lenovo_service.SERVICE} running: {lenovo_service.is_running()}")

dynamic_lighting.set_enabled(True)
print(f"  Windows Dynamic Lighting: "
      f"{'ON' if dynamic_lighting.is_enabled() else 'OFF'}")

print("\nIf Legion Space was closed, reopen it from the Start menu.")
