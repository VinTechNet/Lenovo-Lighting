"""List HID collections, highlighting the ITE keyboard-lighting controller."""

import hidraw

for d in sorted(hidraw.enumerate_devices(), key=lambda x: (x["vid"], x["pid"], x["usage_page"])):
    mark = " <== ITE" if d["vid"] == 0x048D else ""
    print(
        f"{d['vid']:04X}:{d['pid']:04X} "
        f"up=0x{d['usage_page']:04X} u=0x{d['usage']:04X} "
        f"in={d['input_len']:>4} out={d['output_len']:>4} feat={d['feature_len']:>4} "
        f"{d['manufacturer']!r} {d['product']!r}{mark}"
    )
    if d["vid"] == 0x048D:
        print(f"        {d['path']}")
