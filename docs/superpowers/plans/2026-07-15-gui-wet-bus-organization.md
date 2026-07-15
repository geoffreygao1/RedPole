# GUI Cleanup & Wet-Bus Organization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove redundant GUI controls and add density-aware wet-bus management so many inputs remain organized around the source audio.

**Architecture:** Add a focused `wet_bus.py` helper that computes density controls and applies lightweight tone cleanup. `AudioEngine.generate_block` continues to own routing, reverb, limiting, wet/dry blend, and visual buffers, but delegates wet-bus tuning to the helper. `gui.py` removes the global reverb slider and moves global audition controls outside the Scan Input panel.

**Tech Stack:** Python, NumPy, Tkinter, pytest; existing `SchroederReverb`, `RmsLimiter`, and `AudioEngine` APIs.

---

## File Structure

- Create `audio_prototype/wet_bus.py`: density metric, adaptive wet gain, wet-bus high-pass/low-mid cleanup, and reverb-density target helpers.
- Create `audio_prototype/tests/test_wet_bus.py`: deterministic tests for density controls and tone cleanup.
- Modify `audio_prototype/audio_engine.py`: use `WetBusManager`, fold density into reverb feedback/cutoff targets, preserve zero-layer dry behavior.
- Modify `audio_prototype/tests/test_audio_engine.py`: cover many-layer wet bounds, low-frequency cleanup, reverb density, and existing A/B behavior.
- Modify `audio_prototype/gui.py`: remove `reverb_var` and Reverb slider, move Wet/Dry and live-analysis controls into a global audition panel after Scan Input.

## Global Constraints

- Do not overwrite the existing uncommitted spectral harmonic-snapping changes in `audio_prototype/spectral_processor.py` or `audio_prototype/tests/test_spectral_processor.py`.
- Keep `wet_dry=0` as dry/base only and `wet_dry=1` as wet only.
- Reverb-only layers shape the room but add no direct wet signal.
- Zero-layer output must remain exact dry playback.
- Use `.venv/Scripts/python.exe -m pytest` if `.venv` exists; otherwise use `python -m pytest`.

---

### Task 1: Add Wet-Bus Helper

**Files:**
- Create: `audio_prototype/wet_bus.py`
- Create: `audio_prototype/tests/test_wet_bus.py`

- [ ] **Step 1: Write failing wet-bus tests**

Create `audio_prototype/tests/test_wet_bus.py`:

```python
import numpy as np
import pytest

from wet_bus import WetBusManager, density_controls

SR = 44100


def _tone(freq, seconds=1.0, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


def _rms(x):
    return float(np.sqrt(np.mean(np.asarray(x) ** 2)))


def test_density_controls_are_neutral_with_no_density():
    controls = density_controls(wet_voice_count=0, reverb_layer_count=0)
    assert controls["wet_gain"] == pytest.approx(1.0)
    assert controls["feedback_trim"] == pytest.approx(0.0)
    assert controls["cutoff_scale"] == pytest.approx(1.0)
    assert controls["highpass_hz"] == pytest.approx(35.0)
    assert controls["low_mid_gain"] == pytest.approx(1.0)


def test_density_controls_tighten_as_layers_accumulate():
    light = density_controls(wet_voice_count=1, reverb_layer_count=0)
    dense = density_controls(wet_voice_count=20, reverb_layer_count=4)
    assert dense["wet_gain"] < light["wet_gain"]
    assert dense["feedback_trim"] > light["feedback_trim"]
    assert dense["cutoff_scale"] < light["cutoff_scale"]
    assert dense["highpass_hz"] > light["highpass_hz"]
    assert dense["low_mid_gain"] < light["low_mid_gain"]


def test_tone_cleanup_reduces_low_frequency_more_than_presence_band():
    manager = WetBusManager(SR)
    low = _tone(120.0)
    presence = _tone(1800.0)
    low_out = manager.process(low, wet_voice_count=20, reverb_layer_count=0)

    manager2 = WetBusManager(SR)
    presence_out = manager2.process(
        presence, wet_voice_count=20, reverb_layer_count=0
    )

    assert _rms(low_out) < _rms(low) * 0.75
    assert _rms(presence_out) > _rms(presence) * 0.55


def test_process_is_neutral_for_zero_density_after_filter_settle():
    manager = WetBusManager(SR)
    x = _tone(800.0)
    out = manager.process(x, wet_voice_count=0, reverb_layer_count=0)
    np.testing.assert_allclose(out[4000:], x[4000:], atol=0.04)
    assert out.dtype == np.float32
```

