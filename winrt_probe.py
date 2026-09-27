"""Try driving the keyboard through the supported WinRT LampArray API.

Raw HID fights Windows' lighting stack for the device. Windows.Devices.Lights
is the sanctioned path, so the OS arbitrates instead of overwriting us.
"""

import asyncio
import sys
import time
from array import array as pyarray

from winrt.windows.devices.enumeration import DeviceInformation
from winrt.windows.devices.lights import LampArray
from winrt.windows.ui import Color

import dynamic_lighting


def rgb(r, g, b):
    return Color(a=255, r=r, g=g, b=b)


async def get_array():
    selector = LampArray.get_device_selector()
    devices = await DeviceInformation.find_all_async_aqs_filter(selector)
    if not devices:
        return None, None
    return await LampArray.from_id_async(devices[0].id), devices[0]


async def main():
    array, info = await get_array()
    if array is None:
        print("No LampArray exposed to apps.")
        return 1

    print(f"device        : {info.name}")
    print(f"lamp_count    : {array.lamp_count}")
    print(f"is_connected  : {array.is_connected}")
    print(f"is_enabled    : {array.is_enabled}")
    print(f"is_available  : {array.is_available}   "
          f"(Dynamic Lighting is {'ON' if dynamic_lighting.is_enabled() else 'OFF'})")

    if not array.is_available:
        print("\n  -> Windows is not granting this app control.")
        print("     In Settings > Personalization > Dynamic Lighting this is "
              "governed by\n     'Compatible apps in the foreground always "
              "control lighting' and the\n     'Background light control' app "
              "picker.")

    n = array.lamp_count
    indices = pyarray("i", range(n))
    array.brightness_level = 1.0

    print("\nWriting colours anyway - watch the keyboard.", flush=True)
    for name, color in (("RED", rgb(255, 0, 0)),
                        ("GREEN", rgb(0, 255, 0)),
                        ("BLUE", rgb(0, 0, 255))):
        print(f"  all lamps {name} for 4 s ...", flush=True)
        array.set_color(color)
        time.sleep(4)

    print("  left-to-right BLUE->RED gradient for 6 s ...", flush=True)
    colors = [rgb(int(255 * i / (n - 1)), 0, int(255 * (1 - i / (n - 1))))
              for i in range(n)]
    end = time.time() + 6
    while time.time() < end:
        array.set_colors_for_indices(colors, indices)
        time.sleep(1 / 30)

    print(f"  is_available now: {array.is_available}")
    array.set_color(rgb(0, 0, 0))
    return 0


sys.exit(asyncio.run(main()))
