# Web DSP Engine Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `WebEngine.generate_block` (`audio_prototype/web_engine.py`) up to true parity with what the desktop app actually produces at runtime — all 4 microcosm families, crowd/entry-gesture tape modulation, and dynamic reverb spatial character — matching `AudioEngine.generate_block`'s always-on "mixed" mode (`audio_prototype/audio_engine.py`; `gui.py` never calls `set_mode`, so `"mixed"` is the only mode that ever runs in the real app).

**Architecture:** Changes are entirely in `audio_prototype/web_engine.py` (shared, fetched at runtime by Pyodide — no duplication), plus adding one new file (`crowd.py`) to the Pyodide fetch list and the GitHub Pages publish step. No changes to `webapp/main.js` beyond what Plan 2 (`2026-07-21-web-full-patch-bay.md`) already does — engine name strings `microloop`/`glitch`/`multidelay` sent via `connect_source` are already valid per `layers.py`'s `ENGINES` tuple; `MicrocosmProcessor.process` (`microcosm_processor.py:127-141`) already dispatches generically by `layer["engine"]`, so no changes to that file are needed.

**Tech Stack:** Python 3 (runs under Pyodide in a Web Worker), NumPy, Pytest for verification (this part of the codebase — unlike `webapp/`'s JS — already has test infrastructure: `audio_prototype/tests/`).

**Scope note (from `docs/superpowers/specs/2026-07-21-web-full-parity-design.md`):** standalone `spectral`/`granular` single-engine modes and reverb *room-style* picking remain out of scope — `gui.py` never switches `AudioEngine.set_mode()` away from its `"mixed"` default, so those code paths never run in the real desktop app, and reverb style is hardcoded to `"wash"` in `audio_engine.py`'s own `reverb_layer_controls` (never varies) — there is no "style variety" to port. What **is** newly discovered as real, always-active desktop behavior and therefore in scope here: `SchroederReverb.set_space()` is called every block in desktop's mixed mode with dynamically computed `size`/`diffusion` (still `style="wash"` always) — `web_engine.py` never calls `set_space` at all today, so its reverb runs with static constructor defaults (`space_style="bright_room"`, `space_size=0.35`, `diffusion=0.45`) instead of the dynamic wash character the desktop app actually produces. This plan fixes that alongside the microcosm-family and crowd/entry-gesture gaps.

## Global Constraints

- Reuse existing effect classes exactly as `AudioEngine` does — no new DSP algorithms, only wiring already-tested classes (`MicrocosmProcessor`, `CrowdState`, `EntryGestureTracker`, `SchroederReverb.set_space`) into `WebEngine`.
- Do not change `web_engine.py`'s existing `bpm_to_reverb_feedback`/`val_to_reverb_cutoff` tuning constants — those are deliberately web-specific and unrelated to this plan's `set_space` addition.
- Do not add live spectral analysis, visualization buffers, or standalone spectral/granular engines — explicitly out of scope per the design spec.

---

### Task 1: Widen microcosm family filter to all 4 families

**Files:**
- Modify: `audio_prototype/web_engine.py:75-76,102-105` (engine layer filtering)
- Test: `audio_prototype/tests/test_web_engine.py` (create if it doesn't exist)

**Interfaces:**
- Consumes: `MicrocosmProcessor.process(loop_array, frames, layers, source_pos=0)` (`microcosm_processor.py:127`, unchanged), `MicrocosmProcessor.FAMILIES` (`microcosm_processor.py:5`, unchanged).
- Produces: `WebEngine.generate_block` now mixes `microloop`/`granules`/`glitch`/`multidelay` layers together — Task 2 and Task 3 build on this same variable (renamed `micro_layers`).

- [ ] **Step 1: Check for an existing test file and write a failing test**

Check whether `audio_prototype/tests/test_web_engine.py` exists. If not, create it with this content (if it exists, add this test function to it):

```python
import numpy as np
import pytest

from web_engine import WebEngine


@pytest.fixture
def engine():
    eng = WebEngine(samplerate=44100, seed=42)
    rng = np.random.default_rng(1)
    eng.load_loop(rng.uniform(-0.5, 0.5, 44100).astype(np.float32))
    return eng


def test_all_four_microcosm_families_alter_output(engine):
    for family in ("microloop", "granules", "glitch", "multidelay"):
        engine.wet_dry = 0.0
        dry = engine.generate_block(4096)
        engine.modulator._read_pos = 0
        source_id = engine.registry.add_source(hue=0.03, sat=0.68, val=0.94, bpm=100)
        engine.registry.connect_source(source_id, engine=family, row=0, col=0)
        engine.wet_dry = 1.0
        engine.modulator._read_pos = 0
        wet = engine.generate_block(4096)
        assert not np.allclose(dry, wet), f"{family} produced no audible change"
        engine.registry.remove_source(source_id)
```

The test compares a fully-dry block against a fully-wet block generated from the same engine state (`modulator._read_pos` is reset between the two so both reads start from the same point in the loop) — this is what actually distinguishes "the microcosm processor produced sound" from "the loop itself happens to be nonzero," which a plain `np.max(np.abs(block)) > 0.0` assertion would not catch.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd audio_prototype && python -m pytest tests/test_web_engine.py::test_all_four_microcosm_families_alter_output -v`
Expected: FAIL on `microloop` (the first family tried) with an `AssertionError` — `dry` and `wet` are identical because today's filter (`gran_layers = [l for l in layers if l["engine"] == "granules"]`) silently drops `microloop`/`glitch`/`multidelay` layers, so `MicrocosmProcessor` never sees them and the wet mix is unaffected.

- [ ] **Step 3: Widen the engine filter in `web_engine.py`**

In `audio_prototype/web_engine.py`, `generate_block` (currently lines 70-142) starts:

```python
    def generate_block(self, frames):
        if self.loop_array is None:
            raise RuntimeError("No loop loaded; call load_loop() first")

        layers = self.registry.snapshot()
        tape_layers = [l for l in layers if l["engine"] == "tape"]
        gran_layers = [l for l in layers if l["engine"] == "granules"]
        reverb_layers = [l for l in layers if l["engine"] == "reverb"]
```

Replace with:

```python
    def generate_block(self, frames):
        if self.loop_array is None:
            raise RuntimeError("No loop loaded; call load_loop() first")

        layers = self.registry.snapshot()
        tape_layers = [l for l in layers if l["engine"] == "tape"]
        micro_layers = [l for l in layers if l["engine"] in MICRO_FAMILIES]
        reverb_layers = [l for l in layers if l["engine"] == "reverb"]
```

Add the `MICRO_FAMILIES` constant near the top of the file, right after the existing module constants (after `REVERB_SMOOTHING = 0.1` on line 23):

```python
MICRO_FAMILIES = ("microloop", "granules", "glitch", "multidelay")
```

Then further down in the same method, replace every remaining use of `gran_layers`. The current code:

```python
        wet_raw = self.microcosm.process(
            self.loop_array, frames, gran_layers, source_pos=source_pos
        )
        n_wet = len(gran_layers)
        n_rv = len(reverb_layers)
```

becomes:

```python
        wet_raw = self.microcosm.process(
            self.loop_array, frames, micro_layers, source_pos=source_pos
        )
        n_wet = len(micro_layers)
        n_rv = len(reverb_layers)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd audio_prototype && python -m pytest tests/test_web_engine.py::test_all_four_microcosm_families_alter_output -v`
Expected: PASS for all 4 families.

- [ ] **Step 5: Run the full existing test suite to check for regressions**

Run: `cd audio_prototype && python -m pytest tests/ -v`
Expected: all tests PASS (no existing test should reference `gran_layers` by name since it was a local variable, not part of any public interface).

- [ ] **Step 6: Commit**

```bash
git add audio_prototype/web_engine.py audio_prototype/tests/test_web_engine.py
git commit -m "feat(web_engine): mix all 4 microcosm families, not just granules"
```

---

### Task 2: Crowd / entry-gesture tape modulation

**Files:**
- Modify: `audio_prototype/web_engine.py` (imports, `__init__`, `generate_block`)
- Test: `audio_prototype/tests/test_web_engine.py`

**Interfaces:**
- Consumes: `CrowdState.from_layers(layers)` (`crowd.py:27`), `EntryGestureTracker(samplerate, duration_seconds=6.0, max_active=6)` / `.process(layers, frames, density)` → `EntryGestureState` / `.engine_gain(engine)` (`crowd.py:79-136`).
- Produces: `self.entry_gestures` instance attribute on `WebEngine` — no later task in this plan depends on it beyond Task 2 itself.

- [ ] **Step 1: Write a failing test for the bloom-depth boost**

Add to `audio_prototype/tests/test_web_engine.py`:

```python
def test_new_tape_source_gets_a_bloom_boost_from_entry_gesture(engine):
    engine.wet_dry = 0.0
    source_id = engine.registry.add_source(hue=0.03, sat=0.68, val=0.94, bpm=100)
    engine.registry.connect_source(source_id, engine="tape", row=0, col=0)
    boosted = engine.generate_block(4096)
    # A fresh entry gesture decays over ~6s; regenerate blocks until it has
    # fully faded, then compare bloom-driven output magnitude.
    for _ in range(80):
        settled = engine.generate_block(4096)
    assert not np.allclose(boosted, settled)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd audio_prototype && python -m pytest tests/test_web_engine.py::test_new_tape_source_gets_a_bloom_boost_from_entry_gesture -v`
Expected: FAIL — `boosted` and `settled` are identical today since `web_engine.py` has no entry-gesture concept at all, so bloom depth never changes based on how recently a layer was added.

- [ ] **Step 3: Wire `CrowdState`/`EntryGestureTracker` into `WebEngine`**

In `audio_prototype/web_engine.py`, the import block currently reads:

```python
import numpy as np

from layers import LayerRegistry
from modulation import RmsLimiter, combine_layers, soft_clip, val_to_unit
from microcosm_processor import MicrocosmProcessor
from reverb import SchroederReverb
from tape_modulator import TapeModulator, tape_column_controls
from wet_bus import WetBusManager
```

Replace with:

```python
import numpy as np

from crowd import CrowdState, EntryGestureTracker
from layers import LayerRegistry
from modulation import RmsLimiter, combine_layers, sat_to_unit, soft_clip, val_to_unit
from microcosm_processor import MicrocosmProcessor
from reverb import SchroederReverb
from tape_modulator import TapeModulator, tape_column_controls
from wet_bus import WetBusManager
```

(`sat_to_unit` is added here in anticipation of Task 3, which needs it — importing it now avoids touching this import line twice.)

In `WebEngine.__init__` (currently ending with `self.loop_array = None`), add the tracker right after `self.wet_bus = WetBusManager(samplerate)`:

```python
        self.wet_bus = WetBusManager(samplerate)
        self.entry_gestures = EntryGestureTracker(samplerate)
```

- [ ] **Step 4: Apply the entry-gesture gain to tape's bloom depth**

In `generate_block`, the current tape-processing block reads:

```python
        combined = combine_layers(tape_layers)
        tape_controls = tape_column_controls(tape_layers)
        avg_hue = sum(l["hue"] for l in tape_layers) / len(tape_layers) if tape_layers else 0.0
        avg_sat = sum(l["sat"] for l in tape_layers) / len(tape_layers) if tape_layers else 0.5
        avg_val = sum(l["val"] for l in tape_layers) / len(tape_layers) if tape_layers else 1.0

        source_pos = self.modulator._read_pos
        base = self.modulator.process(
            self.loop_array,
            frames,
            combined["warble_depth"],
            combined["bloom_depth"],
            combined["rate_hz"],
            hue=avg_hue,
            sat=avg_sat,
            val=avg_val,
            tape_controls=tape_controls,
        )
```

Replace with (adding the crowd/entry computation right after `layers = self.registry.snapshot()` at the top of the method, and using `entry.engine_gain("tape")` to boost bloom depth, matching desktop mixed mode's `combined["bloom_depth"] * (1.0 + entry.engine_gain("tape"))`, `audio_engine.py:293`):

```python
        combined = combine_layers(tape_layers)
        tape_controls = tape_column_controls(tape_layers)
        avg_hue = sum(l["hue"] for l in tape_layers) / len(tape_layers) if tape_layers else 0.0
        avg_sat = sum(l["sat"] for l in tape_layers) / len(tape_layers) if tape_layers else 0.5
        avg_val = sum(l["val"] for l in tape_layers) / len(tape_layers) if tape_layers else 1.0

        crowd = CrowdState.from_layers(layers)
        entry = self.entry_gestures.process(layers, frames, crowd.density)

        source_pos = self.modulator._read_pos
        base = self.modulator.process(
            self.loop_array,
            frames,
            combined["warble_depth"],
            combined["bloom_depth"] * (1.0 + entry.engine_gain("tape")),
            combined["rate_hz"],
            hue=avg_hue,
            sat=avg_sat,
            val=avg_val,
            tape_controls=tape_controls,
        )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd audio_prototype && python -m pytest tests/test_web_engine.py::test_new_tape_source_gets_a_bloom_boost_from_entry_gesture -v`
Expected: PASS.

- [ ] **Step 6: Run the full test suite**

Run: `cd audio_prototype && python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add audio_prototype/web_engine.py audio_prototype/tests/test_web_engine.py
git commit -m "feat(web_engine): apply entry-gesture bloom boost to new tape sources"
```

---

### Task 3: Dynamic reverb spatial character (`set_space`)

**Files:**
- Modify: `audio_prototype/web_engine.py` (`generate_block`'s reverb section)
- Test: `audio_prototype/tests/test_web_engine.py`

**Interfaces:**
- Consumes: `SchroederReverb.set_space(style, size, diffusion)` (`reverb.py:142-153`), `sat_to_unit` (imported in Task 2).
- Produces: nothing new for later tasks — this is the last task in this plan.

- [ ] **Step 1: Write a failing test**

Add to `audio_prototype/tests/test_web_engine.py`:

```python
def test_reverb_layers_set_dynamic_space(engine):
    assert engine.reverb.space_style == "bright_room"
    source_id = engine.registry.add_source(hue=0.03, sat=0.7, val=0.9, bpm=100)
    engine.registry.connect_source(source_id, engine="reverb", row=0, col=0)
    engine.generate_block(4096)
    assert engine.reverb.space_style == "wash"
    assert engine.reverb.space_size != 0.35 or engine.reverb.diffusion != 0.45
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd audio_prototype && python -m pytest tests/test_web_engine.py::test_reverb_layers_set_dynamic_space -v`
Expected: FAIL — `engine.reverb.space_style` stays `"bright_room"` (the `SchroederReverb` constructor default, `reverb.py:131`) because `web_engine.py` never calls `set_space`.

- [ ] **Step 3: Compute and apply dynamic space size/diffusion**

In `generate_block`, the current reverb-controls block reads:

```python
        if reverb_layers:
            weights = np.array(
                [0.2 + l["sat"] + l["val"] for l in reverb_layers], dtype=np.float64
            )
            vals = np.array([l["val"] for l in reverb_layers], dtype=np.float64)
            bpms = np.array([l["bpm"] for l in reverb_layers], dtype=np.float64)
            rv_val = float(np.average(vals, weights=weights))
            rv_bpm = float(np.average(bpms, weights=weights))
            target_fb = bpm_to_reverb_feedback(rv_bpm)
            target_cut = val_to_reverb_cutoff(rv_val)
        else:
            target_fb = REVERB_DEFAULT_FEEDBACK
            target_cut = REVERB_DEFAULT_CUTOFF
```

Replace with (adding `sats`/`rv_sat_unit`/`rv_density`/`rv_size`/`rv_diffusion`, matching desktop `reverb_layer_controls`'s `size`/`diffusion` formulas exactly, `audio_engine.py:88-94`, while keeping the existing `bpm_to_reverb_feedback`/`val_to_reverb_cutoff` calls untouched):

```python
        if reverb_layers:
            weights = np.array(
                [0.2 + l["sat"] + l["val"] for l in reverb_layers], dtype=np.float64
            )
            sats = np.array([l["sat"] for l in reverb_layers], dtype=np.float64)
            vals = np.array([l["val"] for l in reverb_layers], dtype=np.float64)
            bpms = np.array([l["bpm"] for l in reverb_layers], dtype=np.float64)
            rv_val = float(np.average(vals, weights=weights))
            rv_bpm = float(np.average(bpms, weights=weights))
            rv_sat_unit = float(np.average([sat_to_unit(s) for s in sats], weights=weights))
            target_fb = bpm_to_reverb_feedback(rv_bpm)
            target_cut = val_to_reverb_cutoff(rv_val)
            rv_density = min(1.0, np.sqrt(len(reverb_layers) / 6.0))
            rv_size = min(1.0, 0.48 + 0.38 * rv_sat_unit + 0.30 * rv_density)
            rv_diffusion = min(1.0, 0.55 + 0.30 * rv_sat_unit + 0.25 * rv_density)
        else:
            target_fb = REVERB_DEFAULT_FEEDBACK
            target_cut = REVERB_DEFAULT_CUTOFF
            rv_size = 0.35
            rv_diffusion = 0.45
```

Then, immediately after the existing smoothing block:

```python
        self._rv_feedback += REVERB_SMOOTHING * (target_fb - self._rv_feedback)
        self._rv_cutoff += REVERB_SMOOTHING * (target_cut - self._rv_cutoff)
        self.reverb.set_feedback(self._rv_feedback)
        self.reverb.set_cutoff(self._rv_cutoff)
```

add:

```python
        self.reverb.set_space(style="wash", size=rv_size, diffusion=rv_diffusion)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd audio_prototype && python -m pytest tests/test_web_engine.py::test_reverb_layers_set_dynamic_space -v`
Expected: PASS.

- [ ] **Step 5: Run the full test suite**

Run: `cd audio_prototype && python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add audio_prototype/web_engine.py audio_prototype/tests/test_web_engine.py
git commit -m "feat(web_engine): apply dynamic reverb space size/diffusion"
```

---

### Task 4: Publish `crowd.py` to the Pyodide worker and GitHub Pages

**Files:**
- Modify: `webapp/worker.js:9-17` (`PYTHON_FILES`)
- Modify: `.github/workflows/deploy-pages.yml:8-14,42-49` (`paths` trigger and copy step)

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing — final integration task for this plan.

- [ ] **Step 1: Add `crowd.py` to the worker's fetch list**

In `webapp/worker.js`, `PYTHON_FILES` currently reads:

```js
const PYTHON_FILES = [
  "modulation.py",
  "layers.py",
  "tape_modulator.py",
  "microcosm_processor.py",
  "reverb.py",
  "wet_bus.py",
  "web_engine.py",
];
```

Replace with:

```js
const PYTHON_FILES = [
  "modulation.py",
  "layers.py",
  "tape_modulator.py",
  "microcosm_processor.py",
  "reverb.py",
  "wet_bus.py",
  "crowd.py",
  "web_engine.py",
];
```

(`crowd.py` must be fetched before `web_engine.py` imports it — Pyodide's `pyodide.FS.writeFile` happens for every entry before `import web_engine` runs in `initPyodide`, so list order here doesn't actually gate import order, but keeping it just before `web_engine.py` mirrors the import's dependency direction for readability.)

- [ ] **Step 2: Add `crowd.py` to the GitHub Pages workflow**

In `.github/workflows/deploy-pages.yml`, the `paths` trigger list currently reads:

```yaml
    paths:
      - "webapp/**"
      - "audio_prototype/modulation.py"
      - "audio_prototype/layers.py"
      - "audio_prototype/tape_modulator.py"
      - "audio_prototype/microcosm_processor.py"
      - "audio_prototype/reverb.py"
      - "audio_prototype/wet_bus.py"
      - "audio_prototype/web_engine.py"
      - ".github/workflows/deploy-pages.yml"
```

Replace with:

```yaml
    paths:
      - "webapp/**"
      - "audio_prototype/modulation.py"
      - "audio_prototype/layers.py"
      - "audio_prototype/tape_modulator.py"
      - "audio_prototype/microcosm_processor.py"
      - "audio_prototype/reverb.py"
      - "audio_prototype/wet_bus.py"
      - "audio_prototype/crowd.py"
      - "audio_prototype/web_engine.py"
      - ".github/workflows/deploy-pages.yml"
```

And the copy step currently reads:

```yaml
          cp audio_prototype/modulation.py \
             audio_prototype/layers.py \
             audio_prototype/tape_modulator.py \
             audio_prototype/microcosm_processor.py \
             audio_prototype/reverb.py \
             audio_prototype/wet_bus.py \
             audio_prototype/web_engine.py \
             site/audio_prototype/
```

Replace with:

```yaml
          cp audio_prototype/modulation.py \
             audio_prototype/layers.py \
             audio_prototype/tape_modulator.py \
             audio_prototype/microcosm_processor.py \
             audio_prototype/reverb.py \
             audio_prototype/wet_bus.py \
             audio_prototype/crowd.py \
             audio_prototype/web_engine.py \
             site/audio_prototype/
```

- [ ] **Step 3: Manually verify in-browser**

Serve the repo root (so `../audio_prototype/crowd.py` resolves the same way local dev already resolves the other fetched files) and open `webapp/index.html` in the Browser preview tool. Confirm the status banner clears (no `error` message about a failed fetch or Python import) — this confirms `crowd.py` was fetched successfully and `web_engine.WebEngine()` instantiated without an `ImportError`. Send a source, connect it to each of the 4 microcosm rows in turn (from Plan 2) and confirm audio plays without a worker error in each case; connect a source to the reverb cell and confirm audio still plays (dynamic `set_space` wired in Task 3 doesn't raise).

- [ ] **Step 4: Commit**

```bash
git add webapp/worker.js .github/workflows/deploy-pages.yml
git commit -m "chore(webapp): publish crowd.py to the Pyodide worker and GitHub Pages"
```
