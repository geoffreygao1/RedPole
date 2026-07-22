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

PITCH_PRESETS = [
    {"id": "pitch_1", "semitones": -12.0, "mix": 1.0},                          # sub-octave
    {"id": "pitch_2", "semitones": 12.0, "mix": 0.5},                           # octave shimmer
    {"id": "pitch_3", "semitones": 7.0, "mix": 0.6},                            # fifth / interval generation
    {"id": "pitch_4", "semitones": 0.0, "mix": 1.0, "drift_cents": 25.0},       # pitch drift
    {"id": "pitch_5", "semitones": 0.0, "mix": 1.0},                            # resonator-bank quantization (Phase 1: passthrough placeholder; a later phase can route this through ResonantPulseSource's resonator math)
]


class PitchResonanceTransform:
    """Fractional-resample pitch shift (same technique TapeModulator uses
    for warble) applied within each block (spec 8 row 3). Cross-block
    continuity is a later refinement -- each block reads its own short
    circular buffer, which is audible as a small artifact at very low
    'semitones' shifts but is fine for Phase 1 tuning-by-ear."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._rng = np.random.default_rng(seed)
        self._voices = {}

    def render(self, vid, x, preset):
        voice = self._voices.get(vid)
        if voice is None:
            voice = {"drift_phase": float(self._rng.uniform(0, 2 * np.pi))}
            self._voices[vid] = voice
        frames = len(x)
        semitones = preset["semitones"]
        if preset.get("drift_cents"):
            voice["drift_phase"] += 2.0 * np.pi * 0.1 * frames / self.samplerate
            semitones += preset["drift_cents"] / 100.0 * np.sin(voice["drift_phase"])
        ratio = 2.0 ** (semitones / 12.0)
        idx = np.arange(frames) * ratio
        i0 = np.floor(idx).astype(np.int64) % frames
        i1 = (i0 + 1) % frames
        frac = idx - np.floor(idx)
        shifted = x[i0] * (1.0 - frac) + x[i1] * frac
        return shifted * preset["mix"] + x * (1.0 - preset["mix"])

    def sync(self, active_ids):
        sync_voices(self._voices, active_ids)


GRAINFX_PRESETS = [
    {"id": "grainfx_1", "kind": "granulate", "grain_ms": 30, "scatter": 0.3},
    {"id": "grainfx_2", "kind": "ring_mod", "freq_hz": 180.0, "mix": 0.5},
    {"id": "grainfx_3", "kind": "am", "freq_hz": 6.0, "depth": 0.6},
    {"id": "grainfx_4", "kind": "wavefold", "drive": 2.5},
    {"id": "grainfx_5", "kind": "saturate", "drive": 3.0},
]


class GranularTransform:
    """Granulation + the spec 8 row 4 texture family (ring mod, AM,
    wavefolding, saturation) -- numpy-only waveshaping applied per-block."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._rng = np.random.default_rng(seed)
        self._voices = {}

    def render(self, vid, x, preset):
        voice = self._voices.get(vid)
        if voice is None:
            voice = {"phase": 0.0}
            self._voices[vid] = voice
        frames = len(x)
        kind = preset["kind"]
        t = np.arange(frames, dtype=np.float64) / self.samplerate
        if kind == "granulate":
            grain_len = max(8, int(preset["grain_ms"] * 0.001 * self.samplerate))
            out = x.copy()
            n_grains = frames // grain_len
            for g in range(n_grains):
                if self._rng.random() < preset["scatter"]:
                    start, end = g * grain_len, min(frames, (g + 1) * grain_len)
                    src_offset = int(self._rng.integers(-grain_len, grain_len))
                    src_start = int(np.clip(start + src_offset, 0, frames - (end - start)))
                    out[start:end] = x[src_start:src_start + (end - start)]
            return out
        if kind == "ring_mod":
            carrier = np.sin(2.0 * np.pi * preset["freq_hz"] * t + voice["phase"])
            voice["phase"] = float((voice["phase"] + 2.0 * np.pi * preset["freq_hz"] * frames / self.samplerate) % (2 * np.pi))
            return x * carrier * preset["mix"] + x * (1.0 - preset["mix"])
        if kind == "am":
            lfo = 1.0 - preset["depth"] * 0.5 * (1.0 + np.sin(2.0 * np.pi * preset["freq_hz"] * t + voice["phase"]))
            voice["phase"] = float((voice["phase"] + 2.0 * np.pi * preset["freq_hz"] * frames / self.samplerate) % (2 * np.pi))
            return x * lfo
        if kind == "wavefold":
            y = x * preset["drive"]
            return np.sin(y) - 0.15 * np.sin(3.0 * y)
        if kind == "saturate":
            return np.tanh(x * preset["drive"])
        raise ValueError(f"unknown granular-transform kind {kind!r}")

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
