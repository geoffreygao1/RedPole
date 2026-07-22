"""Source engines for the soundscape synthesizer (spec section 7, 12).

Each engine renders one voice's audio for one block, keyed by layer id,
following the create-on-sight / GC-on-disappearance per-voice pattern used
throughout audio_prototype (soundscape_voices.sync_voices).
"""

import numpy as np

from soundscape_harmony import midi_to_hz
from soundscape_voices import sync_voices
from synth_source import SeedBank

ADDITIVE_PRESETS = [
    {"id": "additive_1", "register_bias": -1, "brightness_bias": 0.0, "attack": 6.0},
    {"id": "additive_2", "register_bias": 0, "brightness_bias": 0.15, "attack": 4.0},
    {"id": "additive_3", "register_bias": 0, "brightness_bias": 0.35, "attack": 3.0},
    {"id": "additive_4", "register_bias": 1, "brightness_bias": 0.55, "attack": 2.0},
    {"id": "additive_5", "register_bias": 1, "brightness_bias": 0.8, "attack": 8.0},
]


class AdditiveDroneSource:
    """Sustained additive/wavetable drone at the allocated harmonic pitch.
    Brightness (spec 5.3) selects a brighter SeedBank wavetable; attack
    length varies per preset (spec 16.3.4 slow-attack layers)."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self.seeds = SeedBank(seed=seed)
        self._voices = {}

    def render(self, vid, assignment, timbre, frames, preset):
        voice = self._voices.get(vid)
        if voice is None:
            voice = {"phase": 0.0, "env": 0.0}
            self._voices[vid] = voice
        hz = float(midi_to_hz(assignment.midi))
        brightness = min(1.0, max(0.0, timbre["brightness"] + preset["brightness_bias"]))
        seed_index = int(round(brightness * (len(self.seeds) - 1)))
        table = self.seeds.table(seed_index)
        n = len(table)
        inc = hz * n / self.samplerate
        idx = (voice["phase"] + np.arange(frames) * inc) % n
        i0 = np.floor(idx).astype(np.int64)
        i1 = (i0 + 1) % n
        frac = idx - i0
        signal = table[i0] * (1.0 - frac) + table[i1] * frac
        voice["phase"] = float((voice["phase"] + frames * inc) % n)
        attack_samples = max(1.0, preset["attack"] * self.samplerate)
        voice["env"] = min(1.0, voice["env"] + frames / attack_samples)
        return (signal * voice["env"]).astype(np.float64)

    def sync(self, active_ids):
        sync_voices(self._voices, active_ids)
