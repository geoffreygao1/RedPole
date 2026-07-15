from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 44100
DURATION_SECONDS = 6.0
OUTPUT_PATH = Path(__file__).parent / "assets" / "sample_loop.wav"

# Frequencies chosen so each completes a whole number of cycles over
# DURATION_SECONDS (220*6=1320, 277*6=1662, 330*6=1980), so the waveform
# and envelope both end exactly where they started -- a seamless loop.
_FREQUENCIES = [220.0, 277.0, 330.0]
_WEIGHTS = [0.5, 0.3, 0.2]


def generate_ambient_loop(samplerate=SAMPLE_RATE, duration=DURATION_SECONDS):
    n = int(samplerate * duration)
    t = np.arange(n) / samplerate
    cycle = 2.0 * np.pi * t / duration

    signal = np.zeros(n)
    for freq, weight in zip(_FREQUENCIES, _WEIGHTS):
        signal += weight * np.sin(2.0 * np.pi * freq * t)

    envelope = 0.6 + 0.4 * np.sin(cycle - np.pi / 2)
    signal *= envelope
    signal /= np.max(np.abs(signal))
    signal *= 0.7  # headroom
    return signal.astype(np.float32)


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    loop = generate_ambient_loop()
    sf.write(str(OUTPUT_PATH), loop, SAMPLE_RATE)
    print(f"Wrote {OUTPUT_PATH} ({len(loop) / SAMPLE_RATE:.1f}s @ {SAMPLE_RATE}Hz)")


if __name__ == "__main__":
    main()
