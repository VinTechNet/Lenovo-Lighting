"""Dump raw LampAttributesResponse bytes for every lamp, to verify layout."""

import struct

import hidraw
from probe_lamparray import (
    REPORT_LAMP_REQUEST,
    REPORT_LAMP_RESPONSE,
    REPORT_ATTRIBUTES,
    find_lamparray,
)

info = find_lamparray()
flen = info["feature_len"]
with hidraw.HidDevice(info["path"]) as dev:
    count = struct.unpack_from("<H", dev.get_feature(REPORT_ATTRIBUTES, flen), 1)[0]
    print(f"{count} lamps\n")
    for lamp_id in range(count):
        dev.set_feature(
            (bytes([REPORT_LAMP_REQUEST]) + struct.pack("<H", lamp_id)).ljust(flen, b"\0")
        )
        r = dev.get_feature(REPORT_LAMP_RESPONSE, flen)
        rid, x, y, z = struct.unpack_from("<HIII", r, 1)
        print(f"id={rid:<3} x={x/1000:>7.1f}mm y={y/1000:>6.1f}mm z={z/1000:>4.1f}mm "
              f"tail={r[15:26].hex(' ')}")
