"""HID LampArray driver (HID Usage Table 1.4, Lighting And Illumination, page 0x59).

Verified against the Legion 5 15IPH11 keyboard controller (048D:C615, MI_01):
24 RGB zones, 255 levels per channel, 2400 us minimum update interval.

Field order below was taken from the device's own report descriptor via
HidP_GetValueCaps; note that HidP lists fields reversed within each run of
equally-sized fields, so the offsets here are the corrected ones.
"""

import struct
import time

import hidraw

USAGE_PAGE_LIGHTING = 0x59
USAGE_LAMP_ARRAY = 0x01

REPORT_ATTRIBUTES = 1      # 23 bytes, feature, read
REPORT_LAMP_REQUEST = 2    # 3 bytes,  feature, write
REPORT_LAMP_RESPONSE = 3   # 29 bytes, feature, read
REPORT_MULTI_UPDATE = 4    # 51 bytes, feature, write
REPORT_RANGE_UPDATE = 5    # 10 bytes, feature, write
REPORT_CONTROL = 6         # 2 bytes,  feature, write

FLAG_UPDATE_COMPLETE = 0x01
LAMPS_PER_MULTI_UPDATE = 8

KIND_NAMES = {
    1: "Keyboard", 2: "Mouse", 3: "GameController", 4: "Peripheral", 5: "Scene",
    6: "Notification", 7: "Chassis", 8: "Wearable", 9: "Furniture", 10: "Art",
    11: "Headset", 12: "Microphone", 13: "Speaker",
}


class Lamp:
    __slots__ = ("id", "x", "y", "z", "purposes", "latency_us",
                 "red_levels", "green_levels", "blue_levels", "intensity_levels",
                 "is_programmable", "input_binding")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def __repr__(self):
        return (f"Lamp(id={self.id}, pos=({self.x/1000:.1f}mm, "
                f"{self.y/1000:.1f}mm, {self.z/1000:.1f}mm))")


class LampArrayError(RuntimeError):
    pass


def find_devices():
    """All HID LampArray collections present on the system."""
    return [
        d for d in hidraw.enumerate_devices()
        if d["usage_page"] == USAGE_PAGE_LIGHTING and d["usage"] == USAGE_LAMP_ARRAY
    ]


