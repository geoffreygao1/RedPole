# Evolving Soundscape Synthesizer — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 1 of the Evolving Soundscape Synthesizer spec (`docs/superpowers/specs/2026-07-22-evolving-soundscape-design.md` — see source spec `evolving_soundscape_synthesizer_spec.md` §12/§13) as new, additive Python modules in `audio_prototype/`: five source engines and five transformation engines (5 presets each = 25 + 25 behaviors), a shared harmonic pitch field with register-aware allocation, density-based gain scaling, a simple voice-priority system, and a runnable harness that simulates ~8 patches so the design can be tuned by ear on real desktop CPU.

**Architecture:** A `SoundscapeEngine` owns a `HarmonicField`/`PitchAllocator` (shared pitch set + register occupancy, spec §6/§17), a `SourceBank` of five generative engines (additive drone, granular cloud, resonant pulse, filtered noise, sample texture — spec §7/§12), a `TransformBank` of five signal transforms (delay, spectral, pitch/resonance, granular-fx, spatial — spec §8/§12), and density/priority bookkeeping (spec §9). It intentionally does **not** touch `LayerRegistry`, `WebEngine`, `gui.py`, or `webapp/` — this plan models patches with a small local `SoundscapePatch` type instead of the existing 5×5-matrix `LayerRegistry`, because the spec's two-matrix (output preset + input preset) topology doesn't fit the existing single-engine/row/col shape. Wiring this into the real patch bay UI, hardware, and eventually replacing the web app's Synth mode are separate future plans (spec Phases 2–5).

**Tech Stack:** Python 3.11 + NumPy only (no scipy — confirmed absent from `audio_prototype/requirements.txt`); `sounddevice` for the desktop playback harness; pytest for tests.

## Global Constraints

- **Phase 1 scope only.** This plan implements spec §12 ("Suggested Prototype Scope") and §13 Phase 1 exactly: 5 source engines × 5 presets, 5 transform engines × 5 presets, ≥8 simultaneous simulated patches, global pitch quantization, density-based gain scaling, a simple voice-priority system. It does **not** implement the real 5×5 GUI matrices (spec Phase 2), hardware integration (Phase 3), the collective-tempo/chord-transition composition engine (Phase 4), reference-track tuning (Phase 5), or any web/Pyodide port — those are separate future plans.
- **Additive only.** Do not modify `layers.py`, `crowd.py`, `web_engine.py`, `gui.py`, `audio_engine.py`, or anything in `webapp/`. All new code lives in new files under `audio_prototype/`.
- **NumPy-only DSP.** No scipy, no new third-party dependencies. Hand-roll filters/resonators as one-pole/biquad difference equations, matching the existing style in `reverb.py`/`tape_modulator.py`.
- **Reuse existing generic helpers** rather than duplicating: `modulation.hue_to_unit/sat_to_unit/val_to_unit`, `modulation.RmsLimiter`, `modulation.soft_clip`, `synth_source.SeedBank` (wavetable generation), `spectral_stretch.SpectralSmear` (phase vocoder), `reverb.SchroederReverb`.
- **Determinism.** Every stochastic component takes a `seed` and uses `np.random.default_rng(seed)`; same seed → same output.
- **Per-voice lifecycle idiom.** Every engine keeps a `dict[layer_id -> voice_state]`, created on first sight, garbage-collected via a `sync(active_ids)` call each block — matches the pattern already used by `MicrocosmProcessor`/`SynthVoiceBank`. Use the shared `soundscape_voices.sync_voices` helper (Task 1) everywhere instead of re-writing the GC loop.
- **Run tests from `audio_prototype/`**: `rtk python -m pytest tests/<file> -v` (the existing `conftest.py` puts the module dir on `sys.path`).
- Prefix shell/build/git commands with `rtk` (project convention).

## File Structure

**Create:**
- `audio_prototype/soundscape_color.py` — calibrated-color mapping (spec §5.1).
- `audio_prototype/soundscape_voices.py` — shared per-voice-dict GC helper.
- `audio_prototype/soundscape_harmony.py` — pitch set, role weights, register occupancy, pitch allocator (spec §6, §17).
- `audio_prototype/soundscape_density.py` — density-based gain smoothing, voice-priority budgets, event probability (spec §9).
- `audio_prototype/soundscape_sources.py` — 5 source engines + 25 presets + `SourceBank` dispatcher (spec §7, §12).
- `audio_prototype/soundscape_transforms.py` — 5 transform engines + 25 presets + `TransformBank` dispatcher (spec §8, §12).
- `audio_prototype/soundscape_engine.py` — `SoundscapePatch`, `SoundscapeEngine` orchestration.
- `audio_prototype/soundscape_prototype.py` — runnable playback harness (spec §13 Phase 1).
- `audio_prototype/tests/test_soundscape_color.py`
- `audio_prototype/tests/test_soundscape_harmony.py`
- `audio_prototype/tests/test_soundscape_density.py`
- `audio_prototype/tests/test_soundscape_sources.py`
- `audio_prototype/tests/test_soundscape_transforms.py`
- `audio_prototype/tests/test_soundscape_engine.py`
- `audio_prototype/tests/test_soundscape_prototype.py`

**Modify:**
- `RedPole/AGENTS.md` — refresh "Pick up here" at the end (Task 16 only).

---

## Task 1: Calibrated color + shared per-voice GC helper

**Files:**
- Create: `audio_prototype/soundscape_color.py`, `audio_prototype/soundscape_voices.py`
- Test: `audio_prototype/tests/test_soundscape_color.py`

**Interfaces:**
- Consumes: `modulation.hue_to_unit/sat_to_unit/val_to_unit`.
- Produces: `calibrate_color(hue, sat, val) -> dict` with keys `warmth`, `brightness`, `saturation` (spec §5.1's `CalibratedColor`), and `sync_voices(voices: dict, active_ids: Iterable) -> None` (drops dict entries whose key isn't in `active_ids`).

- [x] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_soundscape_color.py
import modulation as mod
from soundscape_color import calibrate_color
from soundscape_voices import sync_voices


def test_calibrate_color_maps_gamut_extremes_to_unit_range():
    dark = calibrate_color(mod.FINGER_HUE_MIN, mod.FINGER_SAT_MIN, mod.FINGER_VAL_MIN)
    bright = calibrate_color(mod.FINGER_HUE_MAX, mod.FINGER_SAT_MAX, mod.FINGER_VAL_MAX)
    assert dark["warmth"] == 0.0
    assert bright["warmth"] == 1.0
    assert bright["brightness"] > dark["brightness"]
    assert bright["saturation"] > dark["saturation"]
    for d in (dark, bright):
        for key in ("warmth", "brightness", "saturation"):
            assert 0.0 <= d[key] <= 1.0


def test_sync_voices_drops_inactive_and_keeps_active():
    voices = {1: "a", 2: "b", 3: "c"}
    sync_voices(voices, [1, 3])
    assert voices == {1: "a", 3: "c"}


def test_sync_voices_handles_empty_active_list():
    voices = {1: "a"}
    sync_voices(voices, [])
    assert voices == {}
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_color.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soundscape_color'`.

- [x] **Step 3: Write minimal implementation**

```python
# audio_prototype/soundscape_color.py
"""Calibrated color mapping for the soundscape system (spec section 5.1-5.4).

The scanner only produces red-to-orange hues; warmth/brightness/saturation
are the continuous timbral macros every source/transform engine reads
instead of treating color as a preset selector.
"""

from modulation import hue_to_unit, sat_to_unit, val_to_unit


def calibrate_color(hue, sat, val):
    return {
        "warmth": float(hue_to_unit(hue)),        # 0 = deepest red, 1 = most orange
        "brightness": float(val_to_unit(val)),
        "saturation": float(sat_to_unit(sat)),
    }
```

```python
# audio_prototype/soundscape_voices.py
"""Shared per-voice lifecycle helper: every soundscape engine keeps a
dict[layer_id -> state], created on first sight, garbage-collected here
when a layer id disappears -- the same create/GC idiom already used by
MicrocosmProcessor and SynthVoiceBank."""


def sync_voices(voices, active_ids):
    active = set(active_ids)
    for vid in [v for v in voices if v not in active]:
        del voices[v]
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_color.py -v`
Expected: PASS (3 tests).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_color.py audio_prototype/soundscape_voices.py audio_prototype/tests/test_soundscape_color.py
rtk git commit -m "feat(soundscape): add calibrated-color mapping and voice-GC helper"
```

---

## Task 2: Shared harmonic field (pitch set + role weights)

**Files:**
- Create: `audio_prototype/soundscape_harmony.py`
- Test: `audio_prototype/tests/test_soundscape_harmony.py`

**Interfaces:**
- Consumes: nothing (leaf module, numpy only).
- Produces:
  - `PENTATONIC_SEMITONES = (0, 2, 5, 7, 10)` (spec §17.8 suspended pentatonic).
  - `ROLE_SEMITONES: dict[str,int]` and `ROLE_WEIGHTS: dict[str,float]` (spec §17.3: root 0.32, fifth 0.24, fourth 0.16, ninth 0.14, seventh 0.10, tension 0.04).
  - `midi_to_hz(midi) -> float|np.ndarray`.
  - `class HarmonicField(root_midi=62, tension_enabled=True)` with `.roles() -> tuple[str,...]`, `.weighted_role(rng) -> str`, `.semitone_for_role(role) -> int`, `.midi_for_role(role, octave_offset=0) -> float`.

- [x] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_soundscape_harmony.py
import numpy as np

from soundscape_harmony import HarmonicField, ROLE_WEIGHTS, midi_to_hz


def test_midi_to_hz_a4_is_440():
    assert abs(midi_to_hz(69) - 440.0) < 1e-6


def test_field_midi_for_role_uses_root_and_semitone_offsets():
    field = HarmonicField(root_midi=62)
    assert field.midi_for_role("root") == 62
    assert field.midi_for_role("fifth") == 62 + 7
    assert field.midi_for_role("fifth", octave_offset=1) == 62 + 7 + 12


def test_field_excludes_tension_when_disabled():
    field = HarmonicField(root_midi=62, tension_enabled=False)
    assert "tension" not in field.roles()
    rng = np.random.default_rng(0)
    for _ in range(50):
        assert field.weighted_role(rng) != "tension"


def test_weighted_role_matches_declared_weights_over_many_draws():
    field = HarmonicField(root_midi=62)
    rng = np.random.default_rng(1)
    counts = {r: 0 for r in field.roles()}
    n = 20000
    for _ in range(n):
        counts[field.weighted_role(rng)] += 1
    for role, weight in ROLE_WEIGHTS.items():
        assert abs(counts[role] / n - weight) < 0.02
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_harmony.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soundscape_harmony'`.

