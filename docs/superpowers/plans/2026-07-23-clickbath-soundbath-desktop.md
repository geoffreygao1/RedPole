# Clickbath-Style Soundbath (Desktop Synth) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the desktop Synth tab clickbath's sound — multisampled real instruments (piano/guitar/casio/strings/flute/clarinet/tape bell/tape guitar) with pluck/pad/bloom behaviors, feeding a global reverb+delay wash controlled by two sliders — while keeping the harmonic engine, evolving-mix conductor, live root, and web-app workflow.

**Architecture:** A new `soundscape_instruments.py` (multisample `InstrumentBank` + `InstrumentSource`) plugs into `SourceBank` as a sixth engine; the synth source grid is restructured to rows `(granular, resonant, pluck, pad, bloom)` with instruments in the columns. `resonant` is slowed. A new `soundscape_wash.py` (`SchroederReverb` + feedback delay) is applied to the `SoundscapeEngine` mono mix before the limiter, controlled by thread-safe `set_reverb`/`set_delay` and two tab sliders.

**Tech Stack:** Python 3, NumPy, `soundfile` (libsndfile 1.2.2, decodes mp3), Tkinter, pytest. Flat module layout in `audio_prototype/`.

## Global Constraints

- All work under `audio_prototype/`. Run tests from there: `.venv/Scripts/python.exe -m pytest <path> -v` (Windows) — a `.venv` exists; the interpreter has numpy/soundfile.
- **Tests MUST NOT depend on the real clickbath samples.** `assets/clickbath/*.wav` exist locally but are gitignored and absent on CI/fresh clones. Instrument tests inject synthetic in-memory samples or write tiny temp WAVs.
- NumPy-only DSP (no scipy). Keep the audio path allocation-light.
- Tk widget tests skip when no display (`_tk_root_or_skip` in `tests/test_synth_tab.py`).
- Determinism: seeded RNGs reproducible per `(seed, id)`.
- Prefix shell/git with `rtk`. Conventional Commits. End commit messages with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- MIDI convention C4=60 (matches `_midi_label` and clickbath). Root range is C2–C4 (36–60); tonal voices allocate upward from root.

## Prerequisite (already done — do NOT redo)

The 28 instrument WAVs are already downloaded/converted into gitignored
`audio_prototype/assets/clickbath/` as `<instrument>_<midi>.wav` (e.g.
`piano_60.wav`). `.gitignore` already lists `audio_prototype/assets/clickbath/`.
Instruments and their available MIDI notes:

```
piano:      48 60 72 84
guitar:     48 60 72
tapeguitar: 36 48 60
tapebell:   48 60 72 84
casio:      48 60 72 84
strings:    48 60 72 84
flute:      60 72 84
clarinet:   60 72 84
```

---

### Task 1: `InstrumentBank` — multisample loader (`soundscape_instruments.py`)

**Files:**
- Create: `audio_prototype/soundscape_instruments.py`
- Test: `audio_prototype/tests/test_soundscape_instruments.py`

**Interfaces:**
- Consumes: `audio_io.read_mono_audio`, `audio_io.resample_linear`.
- Produces:
  - Constants `INSTRUMENT_MIDIS: dict[str, tuple[int,...]]`, `INSTRUMENT_GRID: dict[str, list[str]]`, `INSTRUMENT_PRESETS: list[dict]`, `DEFAULT_ASSETS_DIR: Path`.
  - `InstrumentBank(samplerate=44100, assets_dir=None, seed=None, samples=None)`; methods `has(instrument) -> bool`, `nearest(instrument, midi) -> tuple[np.ndarray, int] | None`.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import soundfile as sf

from soundscape_instruments import (
    INSTRUMENT_GRID,
    INSTRUMENT_MIDIS,
    INSTRUMENT_PRESETS,
    InstrumentBank,
)


def test_note_maps_and_presets_are_consistent():
    assert INSTRUMENT_MIDIS["piano"] == (48, 60, 72, 84)
    assert INSTRUMENT_MIDIS["tapeguitar"] == (36, 48, 60)
    # 3 behavior rows x 5 instruments = 15 presets
    assert len(INSTRUMENT_PRESETS) == 15
    rows = {p["behavior"] for p in INSTRUMENT_PRESETS}
    assert rows == {"pluck", "pad", "bloom"}
    for p in INSTRUMENT_PRESETS:
        assert p["engine"] == "instrument"
        assert p["row"] == p["behavior"]
        assert p["instrument"] in INSTRUMENT_MIDIS
    # column order per behavior matches INSTRUMENT_GRID
    for behavior, insts in INSTRUMENT_GRID.items():
        got = [p["instrument"] for p in INSTRUMENT_PRESETS if p["behavior"] == behavior]
        assert got == insts


def test_missing_assets_dir_yields_empty_bank(tmp_path):
    bank = InstrumentBank(samplerate=44100, assets_dir=str(tmp_path))
    assert bank.has("piano") is False
    assert bank.nearest("piano", 60) is None


