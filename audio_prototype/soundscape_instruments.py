"""Multisample instrument sources for the clickbath-style soundbath.

Loads the clickbath instrument WAVs (converted from mp3, gitignored under
assets/clickbath/) and plays them as pitched voices with three behaviors:
pluck (sparse triggered notes), pad (sustained loop), and bloom (slow swell).
If the assets are absent (fresh clone / CI), banks load empty and render
silence, so nothing here requires the samples to be present.
"""

from pathlib import Path

import numpy as np

from audio_io import read_mono_audio, resample_linear
from soundscape_harmony import midi_to_hz
from soundscape_voices import sync_voices

DEFAULT_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "clickbath"

# Available register samples per instrument (MIDI note -> file <inst>_<midi>.wav).
INSTRUMENT_MIDIS = {
    "piano": (48, 60, 72, 84),
    "guitar": (48, 60, 72),
    "tapeguitar": (36, 48, 60),
    "tapebell": (48, 60, 72, 84),
    "casio": (48, 60, 72, 84),
    "strings": (48, 60, 72, 84),
    "flute": (60, 72, 84),
    "clarinet": (60, 72, 84),
}

# Behavior row -> the 5 instruments in columns I..V (matches the design grid).
INSTRUMENT_GRID = {
    "pluck": ["piano", "guitar", "tapeguitar", "tapebell", "casio"],
    "pad": ["strings", "flute", "clarinet", "casio", "piano"],
    "bloom": ["strings", "flute", "clarinet", "guitar", "tapebell"],
}

INSTRUMENT_PRESETS = [
    {
        "id": f"{behavior}_{inst}",
        "engine": "instrument",
        "row": behavior,
        "behavior": behavior,
        "instrument": inst,
    }
    for behavior, insts in INSTRUMENT_GRID.items()
    for inst in insts
]


class InstrumentBank:
    def __init__(self, samplerate=44100, assets_dir=None, seed=None, samples=None):
        self.samplerate = samplerate
        self._samples = {}
        if samples is not None:
            self._samples = {k: dict(v) for k, v in samples.items()}
            return
        base = Path(assets_dir) if assets_dir is not None else DEFAULT_ASSETS_DIR
        for inst, midis in INSTRUMENT_MIDIS.items():
            loaded = {}
            for midi in midis:
                path = base / f"{inst}_{midi}.wav"
                if not path.exists():
                    continue
                data, file_rate = read_mono_audio(str(path))
                data = resample_linear(np.asarray(data), file_rate, samplerate)
                arr = np.asarray(data, dtype=np.float64)
                peak = float(np.max(np.abs(arr))) if len(arr) else 0.0
                if peak > 1e-9:
                    arr = arr / peak
                loaded[midi] = arr
            self._samples[inst] = loaded

    def has(self, instrument):
        return bool(self._samples.get(instrument))

    def nearest(self, instrument, midi):
        samples = self._samples.get(instrument)
        if not samples:
            return None
        best = min(samples.keys(), key=lambda k: abs(k - midi))
        return samples[best], best


def _make_loopable(sample, samplerate, xfade_ms=40.0):
    """Fold the tail into the head with a linear crossfade so modulo looping
    has no seam. Returns a shortened buffer safe to read with wraparound."""
    x = np.asarray(sample, dtype=np.float64)
    xf = int(xfade_ms * 0.001 * samplerate)
    if xf < 1 or len(x) <= 2 * xf:
        return x
    head = x[:xf].copy()
    tail = x[-xf:].copy()
    fade = np.linspace(0.0, 1.0, xf)
    x = x.copy()
    x[:xf] = tail * (1.0 - fade) + head * fade
    return x[:-xf]