- [x] **Step 3: Write minimal implementation**

```python
# audio_prototype/soundscape_harmony.py
"""Shared harmonic field for soundscape voices (spec section 6, 17).

All tonal/modal voices pull pitches from one shared pitch set instead of
choosing arbitrary independent notes. This module owns the pitch set,
per-role weighting, register occupancy, and the pitch allocator (Task 3).
"""

import numpy as np

PENTATONIC_SEMITONES = (0, 2, 5, 7, 10)   # suspended pentatonic, spec 17.8

ROLE_SEMITONES = {
    "root": 0,
    "fifth": 7,
    "fourth": 5,
    "ninth": 2,
    "seventh": 10,
    "tension": 1,          # minor second above root, spec 17.8
}

ROLE_WEIGHTS = {           # spec 17.3
    "root": 0.32,
    "fifth": 0.24,
    "fourth": 0.16,
    "ninth": 0.14,
    "seventh": 0.10,
    "tension": 0.04,
}


def midi_to_hz(midi):
    return 440.0 * (2.0 ** ((np.asarray(midi, dtype=np.float64) - 69.0) / 12.0))


class HarmonicField:
    """The current shared tonal center + pitch set (spec 17.3). A future
    Phase 4 plan will make root_midi/tension_enabled evolve over time
    (spec 6.7's HarmonicState); for Phase 1 it is fixed at construction."""

    def __init__(self, root_midi=62, tension_enabled=True):
        self.root_midi = int(root_midi)
        self.tension_enabled = tension_enabled

    def roles(self):
        if self.tension_enabled:
            return tuple(ROLE_WEIGHTS.keys())
        return tuple(r for r in ROLE_WEIGHTS if r != "tension")

    def weighted_role(self, rng):
        roles = self.roles()
        weights = np.array([ROLE_WEIGHTS[r] for r in roles], dtype=np.float64)
        weights /= weights.sum()
        return roles[int(rng.choice(len(roles), p=weights))]

    def semitone_for_role(self, role):
        return ROLE_SEMITONES[role]

    def midi_for_role(self, role, octave_offset=0):
        return self.root_midi + self.semitone_for_role(role) + 12 * int(octave_offset)
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_harmony.py -v`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_harmony.py audio_prototype/tests/test_soundscape_harmony.py
rtk git commit -m "feat(soundscape): add shared harmonic field with weighted pitch roles"
```

---

## Task 3: Register occupancy + pitch allocator

**Files:**
- Modify: `audio_prototype/soundscape_harmony.py`
- Test: `audio_prototype/tests/test_soundscape_harmony.py`

**Interfaces:**
- Consumes: `HarmonicField` (Task 2).
- Produces:
  - `REGISTER_BANDS` (5 Hz-range bands, spec §9.4) and `REGISTER_LIMITS` (spec §17.5).
  - `band_for_hz(hz) -> str`.
  - `class RegisterOccupancy` with `.counts() -> dict`, `.register(vid, band)`, `.release(vid)`, `.is_crowded(band) -> bool`.
  - `DETUNE_CENTS_RANGE: dict[str,float]` (spec §6.6).
  - `class PitchAssignment` with attributes `pitch_class, octave, detune_cents, harmonic_role, midi`.
  - `class PitchAllocator(field, occupancy=None)` with `.allocate(vid, rng, density, detune_class="foreground") -> PitchAssignment` and `.release(vid)`.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_soundscape_harmony.py
from soundscape_harmony import (
    DETUNE_CENTS_RANGE,
    PitchAllocator,
    RegisterOccupancy,
    band_for_hz,
)


def test_band_for_hz_matches_named_ranges():
    assert band_for_hz(80) == "sub"
    assert band_for_hz(300) == "low"
    assert band_for_hz(1000) == "mid"
    assert band_for_hz(4000) == "high"
    assert band_for_hz(10000) == "air"


def test_register_occupancy_tracks_and_releases():
    occ = RegisterOccupancy()
    occ.register(1, "sub")
    occ.register(2, "sub")
    assert occ.counts()["sub"] == 2
    occ.release(1)
    assert occ.counts()["sub"] == 1
    occ.release(1)  # releasing twice is a no-op
    assert occ.counts()["sub"] == 1


def test_allocator_avoids_crowded_low_registers_at_high_density():
    field = HarmonicField(root_midi=24)  # very low root -> "root" role starts in "sub"
    allocator = PitchAllocator(field)
    rng = np.random.default_rng(2)
    assignment = allocator.allocate(1, rng, density=0.9, detune_class="foreground")
    assert assignment.octave >= 1  # pushed up out of the crowded low register


def test_allocator_detune_respects_class_range():
    field = HarmonicField(root_midi=62)
    allocator = PitchAllocator(field)
    rng = np.random.default_rng(3)
    for _ in range(50):
        a = allocator.allocate(4, rng, density=0.1, detune_class="granular")
        assert abs(a.detune_cents) <= DETUNE_CENTS_RANGE["granular"]
        allocator.release(4)


def test_allocator_release_frees_register_slot():
    field = HarmonicField(root_midi=62)
    allocator = PitchAllocator(field)
    rng = np.random.default_rng(4)
    allocator.allocate(1, rng, density=0.0)
    before = sum(allocator.occupancy.counts().values())
    allocator.release(1)
    after = sum(allocator.occupancy.counts().values())
    assert after == before - 1
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_harmony.py -k "band_for_hz or occupancy or allocator" -v`
Expected: FAIL — `ImportError: cannot import name 'PitchAllocator'`.

- [x] **Step 3: Write minimal implementation**

```python
# append to audio_prototype/soundscape_harmony.py

REGISTER_BANDS = (                     # spec 9.4 Hz ranges, spec 17.5 names
    ("sub", 40.0, 120.0),
    ("low", 120.0, 500.0),
    ("mid", 500.0, 2000.0),
    ("high", 2000.0, 6000.0),
    ("air", 6000.0, 14000.0),
)

REGISTER_LIMITS = {"sub": 2, "low": 3, "mid": 5, "high": 7, "air": 8}   # spec 17.5

DETUNE_CENTS_RANGE = {                 # spec 6.6
    "foreground": 4.0,
    "background": 8.0,
    "granular": 15.0,
    "texture": 30.0,                   # "unconstrained, but low in level"
}


def band_for_hz(hz):
    for name, lo, hi in REGISTER_BANDS:
        if lo <= hz < hi:
            return name
    return "air" if hz >= REGISTER_BANDS[-1][2] else "sub"


class RegisterOccupancy:
    def __init__(self):
        self._counts = {name: 0 for name, _, _ in REGISTER_BANDS}
        self._by_voice = {}

    def counts(self):
        return dict(self._counts)

    def register(self, vid, band):
        self.release(vid)
        self._counts[band] += 1
        self._by_voice[vid] = band

    def release(self, vid):
        band = self._by_voice.pop(vid, None)
        if band is not None:
            self._counts[band] -= 1

    def is_crowded(self, band):
        return self._counts[band] >= REGISTER_LIMITS[band]


class PitchAssignment:
    __slots__ = ("pitch_class", "octave", "detune_cents", "harmonic_role", "midi")

    def __init__(self, pitch_class, octave, detune_cents, harmonic_role, midi):
        self.pitch_class = pitch_class
        self.octave = octave
        self.detune_cents = detune_cents
        self.harmonic_role = harmonic_role
        self.midi = midi


class PitchAllocator:
    """Assigns each connected voice a pitch from the shared HarmonicField,
    preferring registers that are not already crowded and pushing sparse
    upper extensions as density rises (spec 6.5)."""

    def __init__(self, field, occupancy=None):
        self.field = field
        self.occupancy = occupancy if occupancy is not None else RegisterOccupancy()

    def allocate(self, vid, rng, density, detune_class="foreground"):
        role = self.field.weighted_role(rng)
        octave_offset = 0
        for _ in range(4):
            midi = self.field.midi_for_role(role, octave_offset)
            band = band_for_hz(midi_to_hz(midi))
            if not self.occupancy.is_crowded(band):
                break
            octave_offset += 1
        else:
            octave_offset = int(rng.integers(1, 3))
            midi = self.field.midi_for_role(role, octave_offset)
            band = band_for_hz(midi_to_hz(midi))
        if density > 0.6 and band in ("sub", "low"):
            octave_offset += 1
            midi = self.field.midi_for_role(role, octave_offset)
            band = band_for_hz(midi_to_hz(midi))
        detune_limit = DETUNE_CENTS_RANGE.get(detune_class, DETUNE_CENTS_RANGE["foreground"])
        detune_cents = float(rng.uniform(-detune_limit, detune_limit))
        self.occupancy.register(vid, band)
        return PitchAssignment(
            pitch_class=self.field.semitone_for_role(role) % 12,
            octave=octave_offset,
            detune_cents=detune_cents,
            harmonic_role=role,
            midi=midi + detune_cents / 100.0,
        )

    def release(self, vid):
        self.occupancy.release(vid)
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_harmony.py -v`
Expected: PASS (9 tests total).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_harmony.py audio_prototype/tests/test_soundscape_harmony.py
rtk git commit -m "feat(soundscape): add register-aware pitch allocator"
```

---

## Task 4: Density-based gain smoothing

**Files:**
- Create: `audio_prototype/soundscape_density.py`
- Test: `audio_prototype/tests/test_soundscape_density.py`

**Interfaces:**
- Consumes: numpy only.
- Produces: `class DensityGainSmoother(base_gain=1.0, smoothing=0.05)` with `.update(active_count) -> float`, implementing spec §9.3 `voiceGain = baseGain / sqrt(activeVoiceCount)` with one-pole smoothing so gain doesn't jump between blocks.

- [x] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_soundscape_density.py
import numpy as np

from soundscape_density import DensityGainSmoother


def test_gain_decreases_as_count_grows_once_settled():
    low = DensityGainSmoother()
    high = DensityGainSmoother()
    for _ in range(200):
        g_low = low.update(2)
        g_high = high.update(20)
    assert g_high < g_low


def test_gain_approaches_formula_after_settling():
    smoother = DensityGainSmoother(base_gain=1.0)
    for _ in range(500):
        g = smoother.update(9)
    assert abs(g - 1.0 / np.sqrt(9)) < 0.01


def test_gain_changes_smoothly_not_abruptly():
    smoother = DensityGainSmoother()
    smoother.update(1)
    g_before = smoother.update(1)
    g_after_jump = smoother.update(25)
    # a single block should not jump all the way to the new target
    target = 1.0 / np.sqrt(25)
    assert abs(g_after_jump - target) > abs(g_before - target) * 0.01
    assert g_after_jump < g_before
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_density.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soundscape_density'`.