- [ ] **Step 2: Run the wet-bus tests and verify they fail**

Run:

```bash
python -m pytest audio_prototype/tests/test_wet_bus.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wet_bus'`.

- [ ] **Step 3: Implement `wet_bus.py`**

Create `audio_prototype/wet_bus.py`:

```python
import numpy as np


def clamp(value, min_v, max_v):
    return max(min_v, min(max_v, value))


def density_controls(wet_voice_count, reverb_layer_count):
    """Return wet-bus controls derived from active additive density.

    wet_voice_count counts spectral+granular contributors. reverb_layer_count
    shapes room density but never creates direct wet signal.
    """
    wet_voice_count = max(0, int(wet_voice_count))
    reverb_layer_count = max(0, int(reverb_layer_count))
    total_density = wet_voice_count + 0.5 * reverb_layer_count
    normalized = clamp(total_density / 20.0, 0.0, 1.0)

    return {
        "density": normalized,
        "wet_gain": 1.0 / (1.0 + 0.045 * wet_voice_count),
        "feedback_trim": 0.12 * normalized,
        "cutoff_scale": 1.0 - 0.45 * normalized,
        "highpass_hz": 35.0 + 145.0 * normalized,
        "low_mid_gain": 1.0 - 0.35 * normalized,
    }


class OnePoleHighpass:
    """First-order high-pass implemented as x - lowpass(x)."""

    def __init__(self, samplerate, cutoff_hz):
        self.samplerate = samplerate
        self._low_state = 0.0
        self.set_cutoff(cutoff_hz)

    def set_cutoff(self, cutoff_hz):
        self.cutoff_hz = float(cutoff_hz)
        self._alpha = 1.0 - np.exp(-2.0 * np.pi * self.cutoff_hz / self.samplerate)

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        out = np.empty(len(x), dtype=np.float64)
        state = self._low_state
        alpha = self._alpha
        for i, sample in enumerate(x):
            state += alpha * (sample - state)
            out[i] = sample - state
        self._low_state = state
        return out


class OnePoleLowpass:
    def __init__(self, samplerate, cutoff_hz):
        self.samplerate = samplerate
        self._state = 0.0
        self.set_cutoff(cutoff_hz)

    def set_cutoff(self, cutoff_hz):
        self.cutoff_hz = float(cutoff_hz)
        self._alpha = 1.0 - np.exp(-2.0 * np.pi * self.cutoff_hz / self.samplerate)

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        out = np.empty(len(x), dtype=np.float64)
        state = self._state
        alpha = self._alpha
        for i, sample in enumerate(x):
            state += alpha * (sample - state)
            out[i] = state
        self._state = state
        return out


class WetBusManager:
    """Density-aware wet-bus level and tone cleanup."""

    def __init__(self, samplerate):
        self.samplerate = samplerate
        self._highpass = OnePoleHighpass(samplerate, cutoff_hz=35.0)
        self._low_mid = OnePoleLowpass(samplerate, cutoff_hz=650.0)

    def controls(self, wet_voice_count, reverb_layer_count):
        return density_controls(wet_voice_count, reverb_layer_count)

    def process(self, wet, wet_voice_count, reverb_layer_count):
        wet = np.asarray(wet, dtype=np.float64)
        controls = self.controls(wet_voice_count, reverb_layer_count)
        self._highpass.set_cutoff(controls["highpass_hz"])

        highpassed = self._highpass.process(wet)
        low_mid = self._low_mid.process(highpassed)
        cleaned = highpassed - (1.0 - controls["low_mid_gain"]) * low_mid
        return (controls["wet_gain"] * cleaned).astype(np.float32)
```

- [ ] **Step 4: Run wet-bus tests and verify they pass**

Run:

