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

GRANULAR_PRESETS = [
    {"id": "granular_1", "grain_ms": 60, "density_hz": 6, "spread_ms": 40},
    {"id": "granular_2", "grain_ms": 90, "density_hz": 10, "spread_ms": 60},
    {"id": "granular_3", "grain_ms": 40, "density_hz": 14, "spread_ms": 30},
    {"id": "granular_4", "grain_ms": 120, "density_hz": 4, "spread_ms": 90},
    {"id": "granular_5", "grain_ms": 70, "density_hz": 8, "spread_ms": 200},
]


class GranularCloudSource:
    """Self-generating grain cloud (spec 16.3.2 'granular memory'): grains a
    slowly-drifting window over a generated wavetable. BPM scales grain
    density (spec 5.5). Pitch is treated as 'relative' not tonal (spec 7's
    pitchBehavior), so grains are read at a fixed rate -- no per-grain
    resampling."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self.seeds = SeedBank(seed=seed, count=6, length=4096)
        self._voices = {}

    def render(self, vid, timbre, bpm, frames, preset):
        voice = self._voices.get(vid)
        if voice is None:
            table = self.seeds.table(int(round(timbre["brightness"] * (len(self.seeds) - 1))))
            voice = {"table": table, "window_pos": 0.0, "next_grain": 0, "grains": []}
            self._voices[vid] = voice
        table = voice["table"]
        n = len(table)
        grain_len = max(32, int(preset["grain_ms"] * 0.001 * self.samplerate))
        density_hz = max(0.5, preset["density_hz"] * (0.5 + bpm / 180.0))
        interval = max(1, int(self.samplerate / density_hz))
        window_speed = preset["spread_ms"] * 0.001 * self.samplerate / max(1, interval)

        out = np.zeros(frames, dtype=np.float64)
        env = np.hanning(grain_len)
        t = 0
        while t < frames:
            if voice["next_grain"] <= 0:
                voice["window_pos"] = (voice["window_pos"] + window_speed) % max(1, n - grain_len)
                voice["grains"].append({"start": int(voice["window_pos"]), "pos": 0})
                voice["next_grain"] = interval
            step = min(frames - t, voice["next_grain"])
            for grain in voice["grains"]:
                write_len = min(step, grain_len - grain["pos"])
                if write_len <= 0:
                    continue
                src = table[grain["start"] + grain["pos"]: grain["start"] + grain["pos"] + write_len]
                out[t:t + write_len] += src * env[grain["pos"]: grain["pos"] + write_len]
                grain["pos"] += write_len
            voice["grains"] = [g for g in voice["grains"] if g["pos"] < grain_len]
            voice["next_grain"] -= step
            t += step
        peak = np.max(np.abs(out))
        if peak > 1.0:
            out /= peak
        return out

    def sync(self, active_ids):
        sync_voices(self._voices, active_ids)
