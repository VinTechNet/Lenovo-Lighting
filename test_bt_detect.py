"""Check Bluetooth endpoint detection against every output device."""

import time

import soundcard as sc

import musiclight

start = time.perf_counter()
for spk in sc.all_speakers():
    parent = musiclight._device_parent_id(f"SWD\\MMDEVAPI\\{spk.id}")
    bt = musiclight.endpoint_is_bluetooth(str(spk.id))
    print(f"{'BLUETOOTH' if bt else 'wired    '}  {spk.name}")
    print(f"             parent={parent}")
print(f"\nall {len(sc.all_speakers())} endpoints probed in "
      f"{(time.perf_counter() - start) * 1000:.1f} ms")