- [x] **Step 3: Write minimal implementation**

```python
# audio_prototype/soundscape_density.py
"""Density-based gain scaling and voice-priority budgeting (spec section 9)."""

import numpy as np

GAIN_SMOOTHING = 0.05   # one-pole coefficient per block, spec 9.3 "apply smoothing"


class DensityGainSmoother:
    def __init__(self, base_gain=1.0, smoothing=GAIN_SMOOTHING):
        self.base_gain = base_gain
        self.smoothing = smoothing
        self._current = base_gain

    def update(self, active_count):
        target = self.base_gain / np.sqrt(max(1, active_count))
        self._current += self.smoothing * (target - self._current)
        return float(self._current)
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_density.py -v`
Expected: PASS (3 tests).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_density.py audio_prototype/tests/test_soundscape_density.py
rtk git commit -m "feat(soundscape): add density-based gain smoothing"
```

---

## Task 5: Voice-priority budgets + event probability

**Files:**
- Modify: `audio_prototype/soundscape_density.py`
- Test: `audio_prototype/tests/test_soundscape_density.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `ROLE_FOREGROUND/ROLE_MIDGROUND/ROLE_BACKGROUND/ROLE_DORMANT` string constants and `ROLE_GAIN: dict[str,float]`.
  - `assign_voice_roles(order_ids) -> dict[id, str]` — respects spec §9.2 budgets (3-5 foreground, 5-8 midground, 4-8 background, rest dormant), where `order_ids` is a sequence of ids in priority order (oldest/most-important first).
  - `event_probability(active_count) -> float` — spec §9.5's probability-by-density table, linearly interpolated within each bucket.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_soundscape_density.py
from soundscape_density import (
    ROLE_BACKGROUND,
    ROLE_DORMANT,
    ROLE_FOREGROUND,
    ROLE_MIDGROUND,
    assign_voice_roles,
    event_probability,
)


def test_assign_voice_roles_small_group_is_all_foreground():
    roles = assign_voice_roles([1, 2, 3])
    assert all(r == ROLE_FOREGROUND for r in roles.values())


def test_assign_voice_roles_respects_budgets_for_large_group():
    order = list(range(1, 26))  # 25 patches
    roles = assign_voice_roles(order)
    counts = {}
    for r in roles.values():
        counts[r] = counts.get(r, 0) + 1
    assert 3 <= counts.get(ROLE_FOREGROUND, 0) <= 5
    assert 5 <= counts.get(ROLE_MIDGROUND, 0) <= 8
    assert 4 <= counts.get(ROLE_BACKGROUND, 0) <= 8
    assert counts.get(ROLE_DORMANT, 0) > 0
    assert sum(counts.values()) == 25


def test_event_probability_decreases_with_density():
    assert event_probability(3) > event_probability(10) > event_probability(18) > event_probability(24)
    assert 0.0 <= event_probability(24) <= 1.0


def test_event_probability_within_bucket_bounds():
    assert 0.70 <= event_probability(1) <= 1.00
    assert 0.05 <= event_probability(25) <= 0.30
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_density.py -k "assign_voice_roles or event_probability" -v`
Expected: FAIL — `ImportError: cannot import name 'assign_voice_roles'`.

- [x] **Step 3: Write minimal implementation**

```python
# append to audio_prototype/soundscape_density.py

FOREGROUND_BUDGET = (3, 5)     # spec 9.2
MIDGROUND_BUDGET = (5, 8)
BACKGROUND_BUDGET = (4, 8)

ROLE_FOREGROUND = "foreground"
ROLE_MIDGROUND = "midground"
ROLE_BACKGROUND = "background"
ROLE_DORMANT = "dormant"

ROLE_GAIN = {ROLE_FOREGROUND: 1.0, ROLE_MIDGROUND: 0.55, ROLE_BACKGROUND: 0.28, ROLE_DORMANT: 0.0}


def assign_voice_roles(order_ids):
    """order_ids: ids in priority order (e.g. most-recently-connected last).
    Returns {id: role} respecting spec 9.2 budgets."""
    roles = {}
    n = len(order_ids)
    fg_n = min(n, FOREGROUND_BUDGET[1])
    mg_n = min(max(0, n - fg_n), MIDGROUND_BUDGET[1])
    bg_n = min(max(0, n - fg_n - mg_n), BACKGROUND_BUDGET[1])
    for i, vid in enumerate(order_ids):
        if i < fg_n:
            roles[vid] = ROLE_FOREGROUND
        elif i < fg_n + mg_n:
            roles[vid] = ROLE_MIDGROUND
        elif i < fg_n + mg_n + bg_n:
            roles[vid] = ROLE_BACKGROUND
        else:
            roles[vid] = ROLE_DORMANT
    return roles


_EVENT_PROBABILITY_BUCKETS = (   # (lo, hi, p_at_lo, p_at_hi), spec 9.5
    (1, 5, 1.00, 0.70),
    (6, 12, 0.70, 0.35),
    (13, 20, 0.45, 0.15),
    (21, 25, 0.30, 0.05),
)


def event_probability(active_count):
    n = max(1, int(active_count))
    for lo, hi, p_lo, p_hi in _EVENT_PROBABILITY_BUCKETS:
        if lo <= n <= hi:
            frac = (n - lo) / max(1, hi - lo)
            return float(p_lo + (p_hi - p_lo) * frac)
    return 0.05 if n > 25 else 1.0
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_density.py -v`
Expected: PASS (7 tests total).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_density.py audio_prototype/tests/test_soundscape_density.py
rtk git commit -m "feat(soundscape): add voice-priority budgets and event-probability table"
```

---

## Task 6: Additive Drone source engine + presets

**Files:**
- Create: `audio_prototype/soundscape_sources.py`
- Test: `audio_prototype/tests/test_soundscape_sources.py`

**Interfaces:**
- Consumes: `synth_source.SeedBank` (existing, reused unmodified), `soundscape_harmony.midi_to_hz`/`PitchAssignment`, `soundscape_voices.sync_voices`.
- Produces:
  - `ADDITIVE_PRESETS: list[dict]` — 5 presets, each `{"id", "register_bias", "brightness_bias", "attack"}`.
  - `class AdditiveDroneSource(samplerate, seed=None)` with `.render(vid, assignment, timbre, frames, preset) -> np.ndarray` (float64, shape `(frames,)`) and `.sync(active_ids)`.

- [x] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_soundscape_sources.py
import numpy as np

from soundscape_color import calibrate_color
from soundscape_harmony import HarmonicField, PitchAllocator
from soundscape_sources import ADDITIVE_PRESETS, AdditiveDroneSource


def _assignment(midi=62):
    field = HarmonicField(root_midi=midi)
    allocator = PitchAllocator(field)
    rng = np.random.default_rng(0)
    return allocator.allocate(1, rng, density=0.1)


def test_additive_has_five_presets_with_required_keys():
    assert len(ADDITIVE_PRESETS) == 5
    for p in ADDITIVE_PRESETS:
        assert {"id", "register_bias", "brightness_bias", "attack"} <= set(p)


def test_additive_produces_a_bounded_sustained_tone():
    src = AdditiveDroneSource(44100, seed=1)
    assignment = _assignment()
    timbre = calibrate_color(0.03, 0.68, 0.94)
    preset = ADDITIVE_PRESETS[0]
    blocks = [src.render(1, assignment, timbre, 1024, preset) for _ in range(80)]
    total = np.concatenate(blocks)
    assert total.dtype == np.float64
    assert np.max(np.abs(total)) <= 1.0 + 1e-6
    assert not np.any(np.isnan(total))
    tail_rms = float(np.sqrt(np.mean(total[-8192:] ** 2)))
    assert tail_rms > 0.02


def test_additive_attack_ramps_up_from_silence():
    src = AdditiveDroneSource(44100, seed=1)
    assignment = _assignment()
    timbre = calibrate_color(0.03, 0.68, 0.94)
    preset = dict(ADDITIVE_PRESETS[0], attack=1.0)  # 1s attack, short enough to observe
    first = src.render(1, assignment, timbre, 1024, preset)
    later = None
    for _ in range(60):
        later = src.render(1, assignment, timbre, 1024, preset)
    assert np.sqrt(np.mean(first ** 2)) < np.sqrt(np.mean(later ** 2))


def test_additive_voice_is_dropped_on_sync():
    src = AdditiveDroneSource(44100, seed=1)
    assignment = _assignment()
    timbre = calibrate_color(0.03, 0.68, 0.94)
    src.render(1, assignment, timbre, 256, ADDITIVE_PRESETS[0])
    assert 1 in src._voices
    src.sync([])
    assert 1 not in src._voices
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soundscape_sources'`.

- [x] **Step 3: Write minimal implementation**

```python
# audio_prototype/soundscape_sources.py
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
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -v`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_sources.py audio_prototype/tests/test_soundscape_sources.py
rtk git commit -m "feat(soundscape): add additive drone source engine"
```

---

## Task 7: Granular Cloud source engine + presets

**Files:**
- Modify: `audio_prototype/soundscape_sources.py`
- Test: `audio_prototype/tests/test_soundscape_sources.py`

**Interfaces:**
- Consumes: `synth_source.SeedBank`, `soundscape_voices.sync_voices`.
- Produces:
  - `GRANULAR_PRESETS: list[dict]` — 5 presets, each `{"id", "grain_ms", "density_hz", "spread_ms"}`.
  - `class GranularCloudSource(samplerate, seed=None)` with `.render(vid, timbre, bpm, frames, preset) -> np.ndarray` and `.sync(active_ids)`.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_soundscape_sources.py
from soundscape_sources import GRANULAR_PRESETS, GranularCloudSource


def test_granular_has_five_presets_with_required_keys():
    assert len(GRANULAR_PRESETS) == 5
    for p in GRANULAR_PRESETS:
        assert {"id", "grain_ms", "density_hz", "spread_ms"} <= set(p)


def test_granular_cloud_is_audible_and_bounded():
    src = GranularCloudSource(44100, seed=2)
    timbre = calibrate_color(0.03, 0.68, 0.94)
    blocks = [src.render(1, timbre, 90.0, 1024, GRANULAR_PRESETS[0]) for _ in range(60)]
    total = np.concatenate(blocks)
    assert total.dtype == np.float64
    assert np.max(np.abs(total)) <= 1.0 + 1e-6
    assert not np.any(np.isnan(total))
    assert float(np.sqrt(np.mean(total ** 2))) > 0.005


def test_granular_cloud_is_deterministic_given_seed():
    timbre = calibrate_color(0.03, 0.68, 0.94)
    a = GranularCloudSource(44100, seed=9)
    b = GranularCloudSource(44100, seed=9)
    out_a = np.concatenate([a.render(1, timbre, 90.0, 512, GRANULAR_PRESETS[1]) for _ in range(20)])
    out_b = np.concatenate([b.render(1, timbre, 90.0, 512, GRANULAR_PRESETS[1]) for _ in range(20)])
    np.testing.assert_array_equal(out_a, out_b)


def test_granular_cloud_voice_dropped_on_sync():
    src = GranularCloudSource(44100, seed=2)
    timbre = calibrate_color(0.03, 0.68, 0.94)
    src.render(1, timbre, 90.0, 256, GRANULAR_PRESETS[0])
    assert 1 in src._voices
    src.sync([])
    assert 1 not in src._voices
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -k granular -v`
Expected: FAIL — `ImportError: cannot import name 'GranularCloudSource'`.