def test_loads_wavs_and_nearest_picks_closest(tmp_path):
    sr = 44100
    for midi, freq in [(48, 100.0), (72, 400.0)]:
        t = np.arange(sr // 10) / sr
        sf.write(str(tmp_path / f"piano_{midi}.wav"),
                 (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr)
    bank = InstrumentBank(samplerate=sr, assets_dir=str(tmp_path))
    assert bank.has("piano") is True
    sample, src = bank.nearest("piano", 55)     # closer to 48
    assert src == 48
    sample, src = bank.nearest("piano", 66)     # closer to 72
    assert src == 72
    assert float(np.max(np.abs(sample))) <= 1.0 + 1e-6


def test_samples_kwarg_bypasses_disk():
    data = {"flute": {60: np.ones(100, dtype=np.float64)}}
    bank = InstrumentBank(samplerate=44100, samples=data)
    assert bank.has("flute") is True
    sample, src = bank.nearest("flute", 90)
    assert src == 60 and len(sample) == 100
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_soundscape_instruments.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'soundscape_instruments'`

- [ ] **Step 3: Implement the loader**

Create `audio_prototype/soundscape_instruments.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_soundscape_instruments.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_instruments.py audio_prototype/tests/test_soundscape_instruments.py
rtk git commit -m "feat(synth): InstrumentBank multisample loader for clickbath assets"
```

---

### Task 2: `InstrumentSource` — pluck/pad/bloom playback (`soundscape_instruments.py`)

**Files:**
- Modify: `audio_prototype/soundscape_instruments.py` (add `_make_loopable` + `InstrumentSource`)
- Test: `audio_prototype/tests/test_soundscape_instruments.py`

**Interfaces:**
- Consumes: `InstrumentBank` (Task 1), `soundscape_harmony.midi_to_hz`, `soundscape_voices.sync_voices`.
- Produces: `InstrumentSource(bank, samplerate, seed=None)`; `render(vid, preset, assignment, bpm, frames) -> np.ndarray[float64]` (length `frames`); `sync(active_ids)`. `preset` is an `INSTRUMENT_PRESETS` dict; `assignment` needs `.midi`.

- [ ] **Step 1: Write the failing tests**

```python
from types import SimpleNamespace

from soundscape_instruments import InstrumentBank, InstrumentSource


def _sustained_bank():
    # 1 second of a steady tone so pad/bloom have something to loop.
    sr = 44100
    t = np.arange(sr) / sr
    tone = 0.6 * np.sin(2 * np.pi * 220.0 * t)
    return InstrumentBank(samplerate=sr, samples={
        "strings": {60: tone.astype(np.float64)},
        "piano": {60: tone.astype(np.float64)},
    })


def test_pad_is_continuous_and_bounded():
    src = InstrumentSource(_sustained_bank(), samplerate=44100, seed=1)
    preset = {"instrument": "strings", "behavior": "pad"}
    a = SimpleNamespace(midi=60.0)
    total = np.concatenate([src.render(1, preset, a, 90.0, 1024) for _ in range(40)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-6
    assert float(np.sqrt(np.mean(total ** 2))) > 0.02   # audible, not silent


def test_pluck_is_mostly_silent_with_bursts():
    src = InstrumentSource(_sustained_bank(), samplerate=44100, seed=1)
    preset = {"instrument": "piano", "behavior": "pluck"}
    a = SimpleNamespace(midi=60.0)
    total = np.concatenate([src.render(1, preset, a, 90.0, 1024) for _ in range(200)])
    assert np.max(np.abs(total)) <= 1.0 + 1e-6
    frac_silent = float(np.mean(np.abs(total) < 1e-4))
    assert frac_silent > 0.2         # clearly gaps between notes
    assert float(np.sqrt(np.mean(total ** 2))) > 0.005   # but it does sound


def test_playback_rate_tracks_pitch():
    src = InstrumentSource(_sustained_bank(), samplerate=44100, seed=1)
    preset = {"instrument": "strings", "behavior": "pad"}
    lo = src.render(1, preset, SimpleNamespace(midi=48.0), 90.0, 2048)
    src2 = InstrumentSource(_sustained_bank(), samplerate=44100, seed=1)
    hi = src2.render(2, preset, SimpleNamespace(midi=72.0), 90.0, 2048)
    # higher pitch advances the read head faster -> voice pos larger
    assert src2._voices[2]["pos"] > src._voices[1]["pos"]


def test_empty_bank_is_silent_and_state_gcs():
    src = InstrumentSource(InstrumentBank(samplerate=44100, samples={}), 44100, seed=1)
    preset = {"instrument": "strings", "behavior": "pad"}
    out = src.render(1, preset, SimpleNamespace(midi=60.0), 90.0, 512)
    np.testing.assert_allclose(out, np.zeros(512))
    # sustained bank voice is GC'd when it stops being active
    src2 = InstrumentSource(_sustained_bank(), 44100, seed=1)
    src2.render(1, {"instrument": "strings", "behavior": "pad"}, SimpleNamespace(midi=60.0), 90.0, 512)
    src2.sync([2])
    assert 1 not in src2._voices
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_soundscape_instruments.py -k "pad or pluck or rate or empty_bank" -v`
Expected: FAIL (`InstrumentSource` not defined)

- [ ] **Step 3: Implement `_make_loopable` and `InstrumentSource`**

Append to `soundscape_instruments.py` (add `from soundscape_voices import sync_voices` to the imports):

```python
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
                if rng.uniform() < 0.85:
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_soundscape_instruments.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_instruments.py audio_prototype/tests/test_soundscape_instruments.py
rtk git commit -m "feat(synth): InstrumentSource pluck/pad/bloom multisample playback"
```

---

### Task 3: Wire instruments into `SourceBank` + restructure the source grid

**Files:**
- Modify: `audio_prototype/soundscape_sources.py` (add `row` to presets; extend `SOURCE_PRESETS`; add instrument engine to `SourceBank`)
- Modify: `audio_prototype/synth_tab.py` (`SYNTH_SOURCE_ROWS`, group by `row`, instrument column labels)
- Test: `audio_prototype/tests/test_synth_tab.py`, `audio_prototype/tests/test_soundscape_sources.py`

**Interfaces:**
- Consumes: `INSTRUMENT_PRESETS`, `InstrumentBank`, `InstrumentSource` (Tasks 1–2).
- Produces: `SYNTH_SOURCE_ROWS == ("granular","resonant","pluck","pad","bloom")`; `source_preset_id(row,col)` covering all 25 grid cells; `source_col_label(row,col) -> str`; `SourceBank` renders `engine=="instrument"`.

- [ ] **Step 1: Update the grid tests (write them to fail first)**

In `tests/test_synth_tab.py`, replace `test_source_grid_covers_all_25_source_presets` and `test_grid_rows_map_to_declared_engines` with:

```python
def test_source_grid_rows_are_the_soundbath_rows():
    assert SYNTH_SOURCE_ROWS == ("granular", "resonant", "pluck", "pad", "bloom")


def test_source_grid_covers_25_cells_from_declared_rows():
    from soundscape_sources import SOURCE_PRESETS
    ids = {
        source_preset_id(r, c)
        for r in range(SYNTH_GRID_SIZE)
        for c in range(SYNTH_GRID_SIZE)
    }
    assert len(ids) == 25
    by_row = {}
    for p in SOURCE_PRESETS:
        by_row.setdefault(p["row"], []).append(p["id"])
    expected = {pid for row in SYNTH_SOURCE_ROWS for pid in by_row[row]}
    assert ids == expected


def test_instrument_rows_map_to_expected_instruments():
    from soundscape_instruments import INSTRUMENT_GRID
    from synth_tab import source_col_label
    for row_idx, behavior in enumerate(SYNTH_SOURCE_ROWS):
        if behavior in INSTRUMENT_GRID:
            got = [source_col_label(row_idx, c) for c in range(SYNTH_GRID_SIZE)]
            assert got == INSTRUMENT_GRID[behavior]


def test_granular_resonant_rows_use_variant_labels():
    from synth_tab import source_col_label, VARIANT_LABELS
    assert source_col_label(0, 2) == VARIANT_LABELS[2]   # granular
    assert source_col_label(1, 4) == VARIANT_LABELS[4]   # resonant
```

Also update the import line at the top of the file to add `SYNTH_SOURCE_ROWS` (already imported) — no change needed if present.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_synth_tab.py -k "grid or instrument_rows or variant_labels" -v`
Expected: FAIL (rows still the old tuple; `source_col_label` missing)

- [ ] **Step 3: Extend presets + `SourceBank` in `soundscape_sources.py`**

Replace the `SOURCE_PRESETS` builder block (the `for _engine_name, _presets in (...)` loop) with one that tags each preset with a `row` and appends the instrument presets:

```python
SOURCE_PRESETS = []
for _engine_name, _presets in (
    ("additive", ADDITIVE_PRESETS),
    ("granular", GRANULAR_PRESETS),
    ("resonant", RESONANT_PRESETS),
    ("noise", NOISE_PRESETS),
    ("texture", TEXTURE_PRESETS),
):
    for _p in _presets:
        SOURCE_PRESETS.append({**_p, "engine": _engine_name, "row": _engine_name})

from soundscape_instruments import INSTRUMENT_PRESETS, InstrumentBank, InstrumentSource

SOURCE_PRESETS.extend(INSTRUMENT_PRESETS)
```

In `SourceBank.__init__`, after `self.texture = SampleTextureSource(...)` add:

```python
        self.instruments = InstrumentBank(samplerate, seed=seed)
        self.instrument = InstrumentSource(self.instruments, samplerate, seed=seed)
```

In `SourceBank.render`, before the final `raise ValueError`, add:

```python
        if engine == "instrument":
            return self.instrument.render(vid, preset, assignment, bpm, frames)
```

In `SourceBank.sync`, add `self.instrument.sync(active_ids)` alongside the other `.sync` calls.

- [ ] **Step 4: Restructure the grid in `synth_tab.py`**

Change `_grouped` to group by the `"row"` field, update `SYNTH_SOURCE_ROWS`, and add `source_col_label`:

```python
SYNTH_SOURCE_ROWS = ("granular", "resonant", "pluck", "pad", "bloom")
SYNTH_TRANSFORM_ROWS = ("delay", "spectral", "pitch", "grainfx", "spatial")


def _grouped(presets, rows):
    by_row = {}
    for p in presets:
        by_row.setdefault(p.get("row", p["engine"]), []).append(p["id"])
    return [tuple(by_row[row]) for row in rows]
```

(`_TRANSFORM_GRID` still groups transform presets, which have no `"row"` field, so `p.get("row", p["engine"])` falls back to `engine` for them — keep `_TRANSFORM_GRID = _grouped(TRANSFORM_PRESETS, SYNTH_TRANSFORM_ROWS)` as is.)

Add, after `transform_preset_id`:

```python
_INSTRUMENT_LABELS = {p["id"]: p["instrument"] for p in SOURCE_PRESETS if p["engine"] == "instrument"}


def source_col_label(row, col):
    """Column label for the source grid: instrument name on instrument rows,
    generic variant label (I..V) on granular/resonant rows."""
    preset_id = source_preset_id(row, col)
    return _INSTRUMENT_LABELS.get(preset_id, VARIANT_LABELS[col])
```

Note: `VARIANT_LABELS` is defined lower in the file; move the `VARIANT_LABELS = (...)` definition **above** `source_col_label` (i.e. keep it in the geometry-constants block near `SYNTH_CANVAS_W`), or reference it after its definition. Ensure `source_col_label` is defined after `VARIANT_LABELS`.

- [ ] **Step 5: Run grid + sources tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_synth_tab.py tests/test_soundscape_sources.py tests/test_soundscape_engine.py -v`
Expected: PASS. (Engine tests still pass: instrument presets aren't used unless patched; granular/resonant unchanged. If `test_soundscape_sources.py` asserted a preset count that changed, update it to the new count: 25 built-in engine presets + 15 instrument = 40 in `SOURCE_PRESETS`.)

- [ ] **Step 6: Commit**

```bash
rtk git add audio_prototype/soundscape_sources.py audio_prototype/synth_tab.py audio_prototype/tests/test_synth_tab.py audio_prototype/tests/test_soundscape_sources.py
rtk git commit -m "feat(synth): soundbath source grid (granular/resonant/pluck/pad/bloom)"
```

---

### Task 4: Slow the `resonant` source

**Files:**
- Modify: `audio_prototype/soundscape_sources.py` (`ResonantPulseSource`)
- Test: `audio_prototype/tests/test_soundscape_sources.py`

**Interfaces:**
- Produces: `ResonantPulseSource(samplerate, seed=None, pulse_beats=3.0)`; larger `pulse_beats` ⇒ sparser onsets.

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
from types import SimpleNamespace
from soundscape_harmony import HarmonicField, PitchAllocator
from soundscape_sources import ResonantPulseSource


def _res_assignment():
    field = HarmonicField(root_midi=48)
    return PitchAllocator(field).allocate(1, np.random.default_rng(1), 0.1, "foreground")


def _count_onsets(src, frames_total=88200, block=1024, bpm=120.0):
    a = _res_assignment()
    preset = {"id": "resonant_1", "interval_semitones": (0,), "decay": 0.9975, "excite_gain": 0.6}
    prev = 0.0
    onsets = 0
    n = 0
    while n < frames_total:
        out = src.render(1, a, bpm, block, preset)
        # an onset is a sharp jump above a threshold from near-silence
        for v in np.abs(out):
            if v > 0.05 and prev <= 0.05:
                onsets += 1
            prev = v
        n += block
    return onsets


def test_larger_pulse_beats_gives_fewer_onsets():
    fast = ResonantPulseSource(44100, seed=1, pulse_beats=1.0)
    slow = ResonantPulseSource(44100, seed=1, pulse_beats=3.0)
    assert _count_onsets(slow) < _count_onsets(fast)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_soundscape_sources.py::test_larger_pulse_beats_gives_fewer_onsets -v`
Expected: FAIL (`ResonantPulseSource.__init__` has no `pulse_beats`)

- [ ] **Step 3: Implement**

In `ResonantPulseSource.__init__`, add the parameter and store it:

```python
    def __init__(self, samplerate, seed=None, pulse_beats=3.0):
        self.samplerate = samplerate
        self._voices = {}
        self._rng_seed = seed
        self.pulse_beats = float(pulse_beats)
```

In `render`, change the pulse interval to include `pulse_beats`:

```python
        pulse_interval = max(1, int(self.samplerate * 60.0 / max(20.0, bpm) * self.pulse_beats))
```

(`SourceBank` constructs `ResonantPulseSource(samplerate, seed=seed)` — the new default `pulse_beats=3.0` makes it slower automatically; no change needed there.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_soundscape_sources.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_sources.py audio_prototype/tests/test_soundscape_sources.py
rtk git commit -m "feat(soundscape): slow resonant pulses (pulse_beats, default 3)"
```

---

### Task 5: `SoundscapeWash` — global reverb + feedback delay (`soundscape_wash.py`)

**Files:**
- Create: `audio_prototype/soundscape_wash.py`
- Test: `audio_prototype/tests/test_soundscape_wash.py`

**Interfaces:**
- Consumes: `reverb.SchroederReverb`.
- Produces: `SoundscapeWash(samplerate, reverb_amount=0.35, delay_amount=0.2)`; `set_reverb(a)`, `set_delay(a)` (clamped `[0,1]`); `process(mono) -> np.ndarray[float32]`.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np

from soundscape_wash import SoundscapeWash


def test_zero_amounts_pass_dry_through():
    wash = SoundscapeWash(44100, reverb_amount=0.0, delay_amount=0.0)
    x = np.sin(np.linspace(0, 20, 1024)).astype(np.float32)
    np.testing.assert_allclose(wash.process(x), x, atol=1e-6)


def test_reverb_adds_energy_and_tail_rings_out():
    wash = SoundscapeWash(44100, reverb_amount=0.6, delay_amount=0.0)
    impulse = np.zeros(1024, dtype=np.float32)
    impulse[0] = 1.0
    wash.process(impulse)
    tail = np.concatenate([wash.process(np.zeros(1024, dtype=np.float32)) for _ in range(20)])
    assert float(np.max(np.abs(tail))) > 1e-4        # tail keeps ringing on silence


def test_delay_repeats_after_the_delay_time():
    wash = SoundscapeWash(44100, reverb_amount=0.0, delay_amount=1.0)
    impulse = np.zeros(1024, dtype=np.float32)
    impulse[0] = 1.0
    wash.process(impulse)
    later = np.concatenate([wash.process(np.zeros(1024, dtype=np.float32)) for _ in range(120)])
    assert float(np.max(np.abs(later))) > 1e-3        # echo appears later


def test_output_is_bounded_and_finite():
    wash = SoundscapeWash(44100, reverb_amount=1.0, delay_amount=1.0)
    rng = np.random.default_rng(0)
    for _ in range(40):
        out = wash.process((0.5 * rng.standard_normal(1024)).astype(np.float32))
        assert not np.any(np.isnan(out))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_soundscape_wash.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'soundscape_wash'`)

- [ ] **Step 3: Implement**

Create `audio_prototype/soundscape_wash.py`:

```python
"""Global reverb + feedback-delay 'wash' for the soundbath synth output.

Applied to the SoundscapeEngine mono mix before the RMS limiter (whose job
includes taming reverb feedback). The tail keeps ringing on a zero input, so
notes bloom and decay after their voices are removed."""

import numpy as np

from reverb import SchroederReverb


class FeedbackDelay:
    """Single feedback delay line. Delay length >= block size, so a block's
    read indices never overlap its writes and the whole block vectorizes."""

    def __init__(self, samplerate, seconds=2.0, feedback=0.5):
        self.n = max(1, int(seconds * samplerate))
        self.buf = np.zeros(self.n, dtype=np.float64)
        self.pos = 0
        self.feedback = float(np.clip(feedback, 0.0, 0.95))

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        frames = len(x)
        if frames == 0:
            return x
        if frames > self.n:                      # tiny-delay fallback (not used at 2 s)
            out = np.empty(frames)
            buf, pos, n, fb = self.buf, self.pos, self.n, self.feedback
            for i in range(frames):
                d = buf[pos]
                out[i] = d
                buf[pos] = x[i] + d * fb
                pos = (pos + 1) % n
            self.pos = pos
            return out
        ridx = (np.arange(frames) + self.pos) % self.n
        out = self.buf[ridx].copy()
        self.buf[ridx] = x + out * self.feedback
        self.pos = (self.pos + frames) % self.n
        return out


class SoundscapeWash:
    def __init__(self, samplerate, reverb_amount=0.35, delay_amount=0.2):
        self.samplerate = samplerate
        self.reverb = SchroederReverb(samplerate)
        self.reverb.set_space("wash", size=0.9, diffusion=0.7)
        self.reverb.set_feedback(0.9)            # long decay
        self.delay = FeedbackDelay(samplerate, seconds=2.0, feedback=0.5)
        self.reverb_amount = float(np.clip(reverb_amount, 0.0, 1.0))
        self.delay_amount = float(np.clip(delay_amount, 0.0, 1.0))

    def set_reverb(self, amount):
        self.reverb_amount = float(np.clip(amount, 0.0, 1.0))

    def set_delay(self, amount):
        self.delay_amount = float(np.clip(amount, 0.0, 1.0))

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        wet_delay = self.delay.process(x) * self.delay_amount
        wet_reverb = np.asarray(self.reverb.process(x + wet_delay), dtype=np.float64) * self.reverb_amount
        return (x + wet_delay + wet_reverb).astype(np.float32)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_soundscape_wash.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_wash.py audio_prototype/tests/test_soundscape_wash.py
rtk git commit -m "feat(soundscape): SoundscapeWash global reverb+delay bus"
```

---

### Task 6: Integrate the wash into `SoundscapeEngine`

**Files:**
- Modify: `audio_prototype/soundscape_engine.py` (`__init__`, `generate_block`, add `set_reverb`/`set_delay`)
- Test: `audio_prototype/tests/test_soundscape_engine.py`

**Interfaces:**
- Consumes: `SoundscapeWash` (Task 5).
- Produces: `SoundscapeEngine.set_reverb(amount)`, `set_delay(amount)`; `self.wash`. `generate_block` runs the wash on the mono mix (zeros when idle) before the limiter, so a removed voice leaves a decaying tail.

- [ ] **Step 1: Write the failing tests**

```python
def test_reverb_tail_rings_after_voice_removed():
    engine = SoundscapeEngine(samplerate=44100, seed=1, root_midi=48)
    engine.set_reverb(0.8)
    engine.set_delay(0.3)
    pid = engine.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="additive_2")
    for _ in range(40):
        engine.generate_block(1024)
    engine.disconnect_patch(pid)
    tail = np.concatenate([engine.generate_block(1024) for _ in range(20)])
    assert float(np.max(np.abs(tail))) > 1e-4          # not instant silence
    assert not np.any(np.isnan(tail))
    assert float(np.max(np.abs(tail))) <= 1.0 + 1e-3


def test_zero_wash_matches_dry_when_idle():
    engine = SoundscapeEngine(samplerate=44100, seed=1, root_midi=48)
    engine.set_reverb(0.0)
    engine.set_delay(0.0)
    silent = engine.generate_block(1024)
    np.testing.assert_allclose(silent, np.zeros(1024), atol=1e-6)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_soundscape_engine.py -k "reverb_tail or zero_wash" -v`
Expected: FAIL (`set_reverb` missing)

- [ ] **Step 3: Implement**

Add the import near the top of `soundscape_engine.py`:

```python
from soundscape_wash import SoundscapeWash
```

In `__init__`, after `self.conductor = VoiceConductor(...)` (or after `self.limiter = ...`) add:

```python
        self.wash = SoundscapeWash(samplerate)
```

Add methods after `set_root`:

```python
    def set_reverb(self, amount):
        self.wash.set_reverb(amount)

    def set_delay(self, amount):
        self.wash.set_delay(amount)
```

Rewrite the tail of `generate_block` so the wash always runs (mix is zeros when idle) before the limiter. Replace the current `if not patches: return np.zeros(...)` early return and the final `mixed = self.limiter.process(...)` return with this structure — the method becomes:

```python
    def generate_block(self, frames):
        patches = list(self._patches.values())
        active_ids = [p.id for p in patches]
        self.sources.sync(active_ids)
        self.transforms.sync(active_ids)

        glide_k = 1.0 - np.exp(-(frames / self.samplerate) / 0.4)
        self._root_current += glide_k * (self._root_target - self._root_current)
        self.field.root_midi = self._root_current

        conductor_gains = self.conductor.update(active_ids, frames)

        mix = np.zeros(frames, dtype=np.float64)
        if patches:
            density = min(1.0, len(patches) / 20.0)
            voice_gain = self.gain_smoother.update(len(patches))
            for patch in patches:
                if patch.id not in self._assignments:
                    detune_class = "granular" if patch.source_preset.startswith("granular") else "foreground"
                    rng = np.random.default_rng(patch.id)
                    self._assignments[patch.id] = self.allocator.allocate(patch.id, rng, density, detune_class)
                assignment = self._assignments[patch.id]
                assignment.midi = (
                    self._root_current
                    + ROLE_SEMITONES[assignment.harmonic_role]
                    + 12 * assignment.octave
                    + assignment.detune_cents / 100.0
                )
                gain = conductor_gains.get(patch.id, 0.0)
                if gain <= 1e-6:
                    continue
                voice = self.sources.render(
                    patch.id, patch.source_preset, assignment,
                    patch.hue, patch.sat, patch.val, patch.bpm, frames,
                )
                if patch.transform_preset:
                    voice = self.transforms.render(patch.id, patch.transform_preset, voice, patch.bpm)
                mix += voice * gain * voice_gain

        washed = self.wash.process(mix.astype(np.float32))
        mixed = self.limiter.process(washed)
        return soft_clip(mixed).astype(np.float32)
```

(This preserves the Task-3 root re-pitch and conductor gains; it only moves the "no patches" case through the wash so the tail rings. Confirm the existing gliding-root and conductor tests still pass — they do, the math is unchanged.)

- [ ] **Step 4: Run the full engine suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_soundscape_engine.py -v`
Expected: PASS (existing + 2 new). Note `test_no_patches_is_silence` asserts exact zeros with **no** wash configured — with default `reverb_amount=0.35` the idle output would be zeros anyway (mix is zeros → delay(zeros)=0, reverb(zeros)=0 → output zeros). It still passes. If it fails because the reverb emits tiny numerical noise on zeros, update that test to `atol=1e-6`.

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_engine.py audio_prototype/tests/test_soundscape_engine.py
rtk git commit -m "feat(soundscape): run mix through the reverb+delay wash before the limiter"
```

---

### Task 7: `SynthAudioEngine.set_reverb` / `set_delay` (thread-safe)

**Files:**
- Modify: `audio_prototype/synth_audio_engine.py`
- Test: `audio_prototype/tests/test_synth_audio_engine.py`

**Interfaces:**
- Consumes: `SoundscapeEngine.set_reverb`/`set_delay` (Task 6).
- Produces: `SynthAudioEngine.set_reverb(amount)`, `set_delay(amount)` (locked passthroughs).

- [ ] **Step 1: Write the failing test**

```python
def test_set_reverb_and_delay_reach_the_wash():
    eng = SynthAudioEngine(seed=1)
    eng.set_reverb(0.7)
    eng.set_delay(0.4)
    assert abs(eng.engine.wash.reverb_amount - 0.7) < 1e-9
    assert abs(eng.engine.wash.delay_amount - 0.4) < 1e-9
    eng.set_reverb(5.0)                        # clamped
    assert eng.engine.wash.reverb_amount == 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_synth_audio_engine.py::test_set_reverb_and_delay_reach_the_wash -v`
Expected: FAIL (`set_reverb` missing)

- [ ] **Step 3: Implement**

In `synth_audio_engine.py`, in the "sample + tuning" section (near `set_root`), add:

```python
    def set_reverb(self, amount):
        with self._lock:
            self.engine.set_reverb(amount)

    def set_delay(self, amount):
        with self._lock:
            self.engine.set_delay(amount)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_synth_audio_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/synth_audio_engine.py audio_prototype/tests/test_synth_audio_engine.py
rtk git commit -m "feat(synth): thread-safe set_reverb/set_delay on SynthAudioEngine"
```

---

### Task 8: Tab controls — Reverb/Delay sliders, instrument labels, remove Load Sample

**Files:**
- Modify: `audio_prototype/synth_tab.py` (`SynthTab`)
- Test: `audio_prototype/tests/test_synth_tab.py`

**Interfaces:**
- Consumes: `SynthAudioEngine.set_reverb`/`set_delay` (Task 7); `source_col_label` (Task 3); `engine.wash` default amounts.
- Produces: `SynthTab` shows two sliders (`reverb_scale`, `delay_scale`) and instrument column labels; no Load Sample button.

- [ ] **Step 1: Write the failing tests**

```python
def test_reverb_delay_sliders_drive_the_engine():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        tab.reverb_scale.set(0.75)
        tab.delay_scale.set(0.25)
        assert abs(eng.engine.wash.reverb_amount - 0.75) < 1e-6
        assert abs(eng.engine.wash.delay_amount - 0.25) < 1e-6
    finally:
        root.destroy()


def test_no_load_sample_button_text_present():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)

        def texts(widget, acc):
            for child in widget.winfo_children():
                try:
                    acc.append(str(child.cget("text")))
                except Exception:
                    pass
                texts(child, acc)
            return acc

        labels = texts(tab.frame, [])
        assert not any("Load Sample" in t for t in labels)
    finally:
        root.destroy()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_synth_tab.py -k "sliders or load_sample_button" -v`
Expected: FAIL (`reverb_scale` missing / Load Sample button still there)

- [ ] **Step 3: Edit `_build_controls`**

In `SynthTab._build_controls`, **remove** the Load Sample button line:

```python
        ttk.Button(panel, text="Load Sample...", command=self._on_load_sample).pack(
            fill="x", pady=(8, 0)
        )
```

and, immediately before `self._set_pick(PICKER_W // 2, PICKER_H // 2)`, add a wash panel with the two sliders:

```python
        washbox = ttk.LabelFrame(panel, text="Space (reverb + delay)")
        washbox.pack(fill="x", pady=(8, 0))
        ttk.Label(washbox, text="Reverb").grid(row=0, column=0, sticky="w", padx=4)
        self.reverb_scale = ttk.Scale(
            washbox, from_=0.0, to=1.0, orient="horizontal", command=self._on_reverb
        )
        self.reverb_scale.set(self.engine.engine.wash.reverb_amount)
        self.reverb_scale.grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(washbox, text="Delay").grid(row=1, column=0, sticky="w", padx=4)
        self.delay_scale = ttk.Scale(
            washbox, from_=0.0, to=1.0, orient="horizontal", command=self._on_delay
        )
        self.delay_scale.set(self.engine.engine.wash.delay_amount)
        self.delay_scale.grid(row=1, column=1, sticky="ew", padx=4, pady=2)
        washbox.columnconfigure(1, weight=1)
```

Add the callbacks (near `_on_root_slider`), and delete the now-unused `_on_load_sample` method:

```python
    def _on_reverb(self, value):
        self.engine.set_reverb(float(value))

    def _on_delay(self, value):
        self.engine.set_delay(float(value))
```

Note: `self.engine.engine.wash` reads the underlying `SoundscapeEngine`'s wash for the initial slider value; `self.engine.set_reverb/set_delay` is the thread-safe setter. If you prefer not to reach through, initialize the sliders to the same literals as `SoundscapeWash`'s defaults (0.35 reverb, 0.2 delay).

- [ ] **Step 4: Use instrument labels in the source grid draw**

In `_draw_grid`, the source grid must show instrument names on instrument rows. `_draw_grid` is called for both grids; give it an optional label function. Change its signature and the per-cell label:

```python
    def _draw_grid(self, origin, rows, title, col_label=None):
        ox, oy = origin
        c = self.bay
        c.create_text(ox, oy - 22, text=title, anchor="w", fill="#bdbdbd",
                      font=("TkDefaultFont", 9))
        for r, name in enumerate(rows):
            cy = oy + r * SYNTH_CELL + SYNTH_CELL / 2
            c.create_text(ox - 10, cy, text=name, anchor="e", fill="#d5d5d5",
                          font=("TkDefaultFont", 9))
            for col in range(SYNTH_GRID_SIZE):
                x0 = ox + col * SYNTH_CELL
                y0 = oy + r * SYNTH_CELL
                c.create_rectangle(x0, y0, x0 + SYNTH_CELL, y0 + SYNTH_CELL,
                                   outline="#444", fill="#222")
                label = col_label(r, col) if col_label else VARIANT_LABELS[col]
                c.create_text(x0 + 8, y0 + 10, text=label,
                              fill="#808080", font=("TkDefaultFont", 8))
```

and in `_redraw_bay`, pass `source_col_label` for the source grid only:

```python
        self._draw_grid(SYNTH_SOURCE_ORIGIN, SYNTH_SOURCE_ROWS, "generators", col_label=source_col_label)
        self._draw_grid(SYNTH_TRANSFORM_ORIGIN, SYNTH_TRANSFORM_ROWS, "modifiers")
```

- [ ] **Step 5: Run the synth-tab suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_synth_tab.py -v`
Expected: PASS (pure helpers, geometry, grid, workflow, and the 2 new control tests; skipped if no display).

- [ ] **Step 6: Commit**

```bash
rtk git add audio_prototype/synth_tab.py audio_prototype/tests/test_synth_tab.py
rtk git commit -m "feat(synth): Reverb/Delay sliders + instrument grid labels; drop Load Sample"
```

---

### Task 9: Full-suite check, manual smoke, brief update

**Files:**
- Modify: `AGENTS.md` ("Pick up here")

- [ ] **Step 1: Run the entire suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (Tk tests skip without a display). Report pass/skip counts.

- [ ] **Step 2: Manual smoke (by ear)**

Run: `.venv/Scripts/python.exe main.py`
Verify: Synth tab shows granular/resonant + pluck/pad/bloom rows with instrument names in the instrument columns; Send a color, click a source, click e.g. a `pluck` piano jack, press Play → sparse piano notes; add a `pad` strings jack → sustained bed; raise the Reverb and Delay sliders → the notes wash out and ring after removal; slide the root → tonal instruments glide.

- [ ] **Step 3: Update the brief**

Update `AGENTS.md`'s "Pick up here" to record: multisample clickbath instruments (pluck/pad/bloom) in the synth source grid, slowed resonant, global reverb+delay wash with sliders, gitignored `assets/clickbath/`.

- [ ] **Step 4: Commit**

```bash
rtk git add AGENTS.md
rtk git commit -m "docs: record clickbath soundbath (instruments + wash) in brief"
```

---

## Self-Review

**Spec coverage:**
- Assets (download/convert/gitignore, note maps baked) → Prerequisite + Task 1. ✅
- `InstrumentBank`/`InstrumentSource` (multisample, pluck/pad/bloom) → Tasks 1, 2. ✅
- Source grid restructure (granular/resonant/pluck/pad/bloom, instruments in columns) → Task 3. ✅
- Slow resonant → Task 4. ✅
- Global reverb+delay wash + engine integration + thread-safe controls → Tasks 5, 6, 7. ✅
- Reverb/Delay sliders + instrument labels + remove Load Sample → Task 8. ✅
- Tests for all new pure logic; assets not required by tests → every task uses synthetic/in-memory samples. ✅

**Placeholder scan:** No TBD/TODO; every code step is complete.

**Type consistency:** `nearest(instrument, midi) -> (sample, src_midi)|None` used consistently (Tasks 1, 2). `render(vid, preset, assignment, bpm, frames)` matches between `InstrumentSource` (Task 2) and `SourceBank` dispatch (Task 3). `INSTRUMENT_PRESETS` dict fields (`id/engine/row/behavior/instrument`) consistent (Tasks 1, 3). `SoundscapeWash.set_reverb/set_delay`/`process` consistent (Tasks 5–8). `source_col_label(row, col)` consistent (Tasks 3, 8). Grid rows tuple `(granular, resonant, pluck, pad, bloom)` consistent (Tasks 3, 8).
