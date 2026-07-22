"""Transformation engines (spec section 8, 12). Each renders a transform of
an incoming voice signal, keyed by layer id, following the same
create-on-sight/GC lifecycle as the source engines."""

import numpy as np

from soundscape_voices import sync_voices
from spectral_stretch import SpectralSmear

MAX_DELAY_SECONDS = 4.0

DELAY_PRESETS = [
    {"id": "delay_1", "subdivision": 4.0, "feedback": 0.35, "reverse": False},   # slow delay: BPM/4
    {"id": "delay_2", "subdivision": 1.0, "feedback": 0.45, "reverse": False},   # rhythmic delay: BPM
    {"id": "delay_3", "subdivision": 2.0, "feedback": 0.3, "reverse": True},     # reverse delay: BPM/2
    {"id": "delay_4", "subdivision": 0.25, "feedback": 0.6, "reverse": False},   # loop & freeze: short, high fb
    {"id": "delay_5", "subdivision": 8.0, "feedback": 0.5, "reverse": False},    # long, slow-building tap
]


class DelayTransform:
    """BPM-synced feedback delay (spec 8 row 1, 5.5, 10.2 subdivisions)."""

    def __init__(self, samplerate):
        self.samplerate = samplerate
        self._voices = {}

    def render(self, vid, x, bpm, preset):
        buf_len = int(MAX_DELAY_SECONDS * self.samplerate)
        voice = self._voices.get(vid)
        if voice is None:
            voice = {"buf": np.zeros(buf_len, dtype=np.float64), "write": 0}
            self._voices[vid] = voice
        buf = voice["buf"]
        beat_seconds = 60.0 / max(20.0, bpm)
        delay_samples = int(np.clip(beat_seconds * preset["subdivision"] * self.samplerate, 1, buf_len - 1))
        frames = len(x)
        delay_samples = min(delay_samples, max(1, frames // 4))
        out = np.empty(frames, dtype=np.float64)
        write = voice["write"]
        for i in range(frames):
            read_idx = (write - delay_samples) % buf_len
            tap = buf[read_idx]
            out[i] = tap
            buf[write] = x[i] + tap * preset["feedback"]
            write = (write + 1) % buf_len
        voice["write"] = write
        if preset["reverse"]:
            out = out[::-1]
        return out

    def sync(self, active_ids):
        sync_voices(self._voices, active_ids)


SPECTRAL_PRESETS = [
    {"id": "spectral_1", "suspension": 0.1, "smear": 0.0},   # low-pass-ish (mild)
    {"id": "spectral_2", "suspension": 0.2, "smear": 0.1},   # band-pass-ish
    {"id": "spectral_3", "suspension": 0.5, "smear": 0.6},   # spectral blur
    {"id": "spectral_4", "suspension": 0.9, "smear": 0.3},   # spectral freeze
    {"id": "spectral_5", "suspension": 0.4, "smear": 0.0},   # harmonic filtering (magnitude smoothing only)
]


class SpectralTransform:
    """Reuses SpectralSmear (audio_prototype/spectral_stretch.py) -- the
    phase-vocoder already built for synth-mode's master bus -- per voice
    here, since its suspension/smear knobs already cover blur/freeze/
    filtering-adjacent behavior (spec 8 row 2)."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._seed = seed
        self._voices = {}

    def render(self, vid, x, preset):
        voice = self._voices.get(vid)
        if voice is None:
            seed = None if self._seed is None else self._seed + int(vid) * 173
            voice = {"smear": SpectralSmear(self.samplerate, seed=seed)}
            self._voices[vid] = voice
        out = voice["smear"].process(x, suspension=preset["suspension"], smear=preset["smear"])
        return np.asarray(out, dtype=np.float64)

    def sync(self, active_ids):
        sync_voices(self._voices, active_ids)