```bash
python -m pytest audio_prototype/tests/test_wet_bus.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit wet-bus helper**

Run:

```bash
git add audio_prototype/wet_bus.py audio_prototype/tests/test_wet_bus.py
git commit -m "feat: add adaptive wet bus manager"
```

---

### Task 2: Integrate Wet-Bus Manager Into Audio Engine

**Files:**
- Modify: `audio_prototype/audio_engine.py`
- Modify: `audio_prototype/tests/test_audio_engine.py`

- [ ] **Step 1: Add failing engine tests**

Append these tests to `audio_prototype/tests/test_audio_engine.py`:

```python
def _band_rms(x, samplerate, low_hz, high_hz):
    x = np.asarray(x)
    spectrum = np.fft.rfft(x * np.hanning(len(x)))
    freqs = np.fft.rfftfreq(len(x), 1.0 / samplerate)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    return float(np.sqrt(np.mean(np.abs(spectrum[mask]) ** 2)))


def test_dense_wet_layers_trigger_wet_bus_gain_reduction():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    for _ in range(20):
        engine.registry.add(hue=0.03, sat=0.7, val=1.0, bpm=120, engine="spectral")

    for _ in range(20):
        engine.generate_block(1024)

    controls = engine.wet_bus.controls(wet_voice_count=20, reverb_layer_count=0)
    assert controls["wet_gain"] < 0.6
    assert engine.wet_limiter.gain > 0.2


def test_dense_wet_bus_reduces_low_mid_energy():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    low_mid = np.sin(2 * np.pi * 160 * np.arange(8192) / engine.samplerate).astype(
        np.float32
    )

    shaped_sparse = engine.wet_bus.process(
        low_mid, wet_voice_count=1, reverb_layer_count=0
    )

    engine2 = AudioEngine(seed=1)
    engine2.load_loop(str(SAMPLE_LOOP))
    shaped_dense = engine2.wet_bus.process(
        low_mid, wet_voice_count=20, reverb_layer_count=0
    )

    sparse_low = _band_rms(shaped_sparse, engine.samplerate, 80, 300)
    dense_low = _band_rms(shaped_dense, engine.samplerate, 80, 300)
    assert dense_low < sparse_low * 0.7


def test_reverb_density_tightens_feedback_and_cutoff():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=40, engine="reverb")
    for _ in range(20):
        engine.registry.add(hue=0.03, sat=0.7, val=1.0, bpm=120, engine="spectral")

    for _ in range(80):
        engine.generate_block(1024)

    dense_feedback = engine.reverb._combs[0].feedback
    dense_cutoff = engine.reverb._lowpass.cutoff_hz

    sparse = AudioEngine(seed=1)
    sparse.load_loop(str(SAMPLE_LOOP))
    sparse.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=40, engine="reverb")
    for _ in range(80):
        sparse.generate_block(1024)

    assert dense_feedback < sparse.reverb._combs[0].feedback
    assert dense_cutoff < sparse.reverb._lowpass.cutoff_hz
```

- [ ] **Step 2: Run new engine tests and verify they fail**

Run:

```bash
python -m pytest audio_prototype/tests/test_audio_engine.py::test_dense_wet_layers_trigger_wet_bus_gain_reduction audio_prototype/tests/test_audio_engine.py::test_dense_wet_bus_reduces_low_mid_energy audio_prototype/tests/test_audio_engine.py::test_reverb_density_tightens_feedback_and_cutoff -v
```

Expected: FAIL because `AudioEngine` has no `wet_bus` attribute or density integration.

- [ ] **Step 3: Add `WetBusManager` to `AudioEngine.__init__`**

Modify imports in `audio_prototype/audio_engine.py`:

```python
from wet_bus import WetBusManager
```

Add this in `AudioEngine.__init__` after `self.reverb = SchroederReverb(samplerate)`:

```python
self.wet_bus = WetBusManager(samplerate)
```

- [ ] **Step 4: Apply density controls before reverb and limiter**

In `AudioEngine.generate_block`, in the non-tape branch, replace the current reverb-target and wet processing block:

```python
if reverb_layers:
    n_rv = len(reverb_layers)
    target_fb = bpm_to_reverb_feedback(
        sum(l["bpm"] for l in reverb_layers) / n_rv
    )
    target_cut = val_to_reverb_cutoff(
        sum(l["val"] for l in reverb_layers) / n_rv
    )
else:
    target_fb = REVERB_DEFAULT_FEEDBACK
    target_cut = REVERB_DEFAULT_CUTOFF
