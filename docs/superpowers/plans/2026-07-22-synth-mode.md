# Synth Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toggleable "synth" mode to the GitHub Pages web app where each connected patch jack generates its own micro-detuned drone tone (instead of effecting one shared loop), and the collective sound evolves into an ambient wash as more voices join.

**Architecture:** A new `SynthVoiceBank` renders one looping tone per connected layer (seed wavetable + consonant drone pitch + per-voice detune + per-voice loop length). `WebEngine.generate_block` branches on `self.mode`: loop mode is byte-for-byte unchanged; synth mode sums the voice drones as the dry signal, routes each voice through its patched effect (the **existing** `MicrocosmProcessor`/`TapeModulator`/`SchroederReverb`, made per-voice via a backward-compatible `source_arrays` argument), and passes the wet sum through a new density-driven `SpectralSmear` (PaulXStretch-style phase-vocoder) plus the existing reverb before the dry/wet mix. Crowd density (existing `crowd.py` spine) drives the smear depth and reverb size, so evolution is emergent, not authored.

**Tech Stack:** Python 3.11 + NumPy (runs identically on the desktop under CPython and in the browser under Pyodide); vanilla JS + AudioWorklet for the web shell; pytest for the DSP.

## Global Constraints

- **Loop mode must not change.** Every existing `tests/test_web_engine.py` test must still pass unmodified. Synth code paths are entered only when `engine.mode == "synth"`.
- **No shipped audio assets.** Seed tones are synthesized in Python at construction — generative and tiny (§6.1 of the spec).
- **Pyodide-safe Python only.** NumPy + stdlib. No file/device I/O in `web_engine.py` or the new modules (they run under Pyodide). No new third-party deps.
- **Determinism.** Every stochastic component takes a `seed` and uses `np.random.default_rng(seed)`; same seed → same output. Follow the existing `self._seed + vid * <prime>` per-voice seeding idiom.
- **Shared source files, no copy.** The web app fetches the *same* `audio_prototype/*.py` files the desktop app and pytest use (`webapp/worker.js` `PYTHON_FILES`). New Python modules must be added to that list.
- **Finger-scan gamut is fixed** (`modulation.py`): hue 0.0–0.085, sat 0.64–0.72, val 0.90–0.98. Reuse `hue_to_unit`/`sat_to_unit`/`val_to_unit`; do not invent new mappings.
- **Run tests from `audio_prototype/`** with its venv active: `rtk python -m pytest tests/<file> -v` (the venv at `audio_prototype/.venv` already has pytest; `conftest.py` puts the module dir on `sys.path`).
- Prefix shell/build/git commands with `rtk` (project convention).
- **Row → engine mapping is significant** and shared with the desktop: `PATCH_ROW_ENGINES = [microloop, granules, glitch, multidelay, tape]`; the tape row's column 4 is the special `reverb` cell (see `main.js:404`).

## Locked Design Decisions

These resolve the spec's open/RISK items (§9, §10) for *this plan*. Each is deliberately isolated so it can be retuned by ear later without structural change.

1. **Synth output mirrors loop-mode structure:** `out = soft_clip(dry_gain*dry + wet_gain*wet)`. In synth mode `dry` = the summed voice drones (so the room is never silent when a voice is connected — satisfies "empty room = one fragile tone"), and `wet` = the per-voice effects → master smear → reverb. This reuses the existing dry/wet mix knob unchanged.
2. **Per-voice source, not shared loop:** the RISK in spec §9 is resolved by adding optional `source_arrays`/`source_positions` to `MicrocosmProcessor.process` (backward compatible — omitted → today's shared-loop behavior). `TapeModulator` needs no signature change; synth mode gives each tape voice its own `TapeModulator` instance reading its own voice buffer.
3. **Spectral stretch is master-bus-only** for this plan (spec §10 lists per-voice/master/both as open). Per-voice stretch is explicitly out of scope here; the `SpectralSmear` class is written so a per-voice instance is possible later.
4. **Color → timbre** lives in ONE pure function, `synth_source.voice_timbre_from_color(...)` (spec §10: "keep the color→parameter mapping in one small, swappable place"). hue → seed selection, sat → stereo-spread scalar, val → brightness scalar.
5. **Pitch is assigned by slot/join order, not color** (spec §6.2): a fixed consonant just-intonation drone set, filled in with registral spread as voices arrive; each voice micro-detuned a few cents (beating) and looped at a slightly different length (phase-drift lattice).
6. **Mono throughout.** The existing pipeline is mono (the worklet copies the one channel to both outputs). The `spread`/stereo-spread timbre value is computed and stored for a future stereo pass but does not split channels in this plan.

## File Structure

**Create:**
- `audio_prototype/synth_source.py` — seed bank, drone pitch-set, color→timbre map, `SynthVoiceBank` (per-voice rendering + lifecycle). Owns everything about *what a voice sounds like*.
- `audio_prototype/spectral_stretch.py` — `SpectralSmear`, the streaming phase-vocoder. Owns the *time-suspension* DSP.
- `audio_prototype/tests/test_synth_source.py`
- `audio_prototype/tests/test_spectral_stretch.py`
- `audio_prototype/tests/test_web_engine_synth.py` — synth-mode engine behavior (keeps loop-mode tests untouched in their own file).

**Modify:**
- `audio_prototype/microcosm_processor.py` — add optional `source_arrays`/`source_positions` to `process` (backward compatible).
- `audio_prototype/web_engine.py` — add `mode`, `set_mode`, and the `_generate_synth_block` branch.
- `audio_prototype/tests/test_microcosm_processor.py` — add per-voice-source tests.
- `webapp/worker.js` — add `set_mode` message; register the two new Python files.
- `webapp/main.js` — mode toggle, patch-bay reset on toggle, hide Load Loop in synth.
- `webapp/index.html` — the toggle control.
- `webapp/style.css` — toggle styling (minimal).
- `RedPole/AGENTS.md` — refresh "Pick up here" at the end.

---

## Task 1: Seed bank (`SeedBank`)

**Files:**
- Create: `audio_prototype/synth_source.py`
- Test: `audio_prototype/tests/test_synth_source.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - Module constants `WAVETABLE_LEN = 2048`, `DEFAULT_SEED_COUNT = 6`.
  - `class SeedBank(count=DEFAULT_SEED_COUNT, length=WAVETABLE_LEN, seed=None)` with `.tables: list[np.ndarray]`, `.length: int`, `.table(index) -> np.ndarray` (wraps `index % len`), `__len__`.
  - Each table: `float64`, shape `(length,)`, peak-normalized to ≤ 1.0, richer (more harmonics) for higher index.

- [ ] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_synth_source.py
import numpy as np

from synth_source import SeedBank, WAVETABLE_LEN, DEFAULT_SEED_COUNT


def test_seed_bank_is_deterministic_and_shaped():
    a = SeedBank(seed=7)
    b = SeedBank(seed=7)
    assert len(a) == DEFAULT_SEED_COUNT
    for i in range(len(a)):
        assert a.table(i).shape == (WAVETABLE_LEN,)
        assert a.table(i).dtype == np.float64
        assert np.max(np.abs(a.table(i))) <= 1.0 + 1e-9
        np.testing.assert_array_equal(a.table(i), b.table(i))


def test_seed_bank_index_wraps():
    bank = SeedBank(seed=1)
    np.testing.assert_array_equal(bank.table(0), bank.table(len(bank)))


def test_higher_seeds_are_brighter():
    # brightness ~ high-frequency energy; compare the top half of the rFFT
    bank = SeedBank(seed=3)

    def hf_ratio(tbl):
        mag = np.abs(np.fft.rfft(tbl))
        return float(np.sum(mag[len(mag) // 2:]) / (np.sum(mag) + 1e-12))

    assert hf_ratio(bank.table(len(bank) - 1)) > hf_ratio(bank.table(0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_synth_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'synth_source'`.

- [ ] **Step 3: Write minimal implementation**

```python
# audio_prototype/synth_source.py
"""Synth-mode sound source: seed wavetables, a consonant drone pitch-set,
and per-voice rendering into slightly-different-length looping buffers.

Loop mode feeds one shared audio loop into every effect; synth mode gives
each connected jack its own rendered tone. This module owns *what a voice
sounds like*; web_engine owns how voices are summed and effected.
"""

import numpy as np

WAVETABLE_LEN = 2048          # single-cycle seed length (samples)
DEFAULT_SEED_COUNT = 6


class SeedBank:
    """A small bank of single-cycle wavetables, synthesized once.

    Each seed is spectrally rich -- a harmonic series with a seed-specific
    tilt and randomized partial phases -- so grain/stretch effects have
    material to work on (a pure sine would give them nothing). Higher-index
    seeds keep more upper harmonics (brighter). Deterministic given `seed`.
    """

    def __init__(self, count=DEFAULT_SEED_COUNT, length=WAVETABLE_LEN, seed=None):
        self.length = int(length)
        rng = np.random.default_rng(seed)
        self.tables = [self._make_table(rng, i, int(count)) for i in range(int(count))]

    def _make_table(self, rng, index, count):
        n = self.length
        phase = 2.0 * np.pi * np.arange(n) / n
        spread = index / max(1, count - 1)              # 0.0 .. 1.0
        n_harmonics = 4 + int(round(spread * 20))       # 4 .. 24
        tilt = 1.2 - 0.5 * spread                        # brighter seeds fall off slower
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_synth_source.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/synth_source.py audio_prototype/tests/test_synth_source.py
rtk git commit -m "feat(synth): add SeedBank of generative wavetables"
```

---

## Task 2: Drone pitch-set and color→timbre map

**Files:**
- Modify: `audio_prototype/synth_source.py`
- Test: `audio_prototype/tests/test_synth_source.py`

**Interfaces:**
- Consumes: `modulation.hue_to_unit/sat_to_unit/val_to_unit` (import inside the function to keep the module import-light).
- Produces:
  - Constants `DRONE_ROOT_HZ = 55.0`, `DRONE_RATIOS = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0)`.
  - `drone_pitch_hz(order_index: int) -> float` — consonant pitch, registral spread by order.
  - `voice_timbre_from_color(hue, sat, val, seed_count) -> dict` with keys `seed_index:int`, `spread:float in [0,1]`, `brightness:float in [0,1]`. **This is the single swappable color→param place (spec §10).**

- [ ] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_synth_source.py
import modulation as mod
from synth_source import (
    DRONE_RATIOS,
    DRONE_ROOT_HZ,
    drone_pitch_hz,
    voice_timbre_from_color,
)


def test_drone_pitches_are_consonant_and_spread_upward():
    p0 = drone_pitch_hz(0)
    assert p0 == DRONE_ROOT_HZ
    # every pitch is the root times a rational-consonant factor (ratio * 2**octave)
    for i in range(24):
        factor = drone_pitch_hz(i) / DRONE_ROOT_HZ
        octave = i // len(DRONE_RATIOS)
        ratio = DRONE_RATIOS[i % len(DRONE_RATIOS)]
        assert abs(factor - ratio * (2.0 ** octave)) < 1e-9
    # higher order indices trend higher in pitch
    assert drone_pitch_hz(12) > drone_pitch_hz(0)


def test_color_maps_to_timbre_in_one_place():
    seed_count = 6
    dark = voice_timbre_from_color(mod.FINGER_HUE_MIN, mod.FINGER_SAT_MIN,
                                   mod.FINGER_VAL_MIN, seed_count)
    bright = voice_timbre_from_color(mod.FINGER_HUE_MAX, mod.FINGER_SAT_MAX,
                                     mod.FINGER_VAL_MAX, seed_count)
    assert 0 <= dark["seed_index"] < seed_count
    assert 0 <= bright["seed_index"] < seed_count
    assert bright["seed_index"] >= dark["seed_index"]   # hue max -> higher seed
    assert bright["brightness"] > dark["brightness"]    # val max -> brighter
    assert 0.0 <= dark["spread"] <= 1.0
    assert 0.0 <= bright["spread"] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_synth_source.py -v`
Expected: FAIL — `ImportError: cannot import name 'drone_pitch_hz'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to audio_prototype/synth_source.py (below SeedBank)

# Consonant drone pitch-set: just-intonation ratios over a low root, ordered
# so arriving voices fill the drone in with registral spread. Assigned by
# slot/join order -- NOT by color (spec 6.2).
DRONE_ROOT_HZ = 55.0                                  # A1
DRONE_RATIOS = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0)