- [x] **Step 3: Write minimal implementation**

```python
# append to audio_prototype/soundscape_sources.py

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
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -v`
Expected: PASS (8 tests total).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_sources.py audio_prototype/tests/test_soundscape_sources.py
rtk git commit -m "feat(soundscape): add granular cloud source engine"
```

---

## Task 8: Resonant Pulse source engine + presets

**Files:**
- Modify: `audio_prototype/soundscape_sources.py`
- Test: `audio_prototype/tests/test_soundscape_sources.py`

**Interfaces:**
- Consumes: `soundscape_harmony.midi_to_hz`, `soundscape_voices.sync_voices`.
- Produces:
  - `RESONANT_PRESETS: list[dict]` — 5 presets, each `{"id", "interval_semitones": tuple[int,...], "decay", "excite_gain"}`.
  - `class ResonantPulseSource(samplerate, seed=None)` with `.render(vid, assignment, bpm, frames, preset) -> np.ndarray` and `.sync(active_ids)`.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_soundscape_sources.py
from soundscape_sources import RESONANT_PRESETS, ResonantPulseSource


def test_resonant_has_five_presets_with_required_keys():
    assert len(RESONANT_PRESETS) == 5
    for p in RESONANT_PRESETS:
        assert {"id", "interval_semitones", "decay", "excite_gain"} <= set(p)
        assert 0.0 < p["decay"] < 1.0


def test_resonant_pulse_is_audible_bounded_and_stable():
    src = ResonantPulseSource(44100, seed=3)
    assignment = _assignment()
    blocks = [src.render(1, assignment, 90.0, 1024, RESONANT_PRESETS[1]) for _ in range(80)]
    total = np.concatenate(blocks)
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-3
    assert float(np.sqrt(np.mean(total ** 2))) > 0.01


def test_resonant_pulse_is_deterministic_given_seed():
    assignment = _assignment()
    a = ResonantPulseSource(44100, seed=5)
    b = ResonantPulseSource(44100, seed=5)
    out_a = np.concatenate([a.render(1, assignment, 100.0, 512, RESONANT_PRESETS[0]) for _ in range(10)])
    out_b = np.concatenate([b.render(1, assignment, 100.0, 512, RESONANT_PRESETS[0]) for _ in range(10)])
    np.testing.assert_array_equal(out_a, out_b)


def test_resonant_pulse_voice_dropped_on_sync():
    src = ResonantPulseSource(44100, seed=3)
    assignment = _assignment()
    src.render(1, assignment, 90.0, 256, RESONANT_PRESETS[0])
    assert 1 in src._voices
    src.sync([])
    assert 1 not in src._voices
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -k resonant -v`
Expected: FAIL — `ImportError: cannot import name 'ResonantPulseSource'`.

- [x] **Step 3: Write minimal implementation**

```python
# append to audio_prototype/soundscape_sources.py

RESONANT_PRESETS = [
    {"id": "resonant_1", "interval_semitones": (0,), "decay": 0.9975, "excite_gain": 0.6},
    {"id": "resonant_2", "interval_semitones": (0, 7), "decay": 0.997, "excite_gain": 0.55},
    {"id": "resonant_3", "interval_semitones": (7, 2), "decay": 0.995, "excite_gain": 0.5},
    {"id": "resonant_4", "interval_semitones": (0, 7, 10), "decay": 0.993, "excite_gain": 0.45},
    {"id": "resonant_5", "interval_semitones": (0,), "decay": 0.999, "excite_gain": 0.7},
]


class ResonantPulseSource:
    """Modal resonator bank excited by sparse BPM-derived impulses (spec 7
    row 2, 16.3.6 'pulse without conventional drums'). Each resonator is a
    damped 2nd-order recursive oscillator (numpy-only, no scipy) tuned to
    the voice's allocated pitch plus fixed intervals above it. Runs a
    per-sample Python loop -- acceptable for Phase 1's desktop-only,
    ~8-voice budget; revisit before any browser/Pyodide port."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._voices = {}
        self._rng_seed = seed

    def render(self, vid, assignment, bpm, frames, preset):
        intervals = preset["interval_semitones"]
        n_res = len(intervals)
        voice = self._voices.get(vid)
        if voice is None:
            rng_seed = None if self._rng_seed is None else self._rng_seed + int(vid) * 131
            voice = {
                "rng": np.random.default_rng(rng_seed),
                "next_pulse": 0,
                "y1": np.zeros(n_res),
                "y2": np.zeros(n_res),
            }
            self._voices[vid] = voice
        freqs = np.array([midi_to_hz(assignment.midi + s) for s in intervals])
        w = 2.0 * np.pi * freqs / self.samplerate
        decay = preset["decay"]
        a1 = 2.0 * decay * np.cos(w)
        a2 = -(decay ** 2)

        pulse_interval = max(1, int(self.samplerate * 60.0 / max(20.0, bpm)))
        out = np.zeros(frames, dtype=np.float64)
        y1, y2 = voice["y1"], voice["y2"]
        rng = voice["rng"]
        next_pulse = voice["next_pulse"]
        for i in range(frames):
            excite = 0.0
            if next_pulse <= 0:
                excite = preset["excite_gain"] * float(rng.uniform(0.6, 1.0))
                next_pulse = pulse_interval
            next_pulse -= 1
            y0 = a1 * y1 + a2 * y2 + excite
            out[i] = np.sum(y0) / n_res
            y2 = y1
            y1 = y0
        voice["y1"], voice["y2"], voice["next_pulse"] = y1, y2, next_pulse
        return out

    def sync(self, active_ids):
        sync_voices(self._voices, active_ids)
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -v`
Expected: PASS (12 tests total).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_sources.py audio_prototype/tests/test_soundscape_sources.py
rtk git commit -m "feat(soundscape): add resonant pulse source engine"
```

---

## Task 9: Filtered Noise source engine + presets

**Files:**
- Modify: `audio_prototype/soundscape_sources.py`
- Test: `audio_prototype/tests/test_soundscape_sources.py`

**Interfaces:**
- Consumes: `soundscape_voices.sync_voices`.
- Produces:
  - `NOISE_PRESETS: list[dict]` — 5 presets, each `{"id", "tilt", "gain"}`.
  - `class FilteredNoiseSource(samplerate, seed=None)` with `.render(vid, timbre, frames, preset) -> np.ndarray` and `.sync(active_ids)`.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_soundscape_sources.py
from soundscape_sources import NOISE_PRESETS, FilteredNoiseSource


def _hf_ratio(x):
    mag = np.abs(np.fft.rfft(x))
    return float(np.sum(mag[len(mag) // 2:]) / (np.sum(mag) + 1e-12))


def test_noise_has_five_presets_with_required_keys():
    assert len(NOISE_PRESETS) == 5
    for p in NOISE_PRESETS:
        assert {"id", "tilt", "gain"} <= set(p)


def test_dark_preset_is_less_bright_than_bright_preset():
    src = FilteredNoiseSource(44100, seed=4)
    timbre = calibrate_color(0.0, 0.68, 0.94)
    dark = np.concatenate([src.render(1, timbre, 2048, {"id": "d", "tilt": -0.8, "gain": 1.0}) for _ in range(10)])
    bright = np.concatenate([src.render(2, timbre, 2048, {"id": "b", "tilt": 0.8, "gain": 1.0}) for _ in range(10)])
    assert _hf_ratio(bright) > _hf_ratio(dark)


def test_noise_output_is_bounded_and_nan_free():
    src = FilteredNoiseSource(44100, seed=4)
    timbre = calibrate_color(0.03, 0.68, 0.94)
    total = np.concatenate([src.render(1, timbre, 1024, NOISE_PRESETS[i % 5]) for i in range(40)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-6


def test_noise_voice_dropped_on_sync():
    src = FilteredNoiseSource(44100, seed=4)
    timbre = calibrate_color(0.03, 0.68, 0.94)
    src.render(1, timbre, 256, NOISE_PRESETS[0])
    assert 1 in src._voices
    src.sync([])
    assert 1 not in src._voices
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -k noise -v`
Expected: FAIL — `ImportError: cannot import name 'FilteredNoiseSource'`.

- [x] **Step 3: Write minimal implementation**

