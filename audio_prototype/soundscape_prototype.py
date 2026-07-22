"""Runnable Phase 1 proof-of-concept harness (spec section 13, Phase 1):
simulates ~8 patches with color/BPM drawn from the real finger-scan gamut,
connects them across the 25 source x 25 transform preset grid, and plays
the result live so the design can be tuned by ear.

Run from audio_prototype/:
    rtk python soundscape_prototype.py
    rtk python soundscape_prototype.py --duration 60 --patches 12 --seed 3
"""

import argparse
import time

import numpy as np
import sounddevice as sd

from modulation import (
    FINGER_HUE_MAX,
    FINGER_HUE_MIN,
    FINGER_SAT_MAX,
    FINGER_SAT_MIN,
    FINGER_VAL_MAX,
    FINGER_VAL_MIN,
)
from soundscape_engine import SoundscapeEngine
from soundscape_sources import SOURCE_PRESETS
from soundscape_transforms import TRANSFORM_PRESETS

SAMPLERATE = 44100
BLOCKSIZE = 1024


def build_patches(engine, count, rng, bpm_min=55.0, bpm_max=130.0):
    for i in range(count):
        hue = rng.uniform(FINGER_HUE_MIN, FINGER_HUE_MAX)
        sat = rng.uniform(FINGER_SAT_MIN, FINGER_SAT_MAX)
        val = rng.uniform(FINGER_VAL_MIN, FINGER_VAL_MAX)
        bpm = rng.uniform(bpm_min, bpm_max)
        source_preset = SOURCE_PRESETS[i % len(SOURCE_PRESETS)]["id"]
        transform_preset = TRANSFORM_PRESETS[(i * 3) % len(TRANSFORM_PRESETS)]["id"]
        engine.connect_patch(hue, sat, val, bpm, source_preset, transform_preset)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--patches", type=int, default=8)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    engine = SoundscapeEngine(samplerate=SAMPLERATE, seed=args.seed)
    build_patches(engine, args.patches, rng)

    def callback(outdata, frames, time_info, status):
        block = engine.generate_block(frames)
        outdata[:, 0] = block
        outdata[:, 1] = block

    with sd.OutputStream(samplerate=SAMPLERATE, blocksize=BLOCKSIZE, channels=2, callback=callback):
        print(f"Playing {args.patches} simulated patches for {args.duration:.0f}s (seed={args.seed})...")
        time.sleep(args.duration)


if __name__ == "__main__":
    main()