class LampArray:
    """Host-driven control of a HID LampArray device."""

    def __init__(self, path=None):
        if path is None:
            found = find_devices()
            if not found:
                raise LampArrayError(
                    "No HID LampArray device found. If the keyboard normally "
                    "lights up, check that the Lenovo lighting driver is installed."
                )
            path = found[0]["path"]
        self.path = path
        self.dev = hidraw.HidDevice(path)
        self._autonomous = True

        raw = self.dev.get_feature(REPORT_ATTRIBUTES, 23)
        (self.lamp_count, self.width_um, self.height_um, self.depth_um,
         self.kind, self.min_update_interval_us) = struct.unpack_from("<HIIIII", raw, 1)
        if not 0 < self.lamp_count <= 65535:
            raise LampArrayError(f"implausible lamp count {self.lamp_count}")
        self._lamps = None

    # -- metadata ---------------------------------------------------------
    @property
    def kind_name(self):
        return KIND_NAMES.get(self.kind, f"Unknown({self.kind})")

    @property
    def max_fps(self):
        return 1_000_000 / self.min_update_interval_us if self.min_update_interval_us else 1000

    @property
    def lamps(self):
        """Per-lamp attributes, fetched once and cached."""
        if self._lamps is None:
            self._lamps = [self._lamp_attributes(i) for i in range(self.lamp_count)]
        return self._lamps

    def _lamp_attributes(self, lamp_id):
        req = struct.pack("<BH", REPORT_LAMP_REQUEST, lamp_id)
        if not self.dev.set_feature(req):
            raise LampArrayError(f"LampAttributesRequest failed for lamp {lamp_id}")
        r = self.dev.get_feature(REPORT_LAMP_RESPONSE, 29)
        (rid, x, y, z, latency, purposes, red, green, blue,
         intensity, programmable, binding) = struct.unpack_from("<HIIIIIBBBBBB", r, 1)
        return Lamp(
            id=rid, x=x, y=y, z=z, purposes=purposes, latency_us=latency,
            red_levels=red, green_levels=green, blue_levels=blue,
            intensity_levels=intensity, is_programmable=programmable,
            input_binding=binding,
        )

    # -- control ----------------------------------------------------------
    def set_autonomous(self, autonomous: bool):
        """False hands control to this process; True returns it to the firmware."""
        report = struct.pack("<BB", REPORT_CONTROL, 1 if autonomous else 0)
        if not self.dev.set_feature(report):
            raise LampArrayError("LampArrayControl failed (device may be in use)")
        self._autonomous = autonomous

    def update_range(self, start, end, color, complete=True):
        """Set lamps [start, end] inclusive to one RGBI colour."""
        r, g, b, i = _rgbi(color)
        report = struct.pack(
            "<BBHHBBBB",
            REPORT_RANGE_UPDATE,
            FLAG_UPDATE_COMPLETE if complete else 0,
            start, end, r, g, b, i,
        )
        if not self.dev.set_feature(report):
            raise LampArrayError(f"LampRangeUpdate({start},{end}) failed")

    def set_all(self, color):
        self.update_range(0, self.lamp_count - 1, color)

    def update_lamps(self, colors):
        """Set individual lamps.

        `colors` maps lamp id -> colour, or is a sequence of colours indexed
        by lamp id. Sent in batches of 8; only the final batch is flagged
        complete so the whole frame latches at once.
        """
        if isinstance(colors, dict):
            items = sorted(colors.items())
        else:
            items = list(enumerate(colors))
        if not items:
            return

        batches = [
            items[i:i + LAMPS_PER_MULTI_UPDATE]
            for i in range(0, len(items), LAMPS_PER_MULTI_UPDATE)
        ]
        for n, batch in enumerate(batches):
            last = n == len(batches) - 1
            body = bytearray(51)
            body[0] = REPORT_MULTI_UPDATE
            body[1] = len(batch)
            body[2] = FLAG_UPDATE_COMPLETE if last else 0
            for slot, (lamp_id, color) in enumerate(batch):
                struct.pack_into("<H", body, 3 + slot * 2, lamp_id)
                body[19 + slot * 4: 23 + slot * 4] = bytes(_rgbi(color))
            if not self.dev.set_feature(bytes(body)):
                raise LampArrayError("LampMultiUpdate failed")

    # -- lifecycle --------------------------------------------------------
    def close(self, restore=True):
        try:
            if restore and not self._autonomous:
                self.set_all((0, 0, 0))
                self.set_autonomous(True)
        except Exception:
            pass
        finally:
            self.dev.close()

    def __enter__(self):
        self.set_autonomous(False)
        return self

    def __exit__(self, *exc):
        self.close()


def _rgbi(color):
    """Normalise a colour to (r, g, b, intensity), each 0-255."""
    if len(color) == 3:
        r, g, b = color
        i = 255
    elif len(color) == 4:
        r, g, b, i = color
    else:
        raise ValueError(f"colour must be 3 or 4 components, got {len(color)}")
    return (
        max(0, min(255, int(r))),
        max(0, min(255, int(g))),
        max(0, min(255, int(b))),
        max(0, min(255, int(i))),
    )


def describe():
    la = LampArray()
    print(f"{la.kind_name} LampArray: {la.lamp_count} lamps, "
          f"{la.width_um/1000:.0f} x {la.height_um/1000:.0f} mm, "
          f"max {la.max_fps:.0f} fps")
    for lamp in la.lamps:
        print(f"  {lamp} rgb_levels=({lamp.red_levels},{lamp.green_levels},"
              f"{lamp.blue_levels}) programmable={lamp.is_programmable}")
    la.close()


if __name__ == "__main__":
    describe()