```python
# append to audio_prototype/soundscape_sources.py

NOISE_PRESETS = [
    {"id": "noise_1", "tilt": -0.6, "gain": 0.35},   # breath / air texture, darker
    {"id": "noise_2", "tilt": 0.1, "gain": 0.4},      # water-like filtered noise
    {"id": "noise_3", "tilt": 0.4, "gain": 0.3},      # wind model
    {"id": "noise_4", "tilt": -0.3, "gain": 0.2},     # distant room tone
    {"id": "noise_5", "tilt": 0.0, "gain": 0.3},      # broadband noise, flat tilt
]


class FilteredNoiseSource:
    """Warmth-shaped filtered noise (spec 7 row 5, 5.2). tilt<0 mixes toward
    a one-pole-lowpassed signal (darker); tilt>0 toward the highpassed
    complement (brighter). A slow sine 'breathing' envelope avoids static
    full-volume sustain (spec 9.6)."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._voices = {}
        self._rng_seed = seed

    def render(self, vid, timbre, frames, preset):
        voice = self._voices.get(vid)
        if voice is None:
            rng_seed = None if self._rng_seed is None else self._rng_seed + int(vid) * 149
            voice = {"rng": np.random.default_rng(rng_seed), "lp_state": 0.0}
            self._voices[vid] = voice
        rng = voice["rng"]
        noise = rng.uniform(-1.0, 1.0, size=frames)
        tilt = float(np.clip(preset["tilt"] + 0.4 * (timbre["warmth"] - 0.5), -1.0, 1.0))
        coeff = float(np.clip(0.9 - 0.4 * abs(tilt), 0.3, 0.98))
        lowpassed = np.empty(frames, dtype=np.float64)
        state = voice["lp_state"]
        for i in range(frames):
            state = coeff * state + (1.0 - coeff) * noise[i]
            lowpassed[i] = state
        voice["lp_state"] = state
        shaped = lowpassed if tilt <= 0 else (noise - lowpassed)
        t = np.arange(frames, dtype=np.float64) / self.samplerate
        breathing = 0.6 + 0.4 * np.sin(2.0 * np.pi * 0.05 * t + vid)
        return shaped * preset["gain"] * breathing

    def sync(self, active_ids):
        sync_voices(self._voices, active_ids)
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -v`
Expected: PASS (16 tests total).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_sources.py audio_prototype/tests/test_soundscape_sources.py
rtk git commit -m "feat(soundscape): add filtered noise source engine"
```

---

## Task 10: Sample Texture source engine + presets

**Files:**
- Modify: `audio_prototype/soundscape_sources.py`
- Test: `audio_prototype/tests/test_soundscape_sources.py`

**Interfaces:**
- Consumes: numpy only (self-contained; does not depend on `synth_source`'s sample-loading code, which belongs to the sample-backed synth mode this plan does not touch).
- Produces:
  - `TEXTURE_PRESETS: list[dict]` — 5 presets, each `{"id", "window_ms", "drift_ms", "freeze": bool, ["reverse": bool]}`.
  - `class SampleTextureSource(samplerate, seed=None)` with `.load_sample(samples)`, `.render(vid, frames, preset) -> np.ndarray`, `.sync(active_ids)`. Ships with a generated placeholder texture so it's audible with no file loaded.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_soundscape_sources.py
from soundscape_sources import TEXTURE_PRESETS, SampleTextureSource


def test_texture_has_five_presets_with_required_keys():
    assert len(TEXTURE_PRESETS) == 5
    for p in TEXTURE_PRESETS:
        assert {"id", "window_ms", "drift_ms", "freeze"} <= set(p)


def test_texture_is_audible_bounded_and_nan_free_with_placeholder():
    src = SampleTextureSource(44100, seed=6)
    total = np.concatenate([src.render(1, 1024, TEXTURE_PRESETS[0]) for _ in range(60)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-6
    assert float(np.sqrt(np.mean(total ** 2))) > 0.005


def test_freeze_preset_barely_moves_the_read_window():
    src = SampleTextureSource(44100, seed=6)
    freeze_preset = dict(TEXTURE_PRESETS[0], freeze=True)
    src.render(1, 1024, freeze_preset)
    pos_before = src._voices[1]["pos"]
    for _ in range(20):
        src.render(1, 1024, freeze_preset)
    assert src._voices[1]["pos"] == pos_before


def test_non_freeze_preset_advances_the_read_window():
    src = SampleTextureSource(44100, seed=6)
    preset = next(p for p in TEXTURE_PRESETS if not p["freeze"])
    src.render(1, 1024, preset)
    pos_before = src._voices[1]["pos"]
    for _ in range(20):
        src.render(1, 1024, preset)
    assert src._voices[1]["pos"] != pos_before


def test_load_sample_changes_the_output():
    src_a = SampleTextureSource(44100, seed=6)
    src_b = SampleTextureSource(44100, seed=6)
    src_b.load_sample(np.sin(2 * np.pi * 440 * np.arange(44100 * 3) / 44100))
    out_a = np.concatenate([src_a.render(1, 1024, TEXTURE_PRESETS[0]) for _ in range(20)])
    out_b = np.concatenate([src_b.render(1, 1024, TEXTURE_PRESETS[0]) for _ in range(20)])
    assert not np.allclose(out_a, out_b)


def test_texture_voice_dropped_on_sync():
    src = SampleTextureSource(44100, seed=6)
    src.render(1, 256, TEXTURE_PRESETS[0])
    assert 1 in src._voices
    src.sync([])
    assert 1 not in src._voices
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -k texture -v`
Expected: FAIL — `ImportError: cannot import name 'SampleTextureSource'`.

- [x] **Step 3: Write minimal implementation**

```python
# append to audio_prototype/soundscape_sources.py

TEXTURE_PRESETS = [
    {"id": "texture_1", "window_ms": 400, "drift_ms": 200, "freeze": False},
    {"id": "texture_2", "window_ms": 250, "drift_ms": 600, "freeze": False},
    {"id": "texture_3", "window_ms": 180, "drift_ms": 50, "freeze": True},
    {"id": "texture_4", "window_ms": 300, "drift_ms": 300, "freeze": False, "reverse": True},
    {"id": "texture_5", "window_ms": 500, "drift_ms": 900, "freeze": False},
]


class SampleTextureSource:
    """Windowed playback of a loaded (or generated placeholder) sample,
    spec 7 row 3 / 16.3.2 'granular memory' / 20 Scene E. The read window
    drifts slowly through the buffer; 'freeze' presets stop it, 'reverse'
    plays the window backwards."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._rng = np.random.default_rng(seed)
        self._buffer = self._default_texture()
        self._voices = {}

    def _default_texture(self, seconds=6.0):
        n = int(seconds * self.samplerate)
        noise = self._rng.uniform(-1.0, 1.0, size=n)
        state = 0.0
        out = np.empty(n)
        for i in range(n):
            state = 0.995 * state + 0.005 * noise[i]
            out[i] = state
        peak = np.max(np.abs(out))
        return (out / peak if peak > 1e-9 else out).astype(np.float64)

    def load_sample(self, samples):
        buf = np.asarray(samples, dtype=np.float64)
        if buf.ndim > 1:
            buf = buf.mean(axis=1)
        self._buffer = buf

    def render(self, vid, frames, preset):
        voice = self._voices.get(vid)
        if voice is None:
            voice = {"pos": 0.0}
            self._voices[vid] = voice
        buf = self._buffer
        n = len(buf)
        window_len = max(64, min(n, int(preset["window_ms"] * 0.001 * self.samplerate)))
        span = max(1, n - window_len)
        if preset["freeze"]:
            speed = 0.0
        else:
            speed = window_len / max(0.05, preset["drift_ms"] / 1000.0)   # samples/sec
        voice["pos"] = (voice["pos"] + speed * frames / self.samplerate) % span
        start = int(voice["pos"])
        segment = buf[start:start + window_len]
        if preset.get("reverse"):
            segment = segment[::-1]
        env = np.hanning(len(segment)) if len(segment) > 4 else np.ones(len(segment))
        segment = segment * env
        reps = int(np.ceil(frames / max(1, len(segment))))
        return np.tile(segment, reps)[:frames].astype(np.float64)

    def sync(self, active_ids):
        sync_voices(self._voices, active_ids)
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -v`
Expected: PASS (22 tests total).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_sources.py audio_prototype/tests/test_soundscape_sources.py
rtk git commit -m "feat(soundscape): add sample texture source engine"
```

---

## Task 11: `SourceBank` — 25-preset registry and dispatch

**Files:**
- Modify: `audio_prototype/soundscape_sources.py`
- Test: `audio_prototype/tests/test_soundscape_sources.py`

**Interfaces:**
- Consumes: `AdditiveDroneSource`, `GranularCloudSource`, `ResonantPulseSource`, `FilteredNoiseSource`, `SampleTextureSource` (Tasks 6-10), `soundscape_color.calibrate_color`.
- Produces:
  - `SOURCE_PRESETS: list[dict]` — all 25 presets, each with an added `"engine"` key.
  - `class SourceBank(samplerate, seed=None)` with `.preset(preset_id) -> dict`, `.render(vid, preset_id, assignment, hue, sat, val, bpm, frames) -> np.ndarray`, `.sync(active_ids)`.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_soundscape_sources.py
from soundscape_sources import SOURCE_PRESETS, SourceBank


def test_source_presets_has_exactly_25_unique_ids():
    assert len(SOURCE_PRESETS) == 25
    assert len({p["id"] for p in SOURCE_PRESETS}) == 25


def test_source_bank_renders_every_preset_without_error():
    bank = SourceBank(44100, seed=7)
    assignment = _assignment()
    for preset in SOURCE_PRESETS:
        out = bank.render(1, preset["id"], assignment, 0.03, 0.68, 0.94, 90.0, 512)
        assert out.shape == (512,)
        assert not np.any(np.isnan(out))
        bank.sync([])  # reset voice state between presets sharing id 1


def test_source_bank_sync_clears_all_engines():
    bank = SourceBank(44100, seed=7)
    assignment = _assignment()
    bank.render(1, "additive_1", assignment, 0.03, 0.68, 0.94, 90.0, 256)
    bank.render(1, "granular_1", assignment, 0.03, 0.68, 0.94, 90.0, 256)
    bank.sync([])
    assert bank.additive._voices == {}
    assert bank.granular._voices == {}
    assert bank.resonant._voices == {}
    assert bank.noise._voices == {}
    assert bank.texture._voices == {}


def test_source_bank_unknown_preset_raises():
    bank = SourceBank(44100, seed=7)
    try:
        bank.preset("not_a_real_preset")
        assert False, "expected KeyError"
    except KeyError:
        pass
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -k source_bank -v`
Expected: FAIL — `ImportError: cannot import name 'SourceBank'`.

- [x] **Step 3: Write minimal implementation**

```python
# append to audio_prototype/soundscape_sources.py

from soundscape_color import calibrate_color  # noqa: E402  (keep near other imports if preferred)

SOURCE_PRESETS = []
for _engine_name, _presets in (
    ("additive", ADDITIVE_PRESETS),
    ("granular", GRANULAR_PRESETS),
    ("resonant", RESONANT_PRESETS),
    ("noise", NOISE_PRESETS),
    ("texture", TEXTURE_PRESETS),
):
    for _p in _presets:
        SOURCE_PRESETS.append({**_p, "engine": _engine_name})


class SourceBank:
    """Owns one instance of each of the 5 source engines and dispatches a
    layer's render() call to the engine named by its preset (spec 7, 12)."""

    def __init__(self, samplerate, seed=None):
        self.additive = AdditiveDroneSource(samplerate, seed=seed)
        self.granular = GranularCloudSource(samplerate, seed=seed)
        self.resonant = ResonantPulseSource(samplerate, seed=seed)
        self.noise = FilteredNoiseSource(samplerate, seed=seed)
        self.texture = SampleTextureSource(samplerate, seed=seed)
        self._by_id = {p["id"]: p for p in SOURCE_PRESETS}

    def preset(self, preset_id):
        return self._by_id[preset_id]

    def render(self, vid, preset_id, assignment, hue, sat, val, bpm, frames):
        preset = self.preset(preset_id)
        timbre = calibrate_color(hue, sat, val)
        engine = preset["engine"]
        if engine == "additive":
            return self.additive.render(vid, assignment, timbre, frames, preset)
        if engine == "granular":
            return self.granular.render(vid, timbre, bpm, frames, preset)
        if engine == "resonant":
            return self.resonant.render(vid, assignment, bpm, frames, preset)
        if engine == "noise":
            return self.noise.render(vid, timbre, frames, preset)
        if engine == "texture":
            return self.texture.render(vid, frames, preset)
        raise ValueError(f"unknown source engine {engine!r}")

    def sync(self, active_ids):
        self.additive.sync(active_ids)
        self.granular.sync(active_ids)
        self.resonant.sync(active_ids)
        self.noise.sync(active_ids)
        self.texture.sync(active_ids)
```

