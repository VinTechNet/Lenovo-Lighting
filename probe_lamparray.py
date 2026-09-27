"""Read-only probe of the HID LampArray collection (usage page 0x59).

Only issues GET_FEATURE requests plus the LampAttributesRequest write that
the spec defines as the way to page through lamp metadata. Nothing here
changes the lighting state.
"""

import struct
import sys

import hidraw

REPORT_ATTRIBUTES = 1
REPORT_LAMP_REQUEST = 2
REPORT_LAMP_RESPONSE = 3
REPORT_MULTI_UPDATE = 4
REPORT_RANGE_UPDATE = 5
REPORT_CONTROL = 6

KINDS = {
    1: "Keyboard", 2: "Mouse", 3: "GameController", 4: "Peripheral",
    5: "Scene", 6: "Notification", 7: "Chassis", 8: "Wearable",
    9: "Furniture", 10: "Art", 11: "Headset", 12: "Microphone",
    13: "Speaker",
}


def find_lamparray():
    for d in hidraw.enumerate_devices():
        if d["usage_page"] == 0x59 and d["usage"] == 0x01:
            return d
    return None


def main():
    dev_info = find_lamparray()
    if not dev_info:
        print("No LampArray collection found.")
        return 1
    print(f"LampArray: {dev_info['vid']:04X}:{dev_info['pid']:04X} "
          f"feature_len={dev_info['feature_len']}")
    print(f"  {dev_info['path']}\n")

    flen = dev_info["feature_len"]
    with hidraw.HidDevice(dev_info["path"]) as dev:
        raw = dev.get_feature(REPORT_ATTRIBUTES, flen)
        print(f"AttributesReport raw: {raw[:24].hex(' ')}")
        (lamp_count, w, h, depth, kind, min_interval) = struct.unpack_from(
            "<HIIIII", raw, 1
        )
        print(f"  LampCount            : {lamp_count}")
        print(f"  BoundingBox (um)     : {w} x {h} x {depth}")
        print(f"  Kind                 : {kind} ({KINDS.get(kind, '?')})")
        print(f"  MinUpdateInterval    : {min_interval} us "
              f"(max {1_000_000 / min_interval:.0f} fps)" if min_interval
              else "  MinUpdateInterval    : 0")

        print(f"\nPer-lamp attributes (first 8 of {lamp_count}):")
        for lamp_id in range(min(lamp_count, 8)):
            req = bytes([REPORT_LAMP_REQUEST]) + struct.pack("<H", lamp_id)
            dev.set_feature(req.ljust(flen, b"\0"))
            resp = dev.get_feature(REPORT_LAMP_RESPONSE, flen)
            (rid, x, y, z, purposes, red, green, blue, intensity,
             programmable, binding) = struct.unpack_from("<HIIIIBBBBBB", resp, 1)
            print(f"  id={rid:<4} pos=({x:>6},{y:>6},{z:>6}) purpose={purposes} "
                  f"levels=R{red}/G{green}/B{blue}/I{intensity} "
                  f"prog={programmable} key=0x{binding:02X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
