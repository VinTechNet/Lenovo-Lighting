"""Print the LampArray feature-report field layout straight from the descriptor."""

import hidraw
from probe_lamparray import find_lamparray

LIGHTING_USAGES = {
    0x01: "LampArray", 0x02: "LampArrayAttributesReport", 0x03: "LampCount",
    0x04: "BoundingBoxWidthInMicrometers", 0x05: "BoundingBoxHeightInMicrometers",
    0x06: "BoundingBoxDepthInMicrometers", 0x07: "LampArrayKind",
    0x08: "MinUpdateIntervalInMicroseconds", 0x20: "LampAttributesRequestReport",
    0x21: "LampId", 0x22: "LampAttributesResponseReport",
    0x23: "PositionXInMicrometers", 0x24: "PositionYInMicrometers",
    0x25: "PositionZInMicrometers", 0x26: "LampPurposes",
    0x27: "UpdateLatencyInMicroseconds", 0x28: "RedLevelCount",
    0x29: "GreenLevelCount", 0x2A: "BlueLevelCount", 0x2B: "IntensityLevelCount",
    0x2C: "IsProgrammable", 0x2D: "InputBinding", 0x50: "LampMultiUpdateReport",
    0x51: "RedUpdateChannel", 0x52: "GreenUpdateChannel", 0x53: "BlueUpdateChannel",
    0x54: "IntensityUpdateChannel", 0x55: "LampMultiUpdateFlags",
    0x60: "LampRangeUpdateReport", 0x61: "LampIdStart", 0x62: "LampIdEnd",
    0x70: "LampArrayControlReport", 0x71: "AutonomousMode",
}

info = find_lamparray()
caps = hidraw.value_caps(info["path"])

offsets = {}
for c in caps:
    rid = c["report_id"]
    bit = offsets.get(rid, 8)  # report ID occupies the first byte
    name = LIGHTING_USAGES.get(c["usage_min"], f"0x{c['usage_min']:02X}")
    if c["is_range"]:
        name = (f"{LIGHTING_USAGES.get(c['usage_min'], hex(c['usage_min']))}"
                f"..{LIGHTING_USAGES.get(c['usage_max'], hex(c['usage_max']))}")
    total = c["bit_size"] * c["report_count"]
    print(f"report {rid}  byte {bit // 8:>3}  {c['bit_size']:>2}bit x{c['report_count']:<3} "
          f"logical[{c['logical_min']},{c['logical_max']}]  {name}")
    offsets[rid] = bit + total

print("\nreport sizes (bytes, incl. report id):")
for rid, bits in sorted(offsets.items()):
    print(f"  report {rid}: {bits // 8}")