def drone_pitch_hz(order_index):
    """Pitch for the `order_index`-th voice: a consonant ratio of the root,
    stepped up an octave each time the ratio table wraps."""
    order_index = int(order_index)
    ratio = DRONE_RATIOS[order_index % len(DRONE_RATIOS)]
    octave = order_index // len(DRONE_RATIOS)
    return DRONE_ROOT_HZ * ratio * (2.0 ** octave)


def voice_timbre_from_color(hue, sat, val, seed_count):
    """The ONE swappable place mapping finger-scan color -> voice timbre.

    hue -> which seed (wavetable), sat -> stereo-spread scalar (stored for a
    future stereo pass), val -> brightness scalar. Kept tiny and pure so it
    can be re-pointed at touch pitch after listening (spec 10).
    """
    from modulation import hue_to_unit, sat_to_unit, val_to_unit

    seed_index = int(min(int(seed_count) - 1, int(hue_to_unit(hue) * int(seed_count))))
    return {
        "seed_index": max(0, seed_index),
        "spread": sat_to_unit(sat),
        "brightness": val_to_unit(val),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_synth_source.py -v`
Expected: PASS (5 tests total).

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/synth_source.py audio_prototype/tests/test_synth_source.py
rtk git commit -m "feat(synth): add consonant drone pitch-set and color->timbre map"
```

---

## Task 3: Per-voice rendering (`SynthVoiceBank`)

**Files:**
- Modify: `audio_prototype/synth_source.py`
- Test: `audio_prototype/tests/test_synth_source.py`

**Interfaces:**
- Consumes: `SeedBank`, `drone_pitch_hz`, `voice_timbre_from_color` (Tasks 1–2).
- Produces:
  - Constants `VOICE_LOOP_SECONDS = 4.0`, `LOOP_LENGTH_JITTER = 0.06`, `MAX_DETUNE_CENTS = 8.0`.
  - `_loop_crossfade(buf, fade) -> np.ndarray` (module helper, removes the loop-seam click).
  - `class SynthVoiceBank(samplerate, seed=None, seed_bank=None)` with:
    - `block(layers, frames) -> dict[int, np.ndarray]` — returns `{layer_id: float64 block of shape (frames,)}`, creates voices for new ids, tears down vanished ids, advances each voice's read position. **This is the method `web_engine` calls each block.**
    - `buffer_for(vid) -> np.ndarray | None` — the voice's full looping buffer (for grain-reading effects).
    - `read_pos(vid) -> float` — current read position (post-advance).
    - `reset() -> None` — drop all voices.
  - A layer dict here has at least `id, hue, sat, val, bpm, engine`; if connected it also has `patch_row, patch_col` (see `layers.connect_source`). `_order_index` uses `patch_row*5 + patch_col` when present, else `id-1`.

- [ ] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_synth_source.py
from synth_source import SynthVoiceBank, MAX_DETUNE_CENTS


def _layer(layer_id, hue=0.03, sat=0.68, val=0.94, bpm=90.0, engine="granules",
           row=1, col=0):
    return {"id": layer_id, "hue": hue, "sat": sat, "val": val, "bpm": bpm,
            "engine": engine, "patch_row": row, "patch_col": col}


def test_voice_block_shape_and_lifecycle():
    bank = SynthVoiceBank(44100, seed=5)
    layers = [_layer(1, row=1, col=0), _layer(2, row=1, col=1)]
    blocks = bank.block(layers, 512)
    assert set(blocks) == {1, 2}
    for b in blocks.values():
        assert b.shape == (512,)
        assert b.dtype == np.float64
        assert np.max(np.abs(b)) <= 1.0 + 1e-6
    # dropping a layer tears its voice down
    bank.block([_layer(1)], 512)
    assert bank.buffer_for(2) is None
    assert bank.buffer_for(1) is not None


def test_voice_is_a_sustained_tone_not_silence():
    bank = SynthVoiceBank(44100, seed=5)
    total = np.concatenate([bank.block([_layer(1)], 1024)[1] for _ in range(40)])
    assert float(np.sqrt(np.mean(total ** 2))) > 0.05      # audible, sustained


def test_voices_are_detuned_from_each_other():
    # two voices at the SAME drone slot but different ids must not be identical
    bank = SynthVoiceBank(44100, seed=5)
    b1 = bank.buffer_for
    bank.block([_layer(1, row=1, col=0), _layer(2, row=1, col=0)], 256)
    v1, v2 = bank.buffer_for(1), bank.buffer_for(2)
    # different loop lengths (phase-drift) and/or detune => not equal
    assert v1.shape != v2.shape or not np.allclose(v1[:256], v2[:256])


def test_read_position_advances_and_wraps():
    bank = SynthVoiceBank(44100, seed=5)
    bank.block([_layer(1)], 1000)
    p1 = bank.read_pos(1)
    bank.block([_layer(1)], 1000)
    p2 = bank.read_pos(1)
    n = len(bank.buffer_for(1))
    assert p2 == (p1 + 1000) % n


def test_reset_clears_voices():
    bank = SynthVoiceBank(44100, seed=5)
    bank.block([_layer(1)], 256)
    bank.reset()
    assert bank.buffer_for(1) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_synth_source.py -v`
Expected: FAIL — `ImportError: cannot import name 'SynthVoiceBank'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to audio_prototype/synth_source.py (below voice_timbre_from_color)

VOICE_LOOP_SECONDS = 4.0        # nominal per-voice loop length
LOOP_LENGTH_JITTER = 0.06       # +/- fraction of loop length -> phase-drift lattice
MAX_DETUNE_CENTS = 8.0          # micro-detune spread -> beating between voices


def _loop_crossfade(buf, fade):
    """Crossfade the loop seam so the wrap from buf[-1] to buf[0] is click-free."""
    fade = int(fade)
    if fade <= 0 or len(buf) < 2 * fade:
        return buf
    ramp = np.linspace(0.0, 1.0, fade)
    head = buf[:fade].copy()
    tail = buf[-fade:].copy()
    buf = buf.copy()
    buf[:fade] = head * ramp + tail * (1.0 - ramp)
    return buf[:len(buf) - fade]


class SynthVoiceBank:
    """Owns one rendered voice per connected layer id.

    A voice is created on first sight of a layer id and torn down when the id
    disappears (mirrors MicrocosmProcessor's per-id lifecycle). Each voice
    renders its seed at a micro-detuned drone pitch into a looping buffer whose
    length is jittered per voice -> beating (detune) + a phase-drift lattice
    (loop-length spread), the two emergent mechanisms from spec section 4.
    """

    def __init__(self, samplerate, seed=None, seed_bank=None):
        self.samplerate = samplerate
        self._seed = seed
        self.seeds = seed_bank if seed_bank is not None else SeedBank(seed=seed)
        self._voices = {}     # layer_id -> voice dict

    def _order_index(self, layer):
        if "patch_row" in layer and "patch_col" in layer:
            return int(layer["patch_row"]) * 5 + int(layer["patch_col"])
        return int(layer["id"]) - 1

    def _voice_key(self, layer):
        # rebuild the voice if any timbre/pitch input changed
        return (layer["hue"], layer["sat"], layer["val"], self._order_index(layer))

    def _make_voice(self, layer):
        vid = int(layer["id"])
        rng = np.random.default_rng(None if self._seed is None else self._seed + vid * 101)
        order = self._order_index(layer)
        cents = rng.uniform(-MAX_DETUNE_CENTS, MAX_DETUNE_CENTS)
        pitch_hz = drone_pitch_hz(order) * (2.0 ** (cents / 1200.0))
        jitter = 1.0 + rng.uniform(-LOOP_LENGTH_JITTER, LOOP_LENGTH_JITTER)
        loop_len = max(self.seeds.length * 4,
                       int(VOICE_LOOP_SECONDS * self.samplerate * jitter))
        timbre = voice_timbre_from_color(layer["hue"], layer["sat"], layer["val"],
                                         len(self.seeds))
        buffer = self._render(self.seeds.table(timbre["seed_index"]), pitch_hz, loop_len)
        return {
            "buffer": buffer,
            "pos": 0.0,
            "pitch_hz": pitch_hz,
            "timbre": timbre,
            "key": self._voice_key(layer),
        }

    def _render(self, table, pitch_hz, loop_len):
        inc = pitch_hz * self.seeds.length / self.samplerate   # wavetable steps/sample
        idx = (np.arange(loop_len) * inc) % self.seeds.length
        i0 = np.floor(idx).astype(np.int64)
        i1 = (i0 + 1) % self.seeds.length
        frac = idx - i0
        buf = table[i0] * (1.0 - frac) + table[i1] * frac
        return _loop_crossfade(buf.astype(np.float64), fade=min(256, loop_len // 8))

    def block(self, layers, frames):
        active = set()
        out = {}
        for layer in layers:
            vid = int(layer["id"])
            active.add(vid)
            voice = self._voices.get(vid)
            if voice is None or voice["key"] != self._voice_key(layer):
                voice = self._make_voice(layer)
                self._voices[vid] = voice
            out[vid] = self._read_block(voice, frames)
        self._voices = {k: v for k, v in self._voices.items() if k in active}
        return out

    def _read_block(self, voice, frames):
        buf = voice["buffer"]
        n = len(buf)
        idx = (voice["pos"] + np.arange(frames)) % n
        block = buf[idx.astype(np.int64)]
        voice["pos"] = float((voice["pos"] + frames) % n)
        return block.astype(np.float64)

    def buffer_for(self, vid):
        v = self._voices.get(int(vid))
        return None if v is None else v["buffer"]

    def read_pos(self, vid):
        v = self._voices.get(int(vid))
        return 0.0 if v is None else v["pos"]

    def reset(self):
        self._voices = {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_synth_source.py -v`
Expected: PASS (10 tests total).

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/synth_source.py audio_prototype/tests/test_synth_source.py
rtk git commit -m "feat(synth): render per-voice detuned drone loops in SynthVoiceBank"
```

---

## Task 4: Spectral smear (`SpectralSmear`)

**Files:**
- Create: `audio_prototype/spectral_stretch.py`
- Test: `audio_prototype/tests/test_spectral_stretch.py`

**Interfaces:**
- Consumes: NumPy only.
- Produces:
  - Constants `FFT_SIZE = 2048`, `HOP = FFT_SIZE // 4`, `WINDOW_NORM = (FFT_SIZE / HOP) * 0.5` (= 2.0).
  - `class SpectralSmear(samplerate, seed=None)` with `process(x, suspension=0.0, smear=0.0) -> np.float32` returning exactly `len(x)` samples. `suspension` (0..1) slows magnitude updates (longer smear); `smear` (0..1) scales phase randomization. With `suspension=0, smear=0` it is a near-identity passthrough after `FFT_SIZE` samples of priming latency (sqrt-Hann analysis+synthesis at 75% overlap is COLA).

- [ ] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_spectral_stretch.py
import numpy as np

from spectral_stretch import SpectralSmear, FFT_SIZE, HOP

SR = 44100


def _sine(freq, n, sr=SR):
    return (0.5 * np.sin(2 * np.pi * freq * np.arange(n) / sr)).astype(np.float64)


def test_process_returns_same_length_each_block():
    smear = SpectralSmear(SR, seed=1)
    for _ in range(20):
        out = smear.process(_sine(220.0, 512))
        assert out.shape == (512,)
        assert out.dtype == np.float32


def test_identity_passthrough_when_no_suspension_or_smear():
    # feed a steady sine; after priming, output should track the input
    # (delayed), since sqrt-Hann @ 75% overlap reconstructs unity gain and
    # phase is untouched at smear=0.
    smear = SpectralSmear(SR, seed=1)
    x = _sine(220.0, FFT_SIZE * 8)
    out = np.concatenate(
        [smear.process(x[i:i + 512], suspension=0.0, smear=0.0)
         for i in range(0, len(x), 512)]
    )
    # compare steady-state region, allowing for the FFT_SIZE priming latency
    a = out[FFT_SIZE * 2:FFT_SIZE * 6].astype(np.float64)
    b = x[FFT_SIZE * 2 - FFT_SIZE:FFT_SIZE * 6 - FFT_SIZE]   # shift by latency
    corr = np.corrcoef(a, b)[0, 1]
    assert corr > 0.95


def test_smear_randomizes_phase_but_bounds_energy():
    smear = SpectralSmear(SR, seed=1)
    x = _sine(220.0, FFT_SIZE * 8)
    out = np.concatenate(
        [smear.process(x[i:i + 512], suspension=0.8, smear=1.0)
         for i in range(0, len(x), 512)]
    )
    steady = out[FFT_SIZE * 2:]
    assert np.max(np.abs(steady)) < 2.0            # bounded, no runaway
    assert float(np.sqrt(np.mean(steady ** 2))) > 0.01   # not silence
    assert not np.any(np.isnan(out))


def test_deterministic_given_seed():
    a = SpectralSmear(SR, seed=9)
    b = SpectralSmear(SR, seed=9)
    x = _sine(330.0, 4096)
    oa = a.process(x, suspension=0.5, smear=1.0)
    ob = b.process(x, suspension=0.5, smear=1.0)
    np.testing.assert_array_equal(oa, ob)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_spectral_stretch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spectral_stretch'`.

- [ ] **Step 3: Write minimal implementation**

```python
# audio_prototype/spectral_stretch.py
"""PaulXStretch-style spectral smear for synth mode (spec section 8).

A streaming phase-vocoder: it keeps each STFT frame's magnitudes but
randomizes their phases, turning short loops and transients into a suspended
wash. Two density-driven knobs:
  - suspension (0..1): how slowly magnitudes update -> longer smear.
  - smear      (0..1): how much phase is randomized -> wider wash.

Fixed config: sqrt-Hann analysis+synthesis windows at 75% overlap
(hop = FFT_SIZE // 4). Applying sqrt-Hann twice = Hann, whose 75%-overlap sum
is the constant WINDOW_NORM, so overlap-add reconstructs unity gain after
dividing by it. With suspension=0 and smear=0 the block is a near-identity
passthrough, delayed by ~FFT_SIZE samples of priming latency.
"""

import numpy as np

FFT_SIZE = 2048
HOP = FFT_SIZE // 4
WINDOW_NORM = (FFT_SIZE / HOP) * 0.5      # = 2.0, the COLA sum for Hann @ 75%


class SpectralSmear:
    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._rng = np.random.default_rng(seed)
        self._window = np.sqrt(np.clip(np.hanning(FFT_SIZE), 0.0, None))
        self._in = np.zeros(0, dtype=np.float64)          # input accumulator
        self._out = np.zeros(FFT_SIZE, dtype=np.float64)  # OLA accumulator
        self._tail = np.zeros(0, dtype=np.float64)        # finished output queue
        self._prev_mag = None

    def process(self, x, suspension=0.0, smear=0.0):
        x = np.asarray(x, dtype=np.float64)
        self._in = np.concatenate([self._in, x])
        suspension = float(np.clip(suspension, 0.0, 1.0))
        smear = float(np.clip(smear, 0.0, 1.0))
        mag_alpha = 0.95 * suspension                     # 0 = instant .. 0.95 = slow

        while len(self._in) >= FFT_SIZE:
            frame = self._in[:FFT_SIZE] * self._window
            spec = np.fft.rfft(frame)
            mag = np.abs(spec)
            if self._prev_mag is None or len(self._prev_mag) != len(mag):
                self._prev_mag = mag
            mag = mag_alpha * self._prev_mag + (1.0 - mag_alpha) * mag
            self._prev_mag = mag
            phase = np.angle(spec) + smear * self._rng.uniform(
                -np.pi, np.pi, size=len(spec)
            )
            frame_out = np.fft.irfft(mag * np.exp(1j * phase), n=FFT_SIZE)
            frame_out *= self._window / WINDOW_NORM
            self._out += frame_out
            self._tail = np.concatenate([self._tail, self._out[:HOP].copy()])
            self._out = np.concatenate([self._out[HOP:], np.zeros(HOP)])
            self._in = self._in[HOP:]

        n = len(x)
        if len(self._tail) < n:
            out = np.zeros(n, dtype=np.float64)
            out[:len(self._tail)] = self._tail
            self._tail = np.zeros(0, dtype=np.float64)
            return out.astype(np.float32)
        out = self._tail[:n]
        self._tail = self._tail[n:]
        return out.astype(np.float32)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_spectral_stretch.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/spectral_stretch.py audio_prototype/tests/test_spectral_stretch.py
rtk git commit -m "feat(synth): add PaulXStretch-style SpectralSmear phase-vocoder"
```

---

## Task 5: Per-voice source in `MicrocosmProcessor`

**Files:**
- Modify: `audio_prototype/microcosm_processor.py:127-199` (the `process` method)
- Test: `audio_prototype/tests/test_microcosm_processor.py`

**Interfaces:**
- Consumes: existing `MicrocosmProcessor`.
- Produces: new optional keyword args on `process`:
  `process(self, loop_array, frames, layers, source_pos=0, source_arrays=None, source_positions=None)`.
  - `source_arrays: dict[int, np.ndarray] | None` — per-`layer_id` source buffer. When a layer's id is present (and non-None), that layer's events read from *its* buffer instead of `loop_array`.
  - `source_positions: dict[int, float] | None` — per-`layer_id` read position; falls back to `source_pos`.
  - Omitting both → **identical** to today's behavior (shared `loop_array`, shared `source_pos`). This is what makes loop mode untouched.

- [ ] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_microcosm_processor.py
def test_per_voice_source_arrays_are_used_when_provided():
    # Two voices with DISTINCT source buffers must produce distinct output,
    # proving each read its own buffer (not the shared loop_array).
    frames = 1024
    a = _tone(220.0, seconds=2.0)
    b = _tone(660.0, seconds=2.0)
    layers = [_layer(1, engine="granules"), _layer(2, engine="granules")]

    proc = MicrocosmProcessor(SR, seed=1)
    per_voice = np.concatenate([
        proc.process(
            np.zeros(0), frames, layers,
            source_arrays={1: a, 2: b},
            source_positions={1: n * frames, 2: n * frames},
        )
        for n in range(60)
    ])
    assert float(np.sqrt(np.mean(per_voice ** 2))) > 0.005
    assert not np.any(np.isnan(per_voice))


def test_omitting_source_arrays_matches_legacy_shared_loop():
    frames = 1024
    loop = _tone(220.0, seconds=2.0) + 0.25 * _tone(440.0, seconds=2.0)
    layers = [_layer(1, engine="granules")]

    legacy = MicrocosmProcessor(SR, seed=7)
    updated = MicrocosmProcessor(SR, seed=7)
    for n in range(40):
        out_legacy = legacy.process(loop, frames, layers, source_pos=n * frames)
        out_updated = updated.process(
            loop, frames, layers, source_pos=n * frames,
            source_arrays=None, source_positions=None,
        )
        np.testing.assert_array_equal(out_legacy, out_updated)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_microcosm_processor.py -k per_voice -v`
Expected: FAIL — `TypeError: process() got an unexpected keyword argument 'source_arrays'`.

- [ ] **Step 3: Write minimal implementation**

Replace the head of `process` (currently `microcosm_processor.py:127-138`) and the `_emit_event` call site.

Change the signature and top guard:

```python
    def process(self, loop_array, frames, layers, source_pos=0,
                source_arrays=None, source_positions=None):
        if not layers:
            self._voices = {}
            return np.zeros(frames, dtype=np.float32)

        loop = np.asarray(loop_array)
        if len(loop) == 0 and not source_arrays:
            self._voices = {}
            return np.zeros(frames, dtype=np.float32)

        out = np.zeros(frames, dtype=np.float64)
        active = set()
        density_probability = min(1.0, EVENT_DENSITY_TARGET / max(1, len(layers)))
        max_events = event_cap_for_frames(frames)
        events_this_block = 0
```

Inside the `for layer in layers:` loop, after `vid = layer["id"]` and the voice/controls setup, resolve the per-voice source just before the event loop. Replace the existing `t = voice["until_event"]` / `while t < frames:` block (lines ~174-190) with:

```python
            if source_arrays is not None and source_arrays.get(vid) is not None:
                layer_loop = np.asarray(source_arrays[vid])
                layer_source_pos = int(
                    (source_positions or {}).get(vid, source_pos)
                )
            else:
                layer_loop = loop
                layer_source_pos = source_pos

            t = voice["until_event"]
            while t < frames:
                if (
                    events_this_block < max_events
                    and voice["rng"].random() < density_probability
                ):
                    self._emit_event(
                        voice,
                        layer_loop,
                        family,
                        t,
                        int(layer_source_pos + t),
                        controls,
                    )
                    events_this_block += 1
                t += self._next_interval(voice, controls)
            voice["until_event"] = t - frames
```

Everything below (`buffer = voice["buffer"]` onward) is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk python -m pytest tests/test_microcosm_processor.py -v`
Expected: PASS — all existing microcosm tests **plus** the two new ones (the legacy-parity test guards that loop mode is byte-identical).

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/microcosm_processor.py audio_prototype/tests/test_microcosm_processor.py
rtk git commit -m "feat(synth): let MicrocosmProcessor read per-voice source buffers"
```

---

## Task 6: `WebEngine.mode` and `set_mode` reset

**Files:**
- Modify: `audio_prototype/web_engine.py:51-64` (`__init__`) and add `set_mode`.
- Create: `audio_prototype/tests/test_web_engine_synth.py`

**Interfaces:**
- Consumes: `SynthVoiceBank` (Task 3), `SpectralSmear` (Task 4).
- Produces:
  - `WebEngine.__init__` stores `self._seed = seed`, `self.mode = "loop"`, `self.synth = SynthVoiceBank(samplerate, seed=seed)`, `self.spectral_smear = SpectralSmear(samplerate, seed=seed)`, `self.synth_tape = {}`.
  - `WebEngine.set_mode(mode: str) -> None` — validates `mode in ("loop", "synth")`, sets `self.mode`, and resets all per-session state: fresh `LayerRegistry`, fresh `MicrocosmProcessor`, fresh `EntryGestureTracker`, fresh `SpectralSmear`, `self.synth.reset()`, `self.synth_tape = {}`. (Audio-buffer flush is handled JS-side in Task 9.)

- [ ] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_web_engine_synth.py
import numpy as np
import pytest

from web_engine import WebEngine

SR = 44100


def test_engine_defaults_to_loop_mode():
    engine = WebEngine(samplerate=SR, seed=1)
    assert engine.mode == "loop"


def test_set_mode_rejects_unknown():
    engine = WebEngine(samplerate=SR, seed=1)
    with pytest.raises(ValueError):
        engine.set_mode("bogus")


def test_set_mode_resets_sources_and_state():
    engine = WebEngine(samplerate=SR, seed=1)
    sid = engine.registry.add_source(hue=0.03, sat=0.68, val=0.94, bpm=90)
    engine.registry.connect_source(sid, engine="granules", row=1, col=0)
    assert engine.registry.snapshot()          # non-empty
    engine.set_mode("synth")
    assert engine.mode == "synth"
    assert engine.registry.snapshot() == []    # patch bay reset on switch
    assert engine.synth_tape == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_web_engine_synth.py -v`
Expected: FAIL — `AttributeError: 'WebEngine' object has no attribute 'mode'`.

- [ ] **Step 3: Write minimal implementation**

Add imports near the top of `web_engine.py` (after the existing imports, line 18):

```python
from spectral_stretch import SpectralSmear
from synth_source import SynthVoiceBank
```

In `__init__`, store the seed and add the synth members. Change line 51-64 so it keeps everything it has and adds:

```python
    def __init__(self, samplerate=DEFAULT_SAMPLE_RATE, seed=None):
        self.samplerate = samplerate
        self._seed = seed
        self.mode = "loop"
        self.registry = LayerRegistry()
        self.modulator = TapeModulator(samplerate=samplerate, seed=seed)
        self.microcosm = MicrocosmProcessor(samplerate, seed=seed)
        self.reverb = SchroederReverb(samplerate)
        self.wet_bus = WetBusManager(samplerate)
        self.entry_gestures = EntryGestureTracker(samplerate)
        self.wet_limiter = RmsLimiter(target_rms=0.35)
        self.reverb_mix = 0.975
        self.wet_dry = 0.5
        self._rv_feedback = REVERB_DEFAULT_FEEDBACK
        self._rv_cutoff = REVERB_DEFAULT_CUTOFF
        self.loop_array = None
        # synth-mode state
        self.synth = SynthVoiceBank(samplerate, seed=seed)
        self.spectral_smear = SpectralSmear(samplerate, seed=seed)
        self.synth_tape = {}     # layer_id -> per-voice TapeModulator
```

Add the method (place it right after `__init__`, before `load_loop`):

```python
    def set_mode(self, mode):
        """Switch between 'loop' and 'synth'. The two modes mean different
        things by a 'source', so switching resets the patch bay and all
        per-session DSP state (spec section 5). The audio-buffer flush is
        issued by the worker on the JS side."""
        if mode not in ("loop", "synth"):
            raise ValueError(f"Unknown mode {mode!r}; expected 'loop' or 'synth'")
        self.mode = mode
        self.registry = LayerRegistry()
        self.microcosm = MicrocosmProcessor(self.samplerate, seed=self._seed)
        self.entry_gestures = EntryGestureTracker(self.samplerate)
        self.spectral_smear = SpectralSmear(self.samplerate, seed=self._seed)
        self.synth.reset()
        self.synth_tape = {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk python -m pytest tests/test_web_engine_synth.py tests/test_web_engine.py -v`
Expected: PASS — new mode tests pass **and** all existing loop-mode `test_web_engine.py` tests still pass (constructor change is additive).

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/web_engine.py audio_prototype/tests/test_web_engine_synth.py
rtk git commit -m "feat(synth): add mode field and set_mode reset to WebEngine"
```

---

## Task 7: Synth dry signal — summed voice drones

**Files:**
- Modify: `audio_prototype/web_engine.py` — add `_generate_synth_block` and branch `generate_block`.
- Test: `audio_prototype/tests/test_web_engine_synth.py`

**Interfaces:**
- Consumes: `self.synth.block(...)` (Task 3), `CrowdState`, `EntryGestureTracker`, `val_to_unit`, `soft_clip`.
- Produces:
  - `WebEngine.generate_block(frames)` now returns `self._generate_synth_block(frames)` when `self.mode == "synth"` (and does **not** require a loaded loop in synth mode). Loop mode path is unchanged.
  - `WebEngine._generate_synth_block(frames)` — **this task builds only the dry (voice-drone) portion**; wet is added in Tasks 8–9. Returns `soft_clip(dry_gain * dry).astype(np.float32)` for now. No layers → returns zeros (shape `(frames,)`, dtype float32).

- [ ] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_web_engine_synth.py
def _connect(engine, sid_hue=0.03, sat=0.68, val=0.94, bpm=90, engine_name="granules",
             row=1, col=0):
    sid = engine.registry.add_source(hue=sid_hue, sat=sat, val=val, bpm=bpm)
    engine.registry.connect_source(sid, engine=engine_name, row=row, col=col)
    return sid


def test_synth_mode_needs_no_loop_and_is_silent_with_no_voices():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    block = engine.generate_block(1024)          # no load_loop, must not raise
    assert block.shape == (1024,)
    assert block.dtype == np.float32
    np.testing.assert_allclose(block, np.zeros(1024), atol=1e-7)


def test_synth_voice_produces_audible_dry_tone():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    engine.wet_dry = 0.0                          # dry only, isolates this task
    _connect(engine)
    total = np.concatenate([engine.generate_block(2048) for _ in range(40)])
    assert float(np.sqrt(np.mean(total ** 2))) > 0.02
    assert np.max(np.abs(total)) <= 1.0
    assert not np.any(np.isnan(total))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_web_engine_synth.py -k "synth_mode_needs_no_loop or audible_dry" -v`
Expected: FAIL — the no-loop test raises `RuntimeError("No loop loaded...")` because `generate_block` doesn't branch yet.

- [ ] **Step 3: Write minimal implementation**

Branch `generate_block` at its top (before the `if self.loop_array is None:` guard, line 73-75):

```python
    def generate_block(self, frames):
        if self.mode == "synth":
            return self._generate_synth_block(frames)
        if self.loop_array is None:
            raise RuntimeError("No loop loaded; call load_loop() first")
        # ... existing loop-mode body unchanged ...
```

Add the new method (place it after `generate_block`):

```python
    def _generate_synth_block(self, frames):
        layers = self.registry.snapshot()
        if not layers:
            # keep the smear primed on silence so its tail settles gracefully
            self.spectral_smear.process(np.zeros(frames, dtype=np.float32))
            return np.zeros(frames, dtype=np.float32)

        crowd = CrowdState.from_layers(layers)
        entry = self.entry_gestures.process(layers, frames, crowd.density)
        voice_blocks = self.synth.block(layers, frames)

        # DRY: sum of the voice drones, gained by val + a brief entry swell,
        # normalized by sqrt(count) so a full room does not clip.
        dry = np.zeros(frames, dtype=np.float64)
        for layer in layers:
            gain = 0.25 + 0.5 * val_to_unit(layer["val"])
            gain *= 1.0 + entry.engine_gain(layer["engine"])
            dry += voice_blocks[layer["id"]] * gain
        dry /= max(1.0, np.sqrt(len(layers)))

        mix = float(np.clip(self.wet_dry, 0.0, 1.0))
        dry_gain = min(1.0, 2.0 * (1.0 - mix))
        return soft_clip(dry_gain * dry).astype(np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk python -m pytest tests/test_web_engine_synth.py tests/test_web_engine.py -v`
Expected: PASS (new dry tests + all loop-mode tests unchanged).

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/web_engine.py audio_prototype/tests/test_web_engine_synth.py
rtk git commit -m "feat(synth): sum per-voice drones as the synth dry signal"
```

---

## Task 8: Synth wet — micro-family voices through per-voice effects

**Files:**
- Modify: `audio_prototype/web_engine.py` — extend `_generate_synth_block`.
- Test: `audio_prototype/tests/test_web_engine_synth.py`

**Interfaces:**
- Consumes: `self.microcosm.process(..., source_arrays=..., source_positions=...)` (Task 5), `self.synth.buffer_for/read_pos` (Task 3), `MICRO_FAMILIES` (already defined `web_engine.py:25`).
- Produces: `_generate_synth_block` now also computes a `wet` signal from micro-family (`microloop/granules/glitch/multidelay`) voices, each read from its own voice buffer, and mixes it: `out = soft_clip(dry_gain*dry + wet_gain*wet)`. Tape/reverb rows are wired in Task 9.

- [ ] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_web_engine_synth.py
def test_synth_micro_voice_adds_wet_distinct_from_dry():
    wet_engine = WebEngine(samplerate=SR, seed=1)
    wet_engine.set_mode("synth")
    wet_engine.wet_dry = 1.0                      # wet only
    _connect(wet_engine, engine_name="granules", row=1, col=0)

    dry_engine = WebEngine(samplerate=SR, seed=1)
    dry_engine.set_mode("synth")
    dry_engine.wet_dry = 0.0                      # dry only
    _connect(dry_engine, engine_name="granules", row=1, col=0)

    wet_blocks, dry_blocks = [], []
    for _ in range(40):
        w = wet_engine.generate_block(1024)
        d = dry_engine.generate_block(1024)
        wet_blocks.append(w)
        dry_blocks.append(d)
        assert not np.any(np.isnan(w))
        assert np.max(np.abs(w)) <= 1.0
    # wet path must audibly differ from the pure-dry path
    assert any(not np.allclose(w, d, atol=1e-6)
               for w, d in zip(wet_blocks, dry_blocks))


def test_two_micro_voices_are_bounded():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    _connect(engine, engine_name="granules", row=1, col=0)
    _connect(engine, engine_name="glitch", row=2, col=2)
    for _ in range(60):
        block = engine.generate_block(2048)
        assert np.max(np.abs(block)) <= 1.0
        assert not np.any(np.isnan(block))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_web_engine_synth.py -k "micro_voice_adds_wet" -v`
Expected: FAIL — with wet not yet wired, `wet_dry=1.0` makes `dry_gain=0`, so the wet-only output is all zeros and never differs from the dry-only path → the `any(...)` assertion fails.

- [ ] **Step 3: Write minimal implementation**

Extend `_generate_synth_block`: after computing `dry` and before the mix, add the wet computation and change the return.

```python
        # WET: route each micro-family voice through the microcosm processor,
        # reading its OWN voice buffer (per-voice source_arrays).
        micro_layers = [l for l in layers if l["engine"] in MICRO_FAMILIES]
        source_arrays = {vid: self.synth.buffer_for(vid) for vid in voice_blocks}
        source_positions = {vid: self.synth.read_pos(vid) for vid in voice_blocks}

        wet = np.zeros(frames, dtype=np.float64)
        if micro_layers:
            wet += self.microcosm.process(
                np.zeros(0, dtype=np.float32), frames, micro_layers,
                source_arrays=source_arrays, source_positions=source_positions,
            )

        mix = float(np.clip(self.wet_dry, 0.0, 1.0))
        dry_gain = min(1.0, 2.0 * (1.0 - mix))
        wet_gain = min(1.0, 2.0 * mix)
        return soft_clip(dry_gain * dry + wet_gain * wet).astype(np.float32)
```

Remove the old `dry`-only return statement added in Task 7 (the `mix`/`dry_gain`/`return soft_clip(dry_gain * dry)...` three lines) — this block replaces it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk python -m pytest tests/test_web_engine_synth.py tests/test_web_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/web_engine.py audio_prototype/tests/test_web_engine_synth.py
rtk git commit -m "feat(synth): route micro-family voices through per-voice microcosm"
```

---

## Task 9: Synth wet — tape/shape voices + master smear + reverb (density spine)

**Files:**
- Modify: `audio_prototype/web_engine.py` — add `_synth_tape_block`, finish the master bus in `_generate_synth_block`.
- Test: `audio_prototype/tests/test_web_engine_synth.py`

**Interfaces:**
- Consumes: `TapeModulator`, `tape_column_controls`, `combine_layers` (already imported `web_engine.py:14-17`), `self.spectral_smear.process(...)` (Task 4), `self.wet_bus`, `self.reverb`, `self.wet_limiter`.
- Produces:
  - `WebEngine._synth_tape_block(tape_layers, frames, entry) -> np.ndarray(float64)` — one `TapeModulator` per tape-row voice (kept in `self.synth_tape`, created lazily, torn down when the voice vanishes), each processing its own voice buffer.
  - `_generate_synth_block` final form: `wet` (micro + tape) → `wet_bus` → `SpectralSmear` (suspension/smear from `crowd.density`) → `SchroederReverb` (size/feedback from `crowd.density`, "wash" style) → `wet_limiter`, then the dry/wet mix. Reverb-row voices count toward density/reverb size (they add their drone to the dry sum via Task 7 but no separate wet signal — matching loop-mode reverb semantics).

- [ ] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_web_engine_synth.py
def test_shape_row_voice_is_a_tape_toned_drone():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    engine.wet_dry = 1.0
    # tape row index 4 (PATCH_ROW_ENGINES), non-reverb column
    _connect(engine, engine_name="tape", row=4, col=0)
    total = np.concatenate([engine.generate_block(2048) for _ in range(50)])
    assert float(np.sqrt(np.mean(total ** 2))) > 0.01
    assert np.max(np.abs(total)) <= 1.0
    assert not np.any(np.isnan(total))


def test_density_deepens_the_smear_and_reverb():
    # more voices -> higher crowd.density -> longer smear window + bigger room.
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    for i in range(6):
        _connect(engine, engine_name="granules", row=1, col=i % 5)
    for _ in range(20):
        engine.generate_block(2048)
    assert engine.reverb.space_style == "wash"
    assert engine.reverb.space_size > 0.35        # grew past the idle default
    assert not np.any(np.isnan(engine.generate_block(2048)))


def test_full_room_output_stays_bounded():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    engines = ("granules", "glitch", "multidelay", "microloop", "tape")
    for i in range(20):
        _connect(engine, engine_name=engines[i % 5],
                 row=i % 5, col=i % 5, bpm=60 + 4 * i)
    for _ in range(60):
        block = engine.generate_block(2048)
        assert np.max(np.abs(block)) <= 1.0
        assert not np.any(np.isnan(block))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_web_engine_synth.py -k "shape_row or density_deepens" -v`
Expected: FAIL — `shape_row` output is silent (tape not wired), and `reverb.space_style` is still `"bright_room"` (master reverb not driven in synth).

- [ ] **Step 3: Write minimal implementation**

Add the tape helper method:

```python
    def _synth_tape_block(self, tape_layers, frames, entry):
        if not tape_layers:
            self.synth_tape = {}
            return np.zeros(frames, dtype=np.float64)
        active = set()
        out = np.zeros(frames, dtype=np.float64)
        for layer in tape_layers:
            vid = layer["id"]
            active.add(vid)
            mod = self.synth_tape.get(vid)
            if mod is None:
                seed = None if self._seed is None else self._seed + vid * 53
                mod = TapeModulator(samplerate=self.samplerate, seed=seed)
                self.synth_tape[vid] = mod
            buf = self.synth.buffer_for(vid)
            if buf is None or len(buf) == 0:
                continue
            combined = combine_layers([layer])
            controls = tape_column_controls([layer])
            block = mod.process(
                buf, frames,
                combined["warble_depth"],
                combined["bloom_depth"] * (1.0 + entry.engine_gain("tape")),
                combined["rate_hz"],
                hue=layer["hue"], sat=layer["sat"], val=layer["val"],
                tape_controls=controls,
            )
            out += np.asarray(block, dtype=np.float64)
        self.synth_tape = {k: v for k, v in self.synth_tape.items() if k in active}
        return out
```

Replace the `wet` / mix tail of `_generate_synth_block` (added in Task 8) with the full master bus:

```python
        # WET: micro-family voices (per-voice microcosm) + tape/shape voices.
        micro_layers = [l for l in layers if l["engine"] in MICRO_FAMILIES]
        tape_layers = [l for l in layers if l["engine"] == "tape"]
        reverb_layers = [l for l in layers if l["engine"] == "reverb"]
        source_arrays = {vid: self.synth.buffer_for(vid) for vid in voice_blocks}
        source_positions = {vid: self.synth.read_pos(vid) for vid in voice_blocks}

        wet = np.zeros(frames, dtype=np.float64)
        if micro_layers:
            wet += self.microcosm.process(
                np.zeros(0, dtype=np.float32), frames, micro_layers,
                source_arrays=source_arrays, source_positions=source_positions,
            )
        wet += self._synth_tape_block(tape_layers, frames, entry)

        n_wet = len(micro_layers) + len(tape_layers)
        n_rv = len(reverb_layers)
        managed_wet = np.asarray(
            self.wet_bus.process(wet, wet_voice_count=n_wet, reverb_layer_count=n_rv),
            dtype=np.float32,
        )

        # Master spectral smear -> the evolving wash. Density deepens it.
        suspension = min(1.0, 0.25 + 0.7 * crowd.density)
        smear = min(1.0, 0.35 + 0.5 * crowd.density)
        smeared = np.asarray(
            self.spectral_smear.process(managed_wet, suspension=suspension, smear=smear),
            dtype=np.float64,
        )

        # Reverb size grows with density (spec section 7: spectral bloom).
        target_fb = min(0.985, 0.9 + 0.06 * crowd.density)
        target_cut = 3000.0 + 4000.0 * (1.0 - crowd.density)
        rv_size = min(1.0, 0.5 + 0.45 * crowd.density)
        rv_diffusion = min(1.0, 0.6 + 0.35 * crowd.density)
        self._rv_feedback += REVERB_SMOOTHING * (target_fb - self._rv_feedback)
        self._rv_cutoff += REVERB_SMOOTHING * (target_cut - self._rv_cutoff)
        self.reverb.set_feedback(self._rv_feedback)
        self.reverb.set_cutoff(self._rv_cutoff)
        self.reverb.set_space(style="wash", size=rv_size, diffusion=rv_diffusion)
        reverb_wet = self.reverb.process(smeared)
        wet_final = self.wet_limiter.process(smeared + self.reverb_mix * reverb_wet)

        mix = float(np.clip(self.wet_dry, 0.0, 1.0))
        dry_gain = min(1.0, 2.0 * (1.0 - mix))
        wet_gain = min(1.0, 2.0 * mix)
        return soft_clip(dry_gain * dry + wet_gain * wet_final).astype(np.float32)
```

- [ ] **Step 4: Run the full DSP suite to verify it passes**

Run: `rtk python -m pytest tests/ -v`
Expected: PASS — every test, including all pre-existing loop-mode tests, `test_synth_source.py`, `test_spectral_stretch.py`, and `test_web_engine_synth.py`.

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/web_engine.py audio_prototype/tests/test_web_engine_synth.py
rtk git commit -m "feat(synth): add tape voices, density-driven master smear and reverb"
```

---

## Task 10: Worker — `set_mode` message and new Python files

**Files:**
- Modify: `webapp/worker.js:9-18` (PYTHON_FILES) and the `self.onmessage` handler.

**Interfaces:**
- Consumes: `engine.set_mode(...)` (Task 6). The two new modules must be fetched into the Pyodide FS *before* `web_engine.py` imports them.
- Produces: a `{type: "set_mode", mode: "loop"|"synth"}` message handler that runs `engine.set_mode(...)` and flushes the audio buffer (same pattern as `load_loop`/`play`).

- [ ] **Step 1: Add the new modules to `PYTHON_FILES`**

`web_engine.py` imports `spectral_stretch` and `synth_source`, so they must be present in the Pyodide filesystem. Order does not matter for `writeFile` (imports resolve at `runPython` time), but list them before `web_engine.py` for readability:

```javascript
const PYTHON_FILES = [
  "modulation.py",
  "layers.py",
  "tape_modulator.py",
  "microcosm_processor.py",
  "reverb.py",
  "wet_bus.py",
  "crowd.py",
  "spectral_stretch.py",
  "synth_source.py",
  "web_engine.py",
];
```

- [ ] **Step 2: Add the `set_mode` handler**

In `self.onmessage`, add a branch alongside the others (e.g. after the `set_wet_dry` branch, `worker.js:123-124`):

```javascript
    } else if (msg.type === "set_mode") {
      pyodide.runPython(`engine.set_mode(${JSON.stringify(msg.mode)})`);
      bufferedAheadFrames = 0;
      if (audioPort) audioPort.postMessage({ type: "flush" });
    } else if (msg.type === "set_wet_dry") {
```

(Place it so it reads cleanly among the existing `else if` chain; the exact position is not significant as long as it is inside the `try` in `onmessage`.)

- [ ] **Step 3: Verify the worker still loads (manual smoke test)**

Run: `rtk npx serve .` from `webapp/`, open the served URL, and confirm the status banner reaches "ready" (the app div appears) with no console error. This proves `synth_source.py` and `spectral_stretch.py` fetch and import cleanly under Pyodide.
Expected: app loads; loop mode plays exactly as before (Load Loop → patch → sound).

- [ ] **Step 4: Commit**

```bash
rtk git add webapp/worker.js
rtk git commit -m "feat(webapp): add set_mode worker message and register synth modules"
```

---

## Task 11: UI — mode toggle, patch-bay reset, hide Load Loop in synth

**Files:**
- Modify: `webapp/index.html:12-18` (Sound Source section), `webapp/main.js`, `webapp/style.css`.

**Interfaces:**
- Consumes: `worker.postMessage({type: "set_mode", mode})` (Task 10).
- Produces:
  - A Loop/Synth toggle in `index.html` (`id="mode-loop"`, `id="mode-synth"`, radio-style buttons in a `.mode-toggle` group).
  - `App` tracks `this.mode` (default `"loop"`) and a `setMode(mode)` method that: posts `set_mode`, clears client patch state (`this.sources`, `this._pendingSources`, `this.dragSourceId`, `this.dragPos`), toggles the Load Loop button's visibility, updates the toggle's active styling, and redraws.
  - Switching modes **resets the patch bay** on the client to match the engine's server-side reset (spec section 5).

- [ ] **Step 1: Add the toggle to `index.html`**

Replace the first `control-row` in the Sound Source section (`index.html:14-18`) with:

```html
      <div class="control-row mode-toggle">
        <button id="mode-loop" class="mode-active">Loop</button>
        <button id="mode-synth">Synth</button>
      </div>
      <div class="control-row">
        <button id="load-loop-button">Load Loop...</button>
        <input id="load-loop-file" type="file" accept="audio/*" class="hidden" />
        <button id="play-pause-button">Play</button>
      </div>
```

- [ ] **Step 2: Add mode state and `setMode` to `main.js`**

In the `App` constructor, after `this.currentHsv = ...` (`main.js:143`), add:

```javascript
    this.mode = "loop";
```

After the existing element lookups (e.g. after `this.sourceListEl = ...`, `main.js:154`), add:

```javascript
    this.modeLoopButton = document.getElementById("mode-loop");
    this.modeSynthButton = document.getElementById("mode-synth");
    this.loadLoopButton = document.getElementById("load-loop-button");
```

In `bindControls` (`main.js:267`), add:

```javascript
    this.modeLoopButton.addEventListener("click", () => this.setMode("loop"));
    this.modeSynthButton.addEventListener("click", () => this.setMode("synth"));
```

Add the method (e.g. after `bindControls`):

```javascript
  setMode(mode) {
    if (mode === this.mode) return;
    this.mode = mode;
    this.worker.postMessage({ type: "set_mode", mode });

    // Mirror the engine's server-side reset: clear all client patch state.
    this.sources.clear();
    this._pendingSources = [];
    this.dragSourceId = null;
    this.dragPos = null;

    // Load Loop is meaningless in synth mode (voices are generated).
    this.loadLoopButton.classList.toggle("hidden", mode === "synth");
    this.modeLoopButton.classList.toggle("mode-active", mode === "loop");
    this.modeSynthButton.classList.toggle("mode-active", mode === "synth");

    this.drawPatchBay();
    this.renderSourceList();
  }
```

- [ ] **Step 3: Add minimal toggle styling to `style.css`**

Append:

```css
.mode-toggle button {
  opacity: 0.55;
}
.mode-toggle button.mode-active {
  opacity: 1;
  font-weight: 600;
  text-decoration: underline;
}
```

- [ ] **Step 4: Verify the toggle end-to-end (manual)**

Run: `rtk npx serve .` from `webapp/`. Then:
1. In Loop mode: Load a loop, Send a source, patch it — confirm sound (unchanged behavior).
2. Click **Synth** — confirm: the patch bay clears (no sources), the Load Loop button disappears, and the Synth button shows active styling.
3. Click Play (if paused), Send a source, drag it onto a `granules` cell — confirm a sustained tone/wash is audible with **no loop loaded**.
4. Add several more sources across rows — confirm the wash thickens and stays bounded (no clipping/NaN; watch the Underruns readout stays stable).
5. Click **Loop** — confirm the patch bay clears again and Load Loop reappears.

Expected: all five behave as described.

- [ ] **Step 5: Commit**

```bash
rtk git add webapp/index.html webapp/main.js webapp/style.css
rtk git commit -m "feat(webapp): add Loop/Synth mode toggle with patch-bay reset"
```

---

## Task 12: Full-suite verification and brief refresh

**Files:**
- Modify: `RedPole/AGENTS.md:6-12` ("Pick up here").

**Interfaces:** none (verification + docs).

- [ ] **Step 1: Run the complete Python suite**

Run: `rtk python -m pytest tests/ -v` (from `audio_prototype/`)
Expected: PASS — all pre-existing tests plus the three new synth test files. Confirm the count of passing tests and that zero loop-mode tests changed.

- [ ] **Step 2: Confirm loop mode is byte-unchanged**

Run: `rtk python -m pytest tests/test_web_engine.py tests/test_microcosm_processor.py tests/test_tape_modulator.py -v`
Expected: PASS with no modifications to loop-mode assertions (the parity test in Task 5 and the untouched `test_web_engine.py` are the guardrails).

- [ ] **Step 3: Final manual smoke of both modes**

Run: `rtk npx serve .` from `webapp/`; verify loop mode (load + patch → sound) and synth mode (no load + patch → evolving wash), and that toggling resets the bay both ways. Confirm no console errors and stable underruns.

- [ ] **Step 4: Refresh the "Pick up here" brief**

Update `RedPole/AGENTS.md:6-12` to reflect that synth mode is implemented:

```markdown
## ⏱ Pick up here   ← LIVING; refresh at session end
- **Status:**       Prototype — web app now has Loop + Synth modes; synth generates per-voice detuned drones with a density-driven spectral-smear wash. Firmware/TD integration still WIP.
- **Last session:** 2026-07-22 — implemented synth mode (synth_source.py, spectral_stretch.py, WebEngine.mode branch, UI toggle) per docs/superpowers/plans/2026-07-22-synth-mode.md.
- **Next up:**
  - Tune by ear: color→timbre map (synth_source.voice_timbre_from_color), drone pitch-set, and whether the spectral smear should also run per-voice (spec §10).
  - Document the firmware serial message shape (base64 JPEG framing).
- **Blockers / open questions:** Is TD driven by the web app, the Python engine, or the device directly?
```

- [ ] **Step 5: Commit**

```bash
rtk git add RedPole/AGENTS.md
rtk git commit -m "docs: mark synth mode implemented in agent brief"
```

---

## Notes for tuning after implementation (spec §10 — not part of this plan)

These are deliberately deferred; the machinery above is built so each is a small, local change:
- **Color → timbre**: edit only `synth_source.voice_timbre_from_color`.
- **Drone pitch-set**: edit `DRONE_ROOT_HZ` / `DRONE_RATIOS` in `synth_source.py`.
- **Per-voice spectral stretch**: instantiate a `SpectralSmear` per voice in `SynthVoiceBank` (the class already supports it) — currently master-only by decision #3.
- **Smear/reverb density curves**: the `suspension`/`smear`/`rv_size` expressions in `_generate_synth_block`.