self._rv_feedback += REVERB_SMOOTHING * (target_fb - self._rv_feedback)
self._rv_cutoff += REVERB_SMOOTHING * (target_cut - self._rv_cutoff)
self.reverb.set_feedback(self._rv_feedback)
self.reverb.set_cutoff(self._rv_cutoff)

wet = self.wet_limiter.process(
    wet_raw + self.reverb_mix * self.reverb.process(wet_raw)
)
```

with:

```python
if reverb_layers:
    n_rv = len(reverb_layers)
    target_fb = bpm_to_reverb_feedback(
        sum(l["bpm"] for l in reverb_layers) / n_rv
    )
    target_cut = val_to_reverb_cutoff(
        sum(l["val"] for l in reverb_layers) / n_rv
    )
else:
    n_rv = 0
    target_fb = REVERB_DEFAULT_FEEDBACK
    target_cut = REVERB_DEFAULT_CUTOFF

controls = self.wet_bus.controls(
    wet_voice_count=n_wet,
    reverb_layer_count=n_rv,
)
target_fb = max(0.62, target_fb - controls["feedback_trim"])
target_cut = max(700.0, target_cut * controls["cutoff_scale"])
self._rv_feedback += REVERB_SMOOTHING * (target_fb - self._rv_feedback)
self._rv_cutoff += REVERB_SMOOTHING * (target_cut - self._rv_cutoff)
self.reverb.set_feedback(self._rv_feedback)
self.reverb.set_cutoff(self._rv_cutoff)

managed_wet_raw = self.wet_bus.process(
    wet_raw,
    wet_voice_count=n_wet,
    reverb_layer_count=n_rv,
)
wet = self.wet_limiter.process(
    managed_wet_raw + self.reverb_mix * self.reverb.process(managed_wet_raw)
)
```

Keep this line before the new block:

```python
n_wet = len(spec_layers) + len(gran_layers)
```

- [ ] **Step 5: Run targeted engine tests**

Run:

```bash
python -m pytest audio_prototype/tests/test_audio_engine.py::test_dense_wet_layers_trigger_wet_bus_gain_reduction audio_prototype/tests/test_audio_engine.py::test_dense_wet_bus_reduces_low_mid_energy audio_prototype/tests/test_audio_engine.py::test_reverb_density_tightens_feedback_and_cutoff -v
```

Expected: PASS.

- [ ] **Step 6: Run full audio engine tests**

Run:

```bash
python -m pytest audio_prototype/tests/test_audio_engine.py -v
```

Expected: PASS. If `test_reverb_character_follows_reverb_layer_brightness` fails because density now scales cutoff, keep the expected ordering and adjust only tolerance or block count; do not remove the assertion that brighter reverb layers produce brighter tails.

- [ ] **Step 7: Commit engine integration**

Run:

```bash
git add audio_prototype/audio_engine.py audio_prototype/tests/test_audio_engine.py
git commit -m "feat: organize dense wet bus in audio engine"
```

---

### Task 3: Clean Up GUI Control Layout

**Files:**
- Modify: `audio_prototype/gui.py`

- [ ] **Step 1: Inspect current GUI references**

Run:

```bash
rg "reverb_var|Reverb|Wet/Dry|live_var" audio_prototype/gui.py
```

Expected: current matches include `self.reverb_var`, the `Reverb` label/scale, `Wet/Dry`, and `live_var`.

- [ ] **Step 2: Remove `reverb_var` state**

In `RedPoleGUI.__init__`, delete this line:

```python
self.reverb_var = tk.DoubleVar(value=self.engine.reverb_mix)
```

Keep:

```python
self.wet_dry_var = tk.DoubleVar(value=self.engine.wet_dry)
```

- [ ] **Step 3: Remove Reverb slider from Scan Input**

In `_build_controls`, delete this block:

```python
ttk.Label(frame, text="Reverb").grid(row=7, column=0, sticky="w")
ttk.Scale(
    frame, from_=0.0, to=1.0, variable=self.reverb_var,
    command=lambda _v: setattr(
        self.engine, "reverb_mix", self.reverb_var.get()
    ),
).grid(row=7, column=1, columnspan=2, sticky="ew")
```

- [ ] **Step 4: Move live-analysis and Wet/Dry controls into an audition panel**

Delete the current live-analysis checkbutton and Wet/Dry scale from `_build_controls`:

```python
ttk.Checkbutton(
    frame, text="Live analysis (spectral feedback)",
    variable=self.live_var, command=self._on_live_toggle,
).grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))