Move the `from soundscape_color import calibrate_color` line up to the top import block instead of leaving it mid-file — the snippet places it there only to show where it's newly needed relative to earlier tasks.

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_sources.py -v`
Expected: PASS (26 tests total).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_sources.py audio_prototype/tests/test_soundscape_sources.py
rtk git commit -m "feat(soundscape): add SourceBank 25-preset registry and dispatch"
```

---

## Task 12: Delay + Spectral transform engines + presets

**Files:**
- Create: `audio_prototype/soundscape_transforms.py`
- Test: `audio_prototype/tests/test_soundscape_transforms.py`

**Interfaces:**
- Consumes: `soundscape_voices.sync_voices`, `spectral_stretch.SpectralSmear` (existing, reused unmodified).
- Produces:
  - `DELAY_PRESETS: list[dict]` — 5 presets, each `{"id", "subdivision", "feedback", "reverse"}` (BPM-synced tap per spec §5.5/§10.2).
  - `class DelayTransform(samplerate)` with `.render(vid, x, bpm, preset) -> np.ndarray`, `.sync(active_ids)`.
  - `SPECTRAL_PRESETS: list[dict]` — 5 presets, each `{"id", "suspension", "smear"}`.
  - `class SpectralTransform(samplerate, seed=None)` with `.render(vid, x, preset) -> np.ndarray`, `.sync(active_ids)` — reuses `SpectralSmear` per-voice instead of reimplementing an STFT.

- [x] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_soundscape_transforms.py
import numpy as np

from soundscape_transforms import DELAY_PRESETS, DelayTransform, SPECTRAL_PRESETS, SpectralTransform


def _click_train(frames, period, samplerate=44100):
    x = np.zeros(frames)
    x[::period] = 1.0
    return x


def test_delay_has_five_presets_with_required_keys():
    assert len(DELAY_PRESETS) == 5
    for p in DELAY_PRESETS:
        assert {"id", "subdivision", "feedback", "reverse"} <= set(p)


def test_delay_produces_a_later_echo_of_a_click():
    fx = DelayTransform(44100)
    x = np.zeros(4096)
    x[10] = 1.0
    out = fx.render(1, x, bpm=120.0, preset=dict(DELAY_PRESETS[1], reverse=False))
    assert not np.any(np.isnan(out))
    # some later sample should be non-zero due to the fed-back click
    assert np.max(np.abs(out[100:])) > 0.0


def test_delay_feedback_keeps_output_bounded_over_many_blocks():
    fx = DelayTransform(44100)
    rng = np.random.default_rng(1)
    total = []
    for _ in range(60):
        x = rng.uniform(-0.2, 0.2, size=1024)
        total.append(fx.render(1, x, bpm=100.0, preset=DELAY_PRESETS[3]))
    total = np.concatenate(total)
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) < 5.0


def test_delay_voice_dropped_on_sync():
    fx = DelayTransform(44100)
    fx.render(1, np.zeros(256), 100.0, DELAY_PRESETS[0])
    assert 1 in fx._voices
    fx.sync([])
    assert 1 not in fx._voices


def test_spectral_has_five_presets_with_required_keys():
    assert len(SPECTRAL_PRESETS) == 5
    for p in SPECTRAL_PRESETS:
        assert {"id", "suspension", "smear"} <= set(p)


def test_spectral_transform_returns_same_length_and_is_bounded():
    fx = SpectralTransform(44100, seed=2)
    rng = np.random.default_rng(0)
    for preset in SPECTRAL_PRESETS:
        x = rng.uniform(-0.3, 0.3, size=512)
        out = fx.render(1, x, preset)
        assert out.shape == (512,)
        assert not np.any(np.isnan(out))
        assert np.max(np.abs(out)) < 5.0


def test_spectral_transform_voice_dropped_on_sync():
    fx = SpectralTransform(44100, seed=2)
    fx.render(1, np.zeros(256), SPECTRAL_PRESETS[0])
    assert 1 in fx._voices
    fx.sync([])
    assert 1 not in fx._voices
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_transforms.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soundscape_transforms'`.

- [x] **Step 3: Write minimal implementation**

```python
# audio_prototype/soundscape_transforms.py
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
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_transforms.py -v`
Expected: PASS (7 tests).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_transforms.py audio_prototype/tests/test_soundscape_transforms.py
rtk git commit -m "feat(soundscape): add delay and spectral transform engines"
```

---

## Task 13: Pitch/Resonance + Granular transform engines + presets

**Files:**
- Modify: `audio_prototype/soundscape_transforms.py`
- Test: `audio_prototype/tests/test_soundscape_transforms.py`

**Interfaces:**
- Consumes: `soundscape_voices.sync_voices`.
- Produces:
  - `PITCH_PRESETS: list[dict]` — 5 presets, each `{"id", "semitones", "mix", ["drift_cents"]}`.
  - `class PitchResonanceTransform(samplerate, seed=None)` with `.render(vid, x, preset) -> np.ndarray`, `.sync(active_ids)`.
  - `GRAINFX_PRESETS: list[dict]` — 5 presets covering granulation/ring-mod/AM/wavefold/saturation.
  - `class GranularTransform(samplerate, seed=None)` with `.render(vid, x, preset) -> np.ndarray`, `.sync(active_ids)`.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_soundscape_transforms.py
from soundscape_transforms import GRAINFX_PRESETS, PITCH_PRESETS, GranularTransform, PitchResonanceTransform


def test_pitch_has_five_presets_with_required_keys():
    assert len(PITCH_PRESETS) == 5
    for p in PITCH_PRESETS:
        assert {"id", "semitones", "mix"} <= set(p)


def test_pitch_transform_is_bounded_and_nan_free():
    fx = PitchResonanceTransform(44100, seed=3)
    rng = np.random.default_rng(0)
    x = rng.uniform(-0.4, 0.4, size=1024)
    for preset in PITCH_PRESETS:
        out = fx.render(1, x, preset)
        assert out.shape == (1024,)
        assert not np.any(np.isnan(out))
        assert np.max(np.abs(out)) < 5.0


def test_sub_octave_preset_differs_from_dry_signal():
    fx = PitchResonanceTransform(44100, seed=3)
    x = np.sin(2 * np.pi * 220 * np.arange(1024) / 44100)
    out = fx.render(1, x, PITCH_PRESETS[0])
    assert not np.allclose(out, x)


def test_pitch_voice_dropped_on_sync():
    fx = PitchResonanceTransform(44100, seed=3)
    fx.render(1, np.zeros(256), PITCH_PRESETS[0])
    assert 1 in fx._voices
    fx.sync([])
    assert 1 not in fx._voices


def test_grainfx_has_five_presets_with_required_keys():
    assert len(GRAINFX_PRESETS) == 5
    for p in GRAINFX_PRESETS:
        assert "id" in p and "kind" in p


def test_grainfx_presets_are_bounded_and_differ_from_dry():
    fx = GranularTransform(44100, seed=4)
    x = np.sin(2 * np.pi * 220 * np.arange(2048) / 44100) * 0.5
    for preset in GRAINFX_PRESETS:
        out = fx.render(1, x.copy(), preset)
        assert out.shape == (2048,)
        assert not np.any(np.isnan(out))
        assert np.max(np.abs(out)) < 5.0
        if preset["kind"] != "granulate":
            assert not np.allclose(out, x)


def test_grainfx_voice_dropped_on_sync():
    fx = GranularTransform(44100, seed=4)
    fx.render(1, np.zeros(256), GRAINFX_PRESETS[1])
    assert 1 in fx._voices
    fx.sync([])
    assert 1 not in fx._voices
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_transforms.py -k "pitch or grainfx" -v`
Expected: FAIL — `ImportError: cannot import name 'PitchResonanceTransform'`.

- [x] **Step 3: Write minimal implementation**

```python
# append to audio_prototype/soundscape_transforms.py

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
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_transforms.py -v`
Expected: PASS (14 tests total).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_transforms.py audio_prototype/tests/test_soundscape_transforms.py
rtk git commit -m "feat(soundscape): add pitch/resonance and granular-fx transform engines"
```

---

## Task 14: Spatial Diffusion transform + `TransformBank` registry

**Files:**
- Modify: `audio_prototype/soundscape_transforms.py`
- Test: `audio_prototype/tests/test_soundscape_transforms.py`

**Interfaces:**
- Consumes: `reverb.SchroederReverb` (existing, reused unmodified), `DelayTransform`/`SpectralTransform`/`PitchResonanceTransform`/`GranularTransform` (Tasks 12-13).
- Produces:
  - `SPATIAL_PRESETS: list[dict]` — 5 presets covering short room / large reverb / rotate / distance / diffuse-send.
  - `class SpatialDiffusionTransform(samplerate)` with `.render(vid, x, preset) -> np.ndarray`, `.sync(active_ids)`. `"rotate"`/`"diffuse_send"` presets pass the mono signal through unchanged — actual stereo panning and the shared diffusion bus are engine-level concerns handled in Task 15.
  - `TRANSFORM_PRESETS: list[dict]` — all 25 presets with an added `"engine"` key.
  - `class TransformBank(samplerate, seed=None)` with `.preset(preset_id)`, `.render(vid, preset_id, x, bpm) -> np.ndarray`, `.sync(active_ids)`.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_soundscape_transforms.py
from soundscape_transforms import SPATIAL_PRESETS, TRANSFORM_PRESETS, SpatialDiffusionTransform, TransformBank


def test_spatial_has_five_presets_with_required_keys():
    assert len(SPATIAL_PRESETS) == 5
    for p in SPATIAL_PRESETS:
        assert "id" in p and "kind" in p


def test_spatial_reverb_preset_adds_tail_energy():
    fx = SpatialDiffusionTransform(44100)
    reverb_preset = next(p for p in SPATIAL_PRESETS if p["kind"] == "reverb")
    x = np.zeros(4096)
    x[0] = 1.0
    out = fx.render(1, x, reverb_preset)
    assert not np.any(np.isnan(out))
    assert float(np.sqrt(np.mean(out[1000:] ** 2))) > 0.0


def test_spatial_distance_preset_is_bounded():
    fx = SpatialDiffusionTransform(44100)
    distance_preset = next(p for p in SPATIAL_PRESETS if p["kind"] == "distance")
    rng = np.random.default_rng(0)
    out = fx.render(1, rng.uniform(-0.5, 0.5, size=1024), distance_preset)
    assert not np.any(np.isnan(out))
    assert np.max(np.abs(out)) < 5.0


def test_spatial_voice_dropped_on_sync():
    fx = SpatialDiffusionTransform(44100)
    fx.render(1, np.zeros(256), SPATIAL_PRESETS[0])
    assert 1 in fx._voices
    fx.sync([])
    assert 1 not in fx._voices


def test_transform_presets_has_exactly_25_unique_ids():
    assert len(TRANSFORM_PRESETS) == 25
    assert len({p["id"] for p in TRANSFORM_PRESETS}) == 25


def test_transform_bank_renders_every_preset_without_error():
    bank = TransformBank(44100, seed=8)
    for preset in TRANSFORM_PRESETS:
        out = bank.render(1, preset["id"], np.zeros(512), 100.0)
        assert out.shape == (512,)
        assert not np.any(np.isnan(out))
        bank.sync([])
```

