"""Check that we can loopback-capture whatever the default output device is playing.

This is the whole point of the project: WASAPI loopback follows the default
render endpoint, so it captures Bluetooth output just as well as the speakers.
"""

import sys
import time

import numpy as np
import soundcard as sc

sc.default_speaker()  # surfaces init errors early

print("Output devices:")
default = sc.default_speaker()
for spk in sc.all_speakers():
    mark = "  <== DEFAULT" if spk.name == default.name else ""
    print(f"  {spk.name}{mark}")

print(f"\nLoopback-capturing '{default.name}' for 6 s ...")
print("(play some music now)\n")

mic = sc.get_microphone(str(default.name), include_loopback=True)
SR = 48000
with mic.recorder(samplerate=SR, channels=2, blocksize=1024) as rec:
    peak_overall = 0.0
    for _ in range(int(6 * SR / 4096)):
        data = rec.record(numframes=4096)
        mono = data.mean(axis=1)
        rms = float(np.sqrt(np.mean(mono ** 2)))
        peak = float(np.max(np.abs(mono)))
        peak_overall = max(peak_overall, peak)
        bar = "#" * int(min(rms * 300, 50))
        print(f"  rms={rms:7.5f} peak={peak:7.5f} |{bar}")

print(f"\nloudest sample seen: {peak_overall:.5f}")
if peak_overall < 1e-5:
    print("SILENT - nothing was playing, or the default device is not the one in use.")
    sys.exit(1)
print("Loopback capture works.")