ttk.Label(frame, text="Wet/Dry").grid(row=8, column=0, sticky="w")
ttk.Scale(
    frame, from_=0.0, to=1.0, variable=self.wet_dry_var,
    command=lambda _v: setattr(
        self.engine, "wet_dry", self.wet_dry_var.get()
    ),
).grid(row=8, column=1, columnspan=2, sticky="ew")
```

Change the Send button grid row from `row=9` to `row=6`:

```python
ttk.Button(frame, text="Send", command=self._on_send).grid(
    row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0)
)
```

Add this method to `RedPoleGUI` after `_build_controls`:

```python
def _build_audition_controls(self):
    frame = ttk.LabelFrame(self.root, text="Audition")
    frame.grid(row=2, column=0, sticky="new", padx=8, pady=(0, 8))

    ttk.Checkbutton(
        frame,
        text="Live analysis (spectral feedback)",
        variable=self.live_var,
        command=self._on_live_toggle,
    ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

    ttk.Label(frame, text="Wet/Dry").grid(row=1, column=0, sticky="w")
    ttk.Scale(
        frame,
        from_=0.0,
        to=1.0,
        variable=self.wet_dry_var,
        command=lambda _v: setattr(
            self.engine, "wet_dry", self.wet_dry_var.get()
        ),
    ).grid(row=1, column=1, columnspan=2, sticky="ew")

    frame.columnconfigure(1, weight=1)
```

Call it in `RedPoleGUI.__init__` immediately after `_build_controls()`:

```python
self._build_controls()
self._build_audition_controls()
self._build_layer_list()
```

- [ ] **Step 5: Shift layer-list grid row down**

In `_build_layer_list`, change:

```python
frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
```

to:

```python
frame.grid(row=3, column=0, sticky="nsew", padx=8, pady=8)
```

Keep the waveform frame at `row=0, column=1, rowspan=2`; this leaves the waveform stable while controls stack on the left.

- [ ] **Step 6: Verify removed references and compile GUI**

Run:

```bash
rg "reverb_var|text=\"Reverb\"" audio_prototype/gui.py
python -m py_compile audio_prototype/gui.py
```

Expected: `rg` returns no matches; `py_compile` exits successfully.

- [ ] **Step 7: Commit GUI cleanup**

Run:

```bash
git add audio_prototype/gui.py
git commit -m "feat: separate audition controls from scan input"
```

---

### Task 4: Full Verification

**Files:**
- Read/verify: all changed files

- [ ] **Step 1: Run focused processor tests**

Run:

```bash
python -m pytest audio_prototype/tests/test_wet_bus.py audio_prototype/tests/test_audio_engine.py audio_prototype/tests/test_spectral_processor.py -v
```

Expected: PASS, including the existing spectral harmonic-snapping tests.

- [ ] **Step 2: Run full test suite**

Run:

```bash
python -m pytest audio_prototype/tests -v
```

Expected: PASS.

- [ ] **Step 3: Compile all prototype Python files**

Run:

```bash
python -m compileall audio_prototype
```

Expected: all files compile successfully.

- [ ] **Step 4: Check worktree status**

Run:

```bash
git status --short
```

Expected: no uncommitted changes from this plan. Pre-existing uncommitted changes may still appear for `RED_POLE.toe`, `audio_prototype/spectral_processor.py`, and `audio_prototype/tests/test_spectral_processor.py` if they were present before execution and intentionally preserved.

## Self-Review

- Spec coverage: GUI Reverb removal and Wet/Dry relocation are covered in Task 3; live-analysis relocation is covered in Task 3; density-aware wet gain, tone cleanup, and reverb tightening are covered in Tasks 1 and 2; zero-layer and wet/dry behavior are protected in Task 2 and the existing tests; full verification is covered in Task 4.
- Completeness scan: every task has concrete commands, code, and expected results.
- Type consistency: `WetBusManager.controls()` returns the same dictionary as `density_controls()`, and `AudioEngine.wet_bus` is the single engine-facing helper used by tests and runtime code.