- [x] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_transforms.py -k "spatial or transform_bank or TRANSFORM_PRESETS" -v`
Expected: FAIL — `ImportError: cannot import name 'SpatialDiffusionTransform'`.

- [x] **Step 3: Write minimal implementation**

```python
# append to audio_prototype/soundscape_transforms.py

from reverb import SchroederReverb  # noqa: E402  (place with other imports at top of file)

SPATIAL_PRESETS = [
    {"id": "spatial_1", "kind": "reverb", "reverb_style": "bright_room", "size": 0.25, "send": 0.3},
    {"id": "spatial_2", "kind": "reverb", "reverb_style": "wash", "size": 0.8, "send": 0.6},
    {"id": "spatial_3", "kind": "rotate", "rate_hz": 0.15, "depth": 0.7},
    {"id": "spatial_4", "kind": "distance", "cutoff_mix": 0.7, "gain": 0.5},
    {"id": "spatial_5", "kind": "diffuse_send", "send": 0.8},
]


class SpatialDiffusionTransform:
    """Space family (spec 8 row 5): short/large reverb via the existing
    SchroederReverb, distance via a one-pole lowpass + gain. 'rotate' and
    'diffuse_send' return the mono signal unchanged here -- stereo pan LFO
    and the shared background-field send are applied by SoundscapeEngine,
    which is where panning/bus-mixing already lives (Task 15)."""

    def __init__(self, samplerate):
        self.samplerate = samplerate
        self._voices = {}

    def render(self, vid, x, preset):
        voice = self._voices.get(vid)
        if voice is None:
            voice = {"reverb": None, "lp_state": 0.0}
            self._voices[vid] = voice
        frames = len(x)
        kind = preset["kind"]
        if kind == "reverb":
            if voice["reverb"] is None:
                voice["reverb"] = SchroederReverb(self.samplerate)
                voice["reverb"].set_space(style=preset["reverb_style"], size=preset["size"], diffusion=0.6)
            wet = np.asarray(voice["reverb"].process(x), dtype=np.float64)
            return x * (1.0 - preset["send"]) + wet * preset["send"]
        if kind == "distance":
            coeff = 0.6 + 0.3 * preset["cutoff_mix"]
            out = np.empty(frames, dtype=np.float64)
            state = voice["lp_state"]
            for i in range(frames):
                state = coeff * state + (1.0 - coeff) * x[i]
                out[i] = state
            voice["lp_state"] = state
            return out * preset["gain"]
        if kind in ("rotate", "diffuse_send"):
            return x
        raise ValueError(f"unknown spatial-transform kind {kind!r}")

    def sync(self, active_ids):
        sync_voices(self._voices, active_ids)


TRANSFORM_PRESETS = []
for _engine_name, _presets in (
    ("delay", DELAY_PRESETS),
    ("spectral", SPECTRAL_PRESETS),
    ("pitch", PITCH_PRESETS),
    ("grainfx", GRAINFX_PRESETS),
    ("spatial", SPATIAL_PRESETS),
):
    for _p in _presets:
        TRANSFORM_PRESETS.append({**_p, "engine": _engine_name})


class TransformBank:
    def __init__(self, samplerate, seed=None):
        self.delay = DelayTransform(samplerate)
        self.spectral = SpectralTransform(samplerate, seed=seed)
        self.pitch = PitchResonanceTransform(samplerate, seed=seed)
        self.grainfx = GranularTransform(samplerate, seed=seed)
        self.spatial = SpatialDiffusionTransform(samplerate)
        self._by_id = {p["id"]: p for p in TRANSFORM_PRESETS}

    def preset(self, preset_id):
        return self._by_id[preset_id]

    def render(self, vid, preset_id, x, bpm):
        preset = self.preset(preset_id)
        engine = preset["engine"]
        if engine == "delay":
            return self.delay.render(vid, x, bpm, preset)
        if engine == "spectral":
            return self.spectral.render(vid, x, preset)
        if engine == "pitch":
            return self.pitch.render(vid, x, preset)
        if engine == "grainfx":
            return self.grainfx.render(vid, x, preset)
        if engine == "spatial":
            return self.spatial.render(vid, x, preset)
        raise ValueError(f"unknown transform engine {engine!r}")

    def sync(self, active_ids):
        self.delay.sync(active_ids)
        self.spectral.sync(active_ids)
        self.pitch.sync(active_ids)
        self.grainfx.sync(active_ids)
        self.spatial.sync(active_ids)
```

- [x] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_transforms.py -v`
Expected: PASS (20 tests total).

- [x] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_transforms.py audio_prototype/tests/test_soundscape_transforms.py
rtk git commit -m "feat(soundscape): add spatial diffusion transform and TransformBank registry"
```

---

## Task 15: `SoundscapeEngine` orchestration

**Files:**
- Create: `audio_prototype/soundscape_engine.py`
- Test: `audio_prototype/tests/test_soundscape_engine.py`

**Interfaces:**
- Consumes: `modulation.RmsLimiter`/`soft_clip` (existing), `soundscape_density.DensityGainSmoother/ROLE_GAIN/assign_voice_roles`, `soundscape_harmony.HarmonicField/PitchAllocator`, `soundscape_sources.SourceBank`, `soundscape_transforms.TransformBank`.
- Produces:
  - `class SoundscapePatch(patch_id, hue, sat, val, bpm, source_preset, transform_preset)` — plain data holder.
  - `class SoundscapeEngine(samplerate=44100, seed=None, root_midi=62)` with `.connect_patch(hue, sat, val, bpm, source_preset, transform_preset=None) -> int` (patch id), `.disconnect_patch(pid)`, `.generate_block(frames) -> np.ndarray` (float32, shape `(frames,)`).
  - **Note:** this is a fresh, self-contained patch model — it does not use `LayerRegistry`. The spec's two-matrix (output preset + input preset) topology doesn't fit `LayerRegistry.connect_source`'s single-engine/row/col shape; wiring this into the real patch-bay UI is Phase 2, a separate future plan.

- [ ] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_soundscape_engine.py
import numpy as np

from soundscape_engine import SoundscapeEngine


def test_no_patches_is_silence():
    engine = SoundscapeEngine(samplerate=44100, seed=1)
    block = engine.generate_block(1024)
    assert block.shape == (1024,)
    assert block.dtype == np.float32
    np.testing.assert_allclose(block, np.zeros(1024))


def test_one_patch_is_audible_bounded_and_nan_free():
    engine = SoundscapeEngine(samplerate=44100, seed=1)
    engine.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="additive_2")
    total = np.concatenate([engine.generate_block(1024) for _ in range(80)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-3
    assert float(np.sqrt(np.mean(total[-8192:] ** 2))) > 0.01


def test_disconnect_removes_the_voice():
    engine = SoundscapeEngine(samplerate=44100, seed=1)
    pid = engine.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="noise_2")
    engine.generate_block(512)
    engine.disconnect_patch(pid)
    silent = engine.generate_block(512)
    np.testing.assert_allclose(silent, np.zeros(512))


def test_eight_patches_stay_bounded_and_nan_free():
    engine = SoundscapeEngine(samplerate=44100, seed=2)
    presets = ["additive_1", "granular_2", "resonant_3", "noise_4", "texture_5",
               "additive_5", "resonant_1", "granular_4"]
    for i, preset in enumerate(presets):
        engine.connect_patch(hue=0.01 * i, sat=0.66, val=0.92, bpm=70.0 + 5 * i,
                              source_preset=preset, transform_preset="spatial_1")
    for _ in range(80):
        block = engine.generate_block(1024)
        assert not np.any(np.isnan(block))
        assert np.max(np.abs(block)) <= 1.0 + 1e-3


def test_transform_preset_audibly_changes_the_voice():
    dry = SoundscapeEngine(samplerate=44100, seed=1)
    dry.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="additive_2")
    wet = SoundscapeEngine(samplerate=44100, seed=1)
    wet.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="additive_2",
                       transform_preset="grainfx_5")
    dry_out = np.concatenate([dry.generate_block(1024) for _ in range(20)])
    wet_out = np.concatenate([wet.generate_block(1024) for _ in range(20)])
    assert not np.allclose(dry_out, wet_out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soundscape_engine'`.

- [ ] **Step 3: Write minimal implementation**

