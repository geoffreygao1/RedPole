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
