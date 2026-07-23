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