```python
# audio_prototype/soundscape_engine.py
"""Top-level orchestration for the Evolving Soundscape Synthesizer, Phase 1
(spec section 11-13). Owns the harmonic pitch allocator, density/priority
state, and the source/transform banks; generate_block() is the per-block
entry point a desktop audio callback or the harness script (Task 16) calls
each buffer."""

import numpy as np

from modulation import RmsLimiter, soft_clip
from soundscape_density import DensityGainSmoother, ROLE_GAIN, assign_voice_roles
from soundscape_harmony import HarmonicField, PitchAllocator
from soundscape_sources import SourceBank
from soundscape_transforms import TransformBank


class SoundscapePatch:
    __slots__ = ("id", "hue", "sat", "val", "bpm", "source_preset", "transform_preset")

    def __init__(self, patch_id, hue, sat, val, bpm, source_preset, transform_preset):
        self.id = patch_id
        self.hue = hue
        self.sat = sat
        self.val = val
        self.bpm = bpm
        self.source_preset = source_preset
        self.transform_preset = transform_preset


class SoundscapeEngine:
    def __init__(self, samplerate=44100, seed=None, root_midi=62):
        self.samplerate = samplerate
        self.field = HarmonicField(root_midi=root_midi)
        self.allocator = PitchAllocator(self.field)
        self.sources = SourceBank(samplerate, seed=seed)
        self.transforms = TransformBank(samplerate, seed=seed)
        self.gain_smoother = DensityGainSmoother()
        self.limiter = RmsLimiter(target_rms=0.3)
        self._patches = {}
        self._assignments = {}
        self._connect_order = []
        self._next_id = 1

    def connect_patch(self, hue, sat, val, bpm, source_preset, transform_preset=None):
        pid = self._next_id
        self._next_id += 1
        self._patches[pid] = SoundscapePatch(pid, hue, sat, val, bpm, source_preset, transform_preset)
        self._connect_order.append(pid)
        return pid

    def disconnect_patch(self, pid):
        self._patches.pop(pid, None)
        self._connect_order = [p for p in self._connect_order if p != pid]
        self.allocator.release(pid)
        self._assignments.pop(pid, None)

    def generate_block(self, frames):
        patches = list(self._patches.values())
        active_ids = [p.id for p in patches]
        self.sources.sync(active_ids)
        self.transforms.sync(active_ids)

        if not patches:
            return np.zeros(frames, dtype=np.float32)

        density = min(1.0, len(patches) / 20.0)
        roles = assign_voice_roles(self._connect_order)
        voice_gain = self.gain_smoother.update(len(patches))

        mix = np.zeros(frames, dtype=np.float64)
        for patch in patches:
            if patch.id not in self._assignments:
                detune_class = "granular" if patch.source_preset.startswith("granular") else "foreground"
                rng = np.random.default_rng(patch.id)
                self._assignments[patch.id] = self.allocator.allocate(patch.id, rng, density, detune_class)
            assignment = self._assignments[patch.id]
            role_gain = ROLE_GAIN[roles.get(patch.id, "dormant")]
            if role_gain <= 0.0:
                continue
            voice = self.sources.render(
                patch.id, patch.source_preset, assignment,
                patch.hue, patch.sat, patch.val, patch.bpm, frames,
            )
            if patch.transform_preset:
                voice = self.transforms.render(patch.id, patch.transform_preset, voice, patch.bpm)
            mix += voice * role_gain * voice_gain

        mixed = self.limiter.process(mix.astype(np.float32))
        return soft_clip(mixed).astype(np.float32)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_engine.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_engine.py audio_prototype/tests/test_soundscape_engine.py
rtk git commit -m "feat(soundscape): add SoundscapeEngine orchestration"
```

---

## Task 16: Simulated-patch playback harness

**Files:**
- Create: `audio_prototype/soundscape_prototype.py`
- Test: `audio_prototype/tests/test_soundscape_prototype.py`

**Interfaces:**
- Consumes: `soundscape_engine.SoundscapeEngine`, `soundscape_sources.SOURCE_PRESETS`, `soundscape_transforms.TRANSFORM_PRESETS`, `modulation.FINGER_HUE_MIN/MAX`/`FINGER_SAT_MIN/MAX`/`FINGER_VAL_MIN/MAX`.
- Produces:
  - `build_patches(engine, count, rng, bpm_min=55.0, bpm_max=130.0)` — connects `count` simulated patches with hue/sat/val drawn from the real finger-scan gamut, cycling through the 25 source and 25 transform presets.
  - `main()` — CLI entry point (`--duration`, `--patches`, `--seed`) that builds patches and plays live via `sounddevice.OutputStream`. This is spec §13 Phase 1's "simulate color and BPM values... support at least eight simultaneous patches" — the deliverable you actually listen to.

- [ ] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_soundscape_prototype.py
import numpy as np

from soundscape_engine import SoundscapeEngine
from soundscape_prototype import build_patches


def test_build_patches_connects_the_requested_count():
    engine = SoundscapeEngine(samplerate=44100, seed=1)
    rng = np.random.default_rng(1)
    build_patches(engine, 8, rng)
    assert len(engine._patches) == 8


def test_eight_simulated_patches_run_headless_without_error():
    engine = SoundscapeEngine(samplerate=44100, seed=1)
    rng = np.random.default_rng(1)
    build_patches(engine, 8, rng)
    total = np.concatenate([engine.generate_block(1024) for _ in range(80)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-3
    assert float(np.sqrt(np.mean(total[-8192:] ** 2))) > 0.005


def test_build_patches_uses_gamut_bounds():
    import modulation as mod

    engine = SoundscapeEngine(samplerate=44100, seed=1)
    rng = np.random.default_rng(1)
    build_patches(engine, 25, rng)
    for patch in engine._patches.values():
        assert mod.FINGER_HUE_MIN <= patch.hue <= mod.FINGER_HUE_MAX
        assert mod.FINGER_SAT_MIN <= patch.sat <= mod.FINGER_SAT_MAX
        assert mod.FINGER_VAL_MIN <= patch.val <= mod.FINGER_VAL_MAX
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_prototype.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soundscape_prototype'`.

- [ ] **Step 3: Write minimal implementation**

```python
# audio_prototype/soundscape_prototype.py
"""Runnable Phase 1 proof-of-concept harness (spec section 13, Phase 1):
simulates ~8 patches with color/BPM drawn from the real finger-scan gamut,
connects them across the 25 source x 25 transform preset grid, and plays
the result live so the design can be tuned by ear.

Run from audio_prototype/:
    rtk python soundscape_prototype.py
    rtk python soundscape_prototype.py --duration 60 --patches 12 --seed 3
"""

import argparse
import time

import numpy as np
import sounddevice as sd

from modulation import (
    FINGER_HUE_MAX,
    FINGER_HUE_MIN,
    FINGER_SAT_MAX,
    FINGER_SAT_MIN,
    FINGER_VAL_MAX,
    FINGER_VAL_MIN,
)
from soundscape_engine import SoundscapeEngine
from soundscape_sources import SOURCE_PRESETS
from soundscape_transforms import TRANSFORM_PRESETS

SAMPLERATE = 44100
BLOCKSIZE = 1024


def build_patches(engine, count, rng, bpm_min=55.0, bpm_max=130.0):
    for i in range(count):
        hue = rng.uniform(FINGER_HUE_MIN, FINGER_HUE_MAX)
        sat = rng.uniform(FINGER_SAT_MIN, FINGER_SAT_MAX)
        val = rng.uniform(FINGER_VAL_MIN, FINGER_VAL_MAX)
        bpm = rng.uniform(bpm_min, bpm_max)
        source_preset = SOURCE_PRESETS[i % len(SOURCE_PRESETS)]["id"]
        transform_preset = TRANSFORM_PRESETS[(i * 3) % len(TRANSFORM_PRESETS)]["id"]
        engine.connect_patch(hue, sat, val, bpm, source_preset, transform_preset)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--patches", type=int, default=8)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    engine = SoundscapeEngine(samplerate=SAMPLERATE, seed=args.seed)
    build_patches(engine, args.patches, rng)

    def callback(outdata, frames, time_info, status):
        block = engine.generate_block(frames)
        outdata[:, 0] = block
        outdata[:, 1] = block

    with sd.OutputStream(samplerate=SAMPLERATE, blocksize=BLOCKSIZE, channels=2, callback=callback):
        print(f"Playing {args.patches} simulated patches for {args.duration:.0f}s (seed={args.seed})...")
        time.sleep(args.duration)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_prototype.py -v`
Expected: PASS (3 tests). (This does not open an audio device — `sounddevice.OutputStream` is only constructed inside `main()`, which the tests don't call.)

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_prototype.py audio_prototype/tests/test_soundscape_prototype.py
rtk git commit -m "feat(soundscape): add simulated-patch playback harness"
```

---

## Task 17: Full-suite verification and brief refresh

**Files:**
- Modify: `RedPole/AGENTS.md:6-12` ("Pick up here")

**Interfaces:** none (verification + docs).

- [ ] **Step 1: Run the complete Python suite**

Run: `rtk python -m pytest tests/ -v` (from `audio_prototype/`)
Expected: PASS — every pre-existing test plus all new `test_soundscape_*.py` files (roughly 90+ new tests). Confirm zero existing tests changed or broke — this plan is purely additive.

- [ ] **Step 2: Listen to Phase 1 by ear**

Run: `rtk python soundscape_prototype.py --duration 90 --patches 8` from `audio_prototype/`.
Expected: audible, evolving, bounded sound with no clipping/underrun errors from `sounddevice`. This is the point to start the "tune by ear" pass (preset parameters, register limits, gain curves) — expected to sound rough on the first listen; capture notes on what to adjust rather than tuning inline here.

- [ ] **Step 3: Refresh the "Pick up here" brief**

Update `RedPole/AGENTS.md:6-12`:

```markdown
## ⏱ Pick up here   ← LIVING; refresh at session end
- **Status:**       Prototype — Phase 1 of the Evolving Soundscape Synthesizer redesign (docs/superpowers/plans/2026-07-22-evolving-soundscape-phase1.md) is implemented as new, additive modules in audio_prototype/ (soundscape_*.py): 5 source engines x 5 presets, 5 transform engines x 5 presets, a shared harmonic pitch field with register-aware allocation, density-based gain scaling, and a simple voice-priority system. Runnable via `python soundscape_prototype.py` from audio_prototype/ (desktop-only, no browser/Pyodide port yet). The existing web app's Loop/Synth modes and audio_prototype/gui.py are untouched. Firmware/TD integration still WIP.
- **Last session:** 2026-07-22 — implemented Phase 1 of the evolving-soundscape redesign per the new spec (see docs/superpowers/specs/2026-07-22-evolving-soundscape-design.md and the plan above); previous sample-backed synth mode work is preserved but will be replaced by this system once tuned (per project decision).
- **Next up:**
  - Tune Phase 1 by ear against the reference playlist (spec section 4, 16): register limits, gain curves, preset parameters in soundscape_sources.py / soundscape_transforms.py.
  - Plan Phase 2 (spec section 13): wire SoundscapeEngine into a real 5x5 output-matrix / 5x5 input-matrix UI, replacing LayerRegistry's single-engine/row/col model for this system.
  - Once tuned, plan the port that replaces the web app's Synth mode with this engine (desktop-proven first, per project decision).
  - Document the firmware serial message shape (base64 JPEG framing).
- **Blockers / open questions:** Is TD driven by the web app, the Python engine, or the device directly?
```

- [ ] **Step 4: Commit**

```bash
rtk git add RedPole/AGENTS.md
rtk git commit -m "docs: mark soundscape phase 1 implemented in agent brief"
```