class InstrumentSource:
    """Pitched multisample voice with three behaviors. `pluck` fires sparse
    one-shot notes on a BPM clock (natural sample decay rings into the wash);
    `pad` loops a seamless copy with a gentle breathing envelope; `bloom` is a
    pad with a slow, deep swell so it appears and recedes."""

    def __init__(self, bank, samplerate, seed=None):
        self.bank = bank
        self.samplerate = samplerate
        self._seed = seed
        self._voices = {}
        self._loop_cache = {}

    def _loopable(self, instrument, src_midi, sample):
        key = (instrument, src_midi)
        buf = self._loop_cache.get(key)
        if buf is None:
            buf = _make_loopable(sample, self.samplerate)
            self._loop_cache[key] = buf
        return buf

    def _voice(self, vid):
        voice = self._voices.get(vid)
        if voice is None:
            seed = None if self._seed is None else self._seed + int(vid) * 97
            voice = {"pos": 0.0, "rng": np.random.default_rng(seed),
                     "next_pulse": 0, "note_pos": None, "lfo": 0.0}
            self._voices[vid] = voice
        return voice

    def render(self, vid, preset, assignment, bpm, frames):
        picked = self.bank.nearest(preset["instrument"], int(round(assignment.midi)))
        if picked is None:
            self._voices.pop(vid, None)
            return np.zeros(frames, dtype=np.float64)
        sample, src_midi = picked
        rate = float(midi_to_hz(assignment.midi) / midi_to_hz(src_midi))
        voice = self._voice(vid)
        if preset["behavior"] == "pluck":
            return self._render_pluck(voice, sample, rate, bpm, frames)
        loop = self._loopable(preset["instrument"], src_midi, sample)
        return self._render_sustained(voice, loop, rate, frames, preset["behavior"])

    def _render_pluck(self, voice, sample, rate, bpm, frames):
        out = np.zeros(frames, dtype=np.float64)
        length = len(sample)
        beats_per_note = 4.0
        pulse = max(1, int(self.samplerate * 60.0 / max(20.0, bpm) * beats_per_note))
        rng = voice["rng"]
        note_pos = voice["note_pos"]
        next_pulse = voice["next_pulse"]
        i = 0
        while i < frames:
            if next_pulse <= 0:
                if rng.uniform() < 0.9:
                    note_pos = 0.0
                next_pulse = pulse
            step = min(frames - i, next_pulse)
            if note_pos is not None:
                idx = note_pos + np.arange(step) * rate
                inb = idx < (length - 1)
                ii = idx[inb]
                i0 = np.floor(ii).astype(np.int64)
                frac = ii - i0
                seg = sample[i0] * (1.0 - frac) + sample[i0 + 1] * frac
                out[i:i + step][inb] += seg
                note_pos = note_pos + step * rate
                if note_pos >= length - 1:
                    note_pos = None
            next_pulse -= step
            i += step
        voice["note_pos"] = note_pos
        voice["next_pulse"] = next_pulse
        return out

    def _render_sustained(self, voice, loop, rate, frames, behavior):
        length = len(loop)
        if length < 2:
            return np.zeros(frames, dtype=np.float64)
        idx = (voice["pos"] + np.arange(frames) * rate) % length
        i0 = np.floor(idx).astype(np.int64)
        frac = idx - i0
        i1 = (i0 + 1) % length
        out = loop[i0] * (1.0 - frac) + loop[i1] * frac
        voice["pos"] = float((voice["pos"] + frames * rate) % length)
        if behavior == "bloom":
            rate_hz, depth, base = 1.0 / 22.0, 0.9, 0.1
        else:  # pad
            rate_hz, depth, base = 1.0 / 9.0, 0.25, 0.65
        t = np.arange(frames) / self.samplerate
        phase = voice["lfo"]
        lfo = 0.5 + 0.5 * np.sin(2.0 * np.pi * rate_hz * t + phase)
        voice["lfo"] = float((phase + 2.0 * np.pi * rate_hz * frames / self.samplerate) % (2.0 * np.pi))
        return out * (base + depth * lfo)

    def sync(self, active_ids):
        sync_voices(self._voices, active_ids)
