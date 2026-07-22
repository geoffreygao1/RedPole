"""Synth-mode sound source: seed wavetables, a consonant drone pitch-set,
and per-voice rendering into slightly-different-length looping buffers.

Loop mode feeds one shared audio loop into every effect; synth mode gives
each connected jack its own rendered tone. This module owns *what a voice
sounds like*; web_engine owns how voices are summed and effected.
"""

import numpy as np

WAVETABLE_LEN = 2048
DEFAULT_SEED_COUNT = 6


class SeedBank:
    """A small bank of single-cycle wavetables, synthesized once.

    Each seed is spectrally rich: a harmonic series with a seed-specific
    tilt and randomized partial phases. Higher-index seeds keep more upper
    harmonics. Deterministic given `seed`.
    """

    def __init__(self, count=DEFAULT_SEED_COUNT, length=WAVETABLE_LEN, seed=None):
        self.length = int(length)
        rng = np.random.default_rng(seed)
        self.tables = [self._make_table(rng, i, int(count)) for i in range(int(count))]

    def _make_table(self, rng, index, count):
        n = self.length
        phase = 2.0 * np.pi * np.arange(n) / n
        spread = index / max(1, count - 1)
        n_harmonics = 4 + int(round(spread * 20))
        tilt = 1.2 - 0.5 * spread
        table = np.zeros(n, dtype=np.float64)
        for h in range(1, n_harmonics + 1):
            amp = 1.0 / (h ** tilt)
            table += amp * np.sin(h * phase + rng.uniform(0.0, 2.0 * np.pi))
        peak = float(np.max(np.abs(table)))
        if peak > 1e-9:
            table /= peak
        return table

    def table(self, index):
        return self.tables[int(index) % len(self.tables)]

    def __len__(self):
        return len(self.tables)


# Consonant drone pitch-set: just-intonation ratios over a low root, ordered
# so arriving voices fill the drone in with registral spread. Assigned by
# slot/join order, not by color.
DRONE_ROOT_HZ = 55.0
DRONE_RATIOS = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0)


def drone_pitch_hz(order_index):
    """Return the consonant drone pitch for a voice order index."""
    order_index = int(order_index)
    ratio = DRONE_RATIOS[order_index % len(DRONE_RATIOS)]
    octave = order_index // len(DRONE_RATIOS)
    return DRONE_ROOT_HZ * ratio * (2.0 ** octave)


def voice_timbre_from_color(hue, sat, val, seed_count):
    """Map finger-scan color to synth voice timbre in one small pure function."""
    from modulation import hue_to_unit, sat_to_unit, val_to_unit

    seed_count = int(seed_count)
    seed_index = int(min(seed_count - 1, int(hue_to_unit(hue) * seed_count)))
    return {
        "seed_index": max(0, seed_index),
        "spread": sat_to_unit(sat),
        "brightness": val_to_unit(val),
    }
