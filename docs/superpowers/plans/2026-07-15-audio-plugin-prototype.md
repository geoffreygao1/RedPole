# RedPole Audio Plugin Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python prototype that simulates RedPole's finger-scan → color/BPM → looping-audio-modulation experience, with a GUI standing in for the hardware scanner and a live waveform visualizer.

**Architecture:** A real-time `sounddevice` output stream continuously plays a looped base audio file through a `TapeModulator` (organic wow/flutter pitch "warble" + noise-driven amplitude "bloom", both anchored to combined BPM/HSV from active layers). A thread-safe `LayerRegistry` holds one entry per "Send" from the Tkinter GUI; layers can be added and removed and take effect on the next audio block. A ring buffer feeds a Matplotlib waveform view that refreshes on a timer.

**Tech Stack:** Python 3.10+, numpy, soundfile, sounddevice, matplotlib, Tkinter (stdlib), pytest.

## Global Constraints

- Canonical sample rate is 44100 Hz everywhere in this prototype; loop files must already be at this sample rate — `AudioEngine.load_loop` raises `ValueError` on mismatch rather than resampling.
- Modulation depth/rate constants (defined in `modulation.py`): `MAX_WARBLE_DEPTH = 0.02`, `MAX_BLOOM_DEPTH = 0.6`, `PER_LAYER_MIN_WARBLE = 0.001`, `PER_LAYER_MAX_WARBLE = 0.004`, `PER_LAYER_MIN_BLOOM = 0.02`, `PER_LAYER_MAX_BLOOM = 0.12`.
- GUI framework is Tkinter + embedded Matplotlib (`FigureCanvasTkAgg`) — no other GUI toolkit.
- No ESP32/hardware integration, no spectral resynthesis, no persistence across restarts, no networking — all explicitly deferred per the design spec.
- All new code lives under `audio_prototype/` at the repo root, kept separate from the PlatformIO firmware in `src/`/`include/`/`lib/`.

---

### Task 1: Project scaffolding and default sample loop

**Files:**
- Create: `audio_prototype/requirements.txt`
- Create: `audio_prototype/conftest.py`
- Create: `audio_prototype/generate_sample_loop.py`
- Test: `audio_prototype/tests/test_generate_sample_loop.py`

**Interfaces:**
- Produces: `generate_sample_loop.generate_ambient_loop(samplerate=44100, duration=6.0) -> np.ndarray` (float32, seamless-loop sine pad); `generate_sample_loop.OUTPUT_PATH` (module-level `Path`); `generate_sample_loop.main()` (writes the loop to `OUTPUT_PATH`).

- [ ] **Step 1: Create the directory structure and requirements file**

Create `audio_prototype/requirements.txt`:

```text
numpy
soundfile
sounddevice
matplotlib
pytest
```

Create empty `audio_prototype/conftest.py` (this makes pytest add `audio_prototype/` itself to `sys.path`, so later test files can `import modulation`, `import layers`, etc. without packaging):

```python
# Intentionally empty: presence of this file makes pytest add this
# directory to sys.path so sibling test files can import top-level
# modules (modulation, layers, tape_modulator, ring_buffer, audio_engine).
```

- [ ] **Step 2: Write the failing test for the loop generator**

Create `audio_prototype/tests/test_generate_sample_loop.py`:

```python
import soundfile as sf

import generate_sample_loop as gen


def test_generate_ambient_loop_shape_and_range():
    loop = gen.generate_ambient_loop(samplerate=44100, duration=6.0)
    assert loop.dtype.kind == "f"
    assert len(loop) == 44100 * 6
    assert loop.max() <= 1.0
    assert loop.min() >= -1.0


def test_generate_ambient_loop_is_seamless():
    loop = gen.generate_ambient_loop(samplerate=44100, duration=6.0)
    # first and last sample should be close, so looping doesn't click
    assert abs(float(loop[0]) - float(loop[-1])) < 0.01


def test_main_writes_valid_wav(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "OUTPUT_PATH", tmp_path / "sample_loop.wav")
    gen.main()
    info = sf.info(str(tmp_path / "sample_loop.wav"))
    assert info.samplerate == 44100
    assert info.duration >= 5.9
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd audio_prototype && pip install -r requirements.txt && pytest tests/test_generate_sample_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'generate_sample_loop'`

- [ ] **Step 4: Implement the loop generator**

Create `audio_prototype/generate_sample_loop.py`:

```python
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 44100
DURATION_SECONDS = 6.0
OUTPUT_PATH = Path(__file__).parent / "assets" / "sample_loop.wav"

# Frequencies chosen so each completes a whole number of cycles over
# DURATION_SECONDS (220*6=1320, 277*6=1662, 330*6=1980), so the waveform
# and envelope both end exactly where they started -- a seamless loop.
_FREQUENCIES = [220.0, 277.0, 330.0]
_WEIGHTS = [0.5, 0.3, 0.2]


def generate_ambient_loop(samplerate=SAMPLE_RATE, duration=DURATION_SECONDS):
    n = int(samplerate * duration)
    t = np.arange(n) / samplerate
    cycle = 2.0 * np.pi * t / duration

    signal = np.zeros(n)
    for freq, weight in zip(_FREQUENCIES, _WEIGHTS):
        signal += weight * np.sin(2.0 * np.pi * freq * t)

    envelope = 0.6 + 0.4 * np.sin(cycle - np.pi / 2)
    signal *= envelope
    signal /= np.max(np.abs(signal))
    signal *= 0.7  # headroom
    return signal.astype(np.float32)


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    loop = generate_ambient_loop()
    sf.write(str(OUTPUT_PATH), loop, SAMPLE_RATE)
    print(f"Wrote {OUTPUT_PATH} ({len(loop) / SAMPLE_RATE:.1f}s @ {SAMPLE_RATE}Hz)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd audio_prototype && pytest tests/test_generate_sample_loop.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Generate the real bundled asset**

Run: `cd audio_prototype && python generate_sample_loop.py`
Expected: prints `Wrote .../assets/sample_loop.wav (6.0s @ 44100Hz)` and creates `audio_prototype/assets/sample_loop.wav`

- [ ] **Step 7: Commit**

```bash
git add audio_prototype/requirements.txt audio_prototype/conftest.py audio_prototype/generate_sample_loop.py audio_prototype/tests/test_generate_sample_loop.py audio_prototype/assets/sample_loop.wav
git commit -m "feat: scaffold audio prototype and generate default sample loop"
```

---

### Task 2: Pure modulation math (`modulation.py`)

**Files:**
- Create: `audio_prototype/modulation.py`
- Test: `audio_prototype/tests/test_modulation.py`

**Interfaces:**
- Consumes: nothing (pure functions, only `numpy`).
- Produces: `clamp(value, min_v, max_v) -> float`; `bpm_to_hz(bpm) -> float`; `hue_to_warble_depth(hue_norm) -> float`; `sat_val_to_bloom_depth(sat, val) -> float`; `combine_layers(layers: list[dict]) -> dict` with keys `warble_depth`, `bloom_depth`, `rate_hz`; `soft_clip(x, threshold=0.9) -> np.ndarray`. Constants: `MAX_WARBLE_DEPTH`, `MAX_BLOOM_DEPTH`, `PER_LAYER_MIN_WARBLE`, `PER_LAYER_MAX_WARBLE`, `PER_LAYER_MIN_BLOOM`, `PER_LAYER_MAX_BLOOM` (values in Global Constraints above).

- [ ] **Step 1: Write the failing tests**

Create `audio_prototype/tests/test_modulation.py`:

```python
import numpy as np
import pytest

import modulation as mod


def test_clamp():
    assert mod.clamp(5, 0, 10) == 5
    assert mod.clamp(-1, 0, 10) == 0
    assert mod.clamp(11, 0, 10) == 10


def test_bpm_to_hz():
    assert mod.bpm_to_hz(60) == pytest.approx(1.0)
    assert mod.bpm_to_hz(120) == pytest.approx(2.0)


def test_hue_to_warble_depth_bounds():
    assert mod.hue_to_warble_depth(0.0) == pytest.approx(mod.PER_LAYER_MIN_WARBLE)
    assert mod.hue_to_warble_depth(1.0) == pytest.approx(mod.PER_LAYER_MAX_WARBLE)
    mid = mod.hue_to_warble_depth(0.5)
    assert mod.PER_LAYER_MIN_WARBLE < mid < mod.PER_LAYER_MAX_WARBLE


def test_sat_val_to_bloom_depth_bounds():
    assert mod.sat_val_to_bloom_depth(0.0, 0.0) == pytest.approx(mod.PER_LAYER_MIN_BLOOM)
    assert mod.sat_val_to_bloom_depth(1.0, 1.0) == pytest.approx(mod.PER_LAYER_MAX_BLOOM)


def test_combine_layers_empty():
    combined = mod.combine_layers([])
    assert combined == {"warble_depth": 0.0, "bloom_depth": 0.0, "rate_hz": 0.0}


def test_combine_layers_sums_depth_and_averages_rate():
    layers = [
        {"hue": 1.0, "sat": 1.0, "val": 1.0, "bpm": 60.0},
        {"hue": 1.0, "sat": 1.0, "val": 1.0, "bpm": 120.0},
    ]
    combined = mod.combine_layers(layers)
    assert combined["warble_depth"] == pytest.approx(
        min(2 * mod.PER_LAYER_MAX_WARBLE, mod.MAX_WARBLE_DEPTH)
    )
    assert combined["bloom_depth"] == pytest.approx(
        min(2 * mod.PER_LAYER_MAX_BLOOM, mod.MAX_BLOOM_DEPTH)
    )
    assert combined["rate_hz"] == pytest.approx(1.5)  # average of 1.0 and 2.0 Hz


def test_combine_layers_clamps_depth_with_many_layers():
    layers = [{"hue": 1.0, "sat": 1.0, "val": 1.0, "bpm": 60.0} for _ in range(20)]
    combined = mod.combine_layers(layers)
    assert combined["warble_depth"] == pytest.approx(mod.MAX_WARBLE_DEPTH)
    assert combined["bloom_depth"] == pytest.approx(mod.MAX_BLOOM_DEPTH)


def test_soft_clip_leaves_small_values_untouched():
    x = np.array([-0.5, 0.0, 0.5, 0.89])
    np.testing.assert_allclose(mod.soft_clip(x, threshold=0.9), x)


def test_soft_clip_bounds_large_values():
    x = np.array([5.0, -5.0])
    y = mod.soft_clip(x, threshold=0.9)
    assert np.all(np.abs(y) < 1.0)
    assert np.all(np.abs(y) > 0.9)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd audio_prototype && pytest tests/test_modulation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'modulation'`

- [ ] **Step 3: Implement `modulation.py`**

Create `audio_prototype/modulation.py`:

```python
import numpy as np

MAX_WARBLE_DEPTH = 0.02
MAX_BLOOM_DEPTH = 0.6
PER_LAYER_MIN_WARBLE = 0.001
PER_LAYER_MAX_WARBLE = 0.004
PER_LAYER_MIN_BLOOM = 0.02
PER_LAYER_MAX_BLOOM = 0.12


def clamp(value, min_v, max_v):
    return max(min_v, min(max_v, value))


def bpm_to_hz(bpm):
    return bpm / 60.0


def hue_to_warble_depth(hue_norm):
    hue_norm = clamp(hue_norm, 0.0, 1.0)
    return PER_LAYER_MIN_WARBLE + hue_norm * (PER_LAYER_MAX_WARBLE - PER_LAYER_MIN_WARBLE)


def sat_val_to_bloom_depth(sat, val):
    sat = clamp(sat, 0.0, 1.0)
    val = clamp(val, 0.0, 1.0)
    avg = (sat + val) / 2.0
    return PER_LAYER_MIN_BLOOM + avg * (PER_LAYER_MAX_BLOOM - PER_LAYER_MIN_BLOOM)


def combine_layers(layers):
    if not layers:
        return {"warble_depth": 0.0, "bloom_depth": 0.0, "rate_hz": 0.0}

    warble_depth = clamp(
        sum(hue_to_warble_depth(l["hue"]) for l in layers), 0.0, MAX_WARBLE_DEPTH
    )
    bloom_depth = clamp(
        sum(sat_val_to_bloom_depth(l["sat"], l["val"]) for l in layers),
        0.0,
        MAX_BLOOM_DEPTH,
    )
    rate_hz = sum(bpm_to_hz(l["bpm"]) for l in layers) / len(layers)
    return {"warble_depth": warble_depth, "bloom_depth": bloom_depth, "rate_hz": rate_hz}


def soft_clip(x, threshold=0.9):
    """Identity below `threshold`; tanh-compresses toward +/-1 above it."""
    x = np.asarray(x)
    over = np.abs(x) > threshold
    compressed = np.sign(x) * (
        threshold + (1.0 - threshold) * np.tanh((np.abs(x) - threshold) / (1.0 - threshold))
    )
    return np.where(over, compressed, x)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd audio_prototype && pytest tests/test_modulation.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/modulation.py audio_prototype/tests/test_modulation.py
git commit -m "feat: add pure modulation math (depth mapping, combine, soft clip)"
```

---

### Task 3: Tape modulator DSP (`tape_modulator.py`)

**Files:**
- Create: `audio_prototype/tape_modulator.py`
- Test: `audio_prototype/tests/test_tape_modulator.py`

**Interfaces:**
- Consumes: `modulation.soft_clip` from Task 2.
- Produces: `TapeModulator(samplerate=44100, seed=None)` with method `process(loop_array: np.ndarray, frames: int, warble_depth: float, bloom_depth: float, rate_hz: float) -> np.ndarray` (float32, length `frames`), preserving internal state (`_read_pos`, `_wow_phase`, `_flutter_phase`, `_jitter_state`, `_bloom_state`) across calls.

- [ ] **Step 1: Write the failing tests**

Create `audio_prototype/tests/test_tape_modulator.py`:

```python
import numpy as np
import pytest

from tape_modulator import TapeModulator


def test_process_returns_requested_length():
    loop = np.linspace(-0.5, 0.5, 1000, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    out = tm.process(loop, frames=512, warble_depth=0.01, bloom_depth=0.1, rate_hz=1.0)
    assert out.shape == (512,)
    assert out.dtype == np.float32


def test_zero_depth_is_dry_passthrough():
    loop = np.linspace(-0.5, 0.5, 100, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    out = tm.process(loop, frames=25, warble_depth=0.0, bloom_depth=0.0, rate_hz=1.0)
    expected = loop[np.arange(25) % 100]
    np.testing.assert_allclose(out, expected, atol=1e-6)


def test_zero_depth_wraps_around_loop_boundary():
    loop = np.linspace(-0.5, 0.5, 10, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    out = tm.process(loop, frames=25, warble_depth=0.0, bloom_depth=0.0, rate_hz=1.0)
    expected = loop[np.arange(25) % 10]
    np.testing.assert_allclose(out, expected, atol=1e-6)


def test_read_position_persists_across_calls():
    loop = np.linspace(-0.5, 0.5, 10, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    first = tm.process(loop, frames=7, warble_depth=0.0, bloom_depth=0.0, rate_hz=1.0)
    second = tm.process(loop, frames=7, warble_depth=0.0, bloom_depth=0.0, rate_hz=1.0)
    combined = np.concatenate([first, second])
    expected = loop[np.arange(14) % 10]
    np.testing.assert_allclose(combined, expected, atol=1e-6)


def test_nonzero_warble_depth_changes_output():
    loop = np.sin(np.linspace(0, 20 * np.pi, 2000, dtype=np.float32))
    tm_dry = TapeModulator(samplerate=44100, seed=1)
    tm_wet = TapeModulator(samplerate=44100, seed=1)
    dry = tm_dry.process(loop, frames=1024, warble_depth=0.0, bloom_depth=0.0, rate_hz=1.5)
    wet = tm_wet.process(loop, frames=1024, warble_depth=0.02, bloom_depth=0.0, rate_hz=1.5)
    assert not np.allclose(dry, wet)


def test_output_stays_within_soft_clip_range():
    loop = np.ones(500, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    out = tm.process(loop, frames=500, warble_depth=0.02, bloom_depth=0.6, rate_hz=3.0)
    assert np.all(np.abs(out) < 1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd audio_prototype && pytest tests/test_tape_modulator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tape_modulator'`

- [ ] **Step 3: Implement `tape_modulator.py`**

Create `audio_prototype/tape_modulator.py`:

```python
import numpy as np

from modulation import soft_clip

SAMPLE_RATE_DEFAULT = 44100


class TapeModulator:
    """Applies organic, tape-like warble (pitch) and bloom (amplitude)
    modulation to samples read from a looping buffer.

    Rate (wow/flutter speed, bloom breathing speed) is anchored to the
    combined BPM (`rate_hz`); depth is anchored to combined HSV, already
    computed by `modulation.combine_layers` before calling `process`.
    """

    def __init__(self, samplerate=SAMPLE_RATE_DEFAULT, seed=None):
        self.samplerate = samplerate
        self._rng = np.random.default_rng(seed)
        self._read_pos = 0.0
        self._wow_phase = 0.0
        self._flutter_phase = 0.0
        self._jitter_state = 0.0
        self._bloom_state = 0.0

    def _one_pole_alpha(self, cutoff_hz):
        cutoff_hz = max(cutoff_hz, 1e-6)
        return float(np.exp(-2.0 * np.pi * cutoff_hz / self.samplerate))

    def _smoothed_noise(self, n, state, cutoff_hz):
        alpha = self._one_pole_alpha(cutoff_hz)
        raw = self._rng.uniform(-1.0, 1.0, size=n)
        out = np.empty(n, dtype=np.float64)
        prev = state
        for i in range(n):
            prev = alpha * prev + (1.0 - alpha) * raw[i]
            out[i] = prev
        return out, prev

    def process(self, loop_array, frames, warble_depth, bloom_depth, rate_hz):
        loop_len = len(loop_array)
        t = np.arange(frames) / self.samplerate

        # Wow: slow drift. Flutter: faster wobble. Both scaled by BPM-derived
        # rate_hz but kept in their natural physical ranges.
        wow_rate = 0.1 + 0.15 * rate_hz
        flutter_rate = 4.0 + 2.0 * rate_hz

        wow = np.sin(2.0 * np.pi * wow_rate * t + self._wow_phase)
        flutter = np.sin(2.0 * np.pi * flutter_rate * t + self._flutter_phase)
        jitter, self._jitter_state = self._smoothed_noise(
            frames, self._jitter_state, cutoff_hz=1.0 + rate_hz
        )

        self._wow_phase = (
            self._wow_phase + 2.0 * np.pi * wow_rate * frames / self.samplerate
        ) % (2.0 * np.pi)
        self._flutter_phase = (
            self._flutter_phase + 2.0 * np.pi * flutter_rate * frames / self.samplerate
        ) % (2.0 * np.pi)

        raw_warble = 0.6 * wow + 0.3 * flutter + 0.1 * jitter
        rate_per_sample = 1.0 + warble_depth * raw_warble

        # Exclusive prefix sum: the i-th output sample reads from the
        # position *before* applying increment i, so depth=0 (rate=1
        # everywhere) reproduces the loop exactly with no offset.
        cum = np.cumsum(rate_per_sample)
        positions = (self._read_pos + cum - rate_per_sample) % loop_len
        self._read_pos = float((self._read_pos + cum[-1]) % loop_len)

        idx0 = np.floor(positions).astype(np.int64) % loop_len
        idx1 = (idx0 + 1) % loop_len
        frac = positions - np.floor(positions)
        output = loop_array[idx0] * (1.0 - frac) + loop_array[idx1] * frac

        bloom_noise, self._bloom_state = self._smoothed_noise(
            frames, self._bloom_state, cutoff_hz=0.05 + 0.1 * rate_hz
        )
        gain = np.clip(1.0 + bloom_depth * bloom_noise, 0.05, 1.95)
        output = output * gain

        return soft_clip(output).astype(np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd audio_prototype && pytest tests/test_tape_modulator.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/tape_modulator.py audio_prototype/tests/test_tape_modulator.py
git commit -m "feat: add TapeModulator (wow/flutter warble + noise bloom)"
```

---

### Task 4: Layer registry (`layers.py`)

**Files:**
- Create: `audio_prototype/layers.py`
- Test: `audio_prototype/tests/test_layers.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `LayerRegistry()` with `add(hue, sat, val, bpm) -> int` (returns unique layer id), `remove(layer_id) -> None` (no-op if id absent), `snapshot() -> list[dict]` (each dict has keys `hue`, `sat`, `val`, `bpm`; safe to mutate the returned list without affecting the registry).

- [ ] **Step 1: Write the failing tests**

Create `audio_prototype/tests/test_layers.py`:

```python
import threading

from layers import LayerRegistry


def test_add_returns_unique_ids():
    reg = LayerRegistry()
    id1 = reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
    id2 = reg.add(hue=0.2, sat=0.6, val=0.6, bpm=80)
    assert id1 != id2


def test_snapshot_reflects_added_layers():
    reg = LayerRegistry()
    reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
    snap = reg.snapshot()
    assert len(snap) == 1
    assert snap[0] == {"hue": 0.1, "sat": 0.5, "val": 0.5, "bpm": 70}


def test_remove_deletes_only_that_layer():
    reg = LayerRegistry()
    id1 = reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
    id2 = reg.add(hue=0.2, sat=0.6, val=0.6, bpm=80)
    reg.remove(id1)
    snap = reg.snapshot()
    assert len(snap) == 1
    assert snap[0]["bpm"] == 80
    assert id2 is not None


def test_remove_unknown_id_is_noop():
    reg = LayerRegistry()
    reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
    reg.remove(9999)
    assert len(reg.snapshot()) == 1


def test_snapshot_is_a_copy():
    reg = LayerRegistry()
    reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
    snap = reg.snapshot()
    snap.append({"hue": 1, "sat": 1, "val": 1, "bpm": 1})
    assert len(reg.snapshot()) == 1


def test_concurrent_add_remove_does_not_crash():
    reg = LayerRegistry()

    def worker():
        for _ in range(50):
            layer_id = reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
            reg.snapshot()
            reg.remove(layer_id)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert reg.snapshot() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd audio_prototype && pytest tests/test_layers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'layers'`

- [ ] **Step 3: Implement `layers.py`**

Create `audio_prototype/layers.py`:

```python
import threading


class LayerRegistry:
    """Thread-safe registry of active 'sends' (color+BPM layers).

    The audio callback thread reads via snapshot() every block; the GUI
    thread mutates via add()/remove() on user action. All access goes
    through a single lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._layers = {}
        self._next_id = 1

    def add(self, hue, sat, val, bpm):
        with self._lock:
            layer_id = self._next_id
            self._next_id += 1
            self._layers[layer_id] = {"hue": hue, "sat": sat, "val": val, "bpm": bpm}
            return layer_id

    def remove(self, layer_id):
        with self._lock:
            self._layers.pop(layer_id, None)

    def snapshot(self):
        with self._lock:
            return [dict(layer) for layer in self._layers.values()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd audio_prototype && pytest tests/test_layers.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/layers.py audio_prototype/tests/test_layers.py
git commit -m "feat: add thread-safe LayerRegistry"
```

---

### Task 5: Ring buffer for the visualizer (`ring_buffer.py`)

**Files:**
- Create: `audio_prototype/ring_buffer.py`
- Test: `audio_prototype/tests/test_ring_buffer.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RingBuffer(capacity: int)` with `write(chunk: np.ndarray) -> None` and `read_latest(n: int) -> np.ndarray` (length `n`, most-recent samples last, zero-padded on the left if fewer than `n` samples have been written yet).

- [ ] **Step 1: Write the failing tests**

Create `audio_prototype/tests/test_ring_buffer.py`:

```python
import numpy as np

from ring_buffer import RingBuffer


def test_initial_read_is_zeros():
    rb = RingBuffer(capacity=10)
    np.testing.assert_array_equal(rb.read_latest(10), np.zeros(10, dtype=np.float32))


def test_write_smaller_than_capacity_is_right_aligned():
    rb = RingBuffer(capacity=10)
    rb.write(np.array([1, 2, 3], dtype=np.float32))
    expected = np.array([0, 0, 0, 0, 0, 0, 0, 1, 2, 3], dtype=np.float32)
    np.testing.assert_array_equal(rb.read_latest(10), expected)


def test_write_larger_than_capacity_keeps_last_capacity_samples():
    rb = RingBuffer(capacity=5)
    rb.write(np.arange(20, dtype=np.float32))
    np.testing.assert_array_equal(rb.read_latest(5), np.array([15, 16, 17, 18, 19], dtype=np.float32))


def test_multiple_writes_roll_forward():
    rb = RingBuffer(capacity=5)
    rb.write(np.array([1, 2, 3], dtype=np.float32))
    rb.write(np.array([4, 5, 6], dtype=np.float32))
    np.testing.assert_array_equal(rb.read_latest(5), np.array([2, 3, 4, 5, 6], dtype=np.float32))


def test_read_latest_fewer_than_capacity():
    rb = RingBuffer(capacity=5)
    rb.write(np.array([1, 2, 3, 4, 5], dtype=np.float32))
    np.testing.assert_array_equal(rb.read_latest(2), np.array([4, 5], dtype=np.float32))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd audio_prototype && pytest tests/test_ring_buffer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ring_buffer'`

- [ ] **Step 3: Implement `ring_buffer.py`**

Create `audio_prototype/ring_buffer.py`:

```python
import threading

import numpy as np


class RingBuffer:
    """Fixed-size rolling buffer of the most recent audio samples, for the
    waveform visualizer. Not used for playback -- only for display."""

    def __init__(self, capacity):
        self.capacity = capacity
        self._buffer = np.zeros(capacity, dtype=np.float32)
        self._lock = threading.Lock()

    def write(self, chunk):
        chunk = np.asarray(chunk, dtype=np.float32)
        n = len(chunk)
        with self._lock:
            if n >= self.capacity:
                self._buffer = chunk[-self.capacity :].copy()
            else:
                self._buffer = np.concatenate([self._buffer[n:], chunk])

    def read_latest(self, n):
        with self._lock:
            if n >= self.capacity:
                return self._buffer.copy()
            return self._buffer[-n:].copy()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd audio_prototype && pytest tests/test_ring_buffer.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/ring_buffer.py audio_prototype/tests/test_ring_buffer.py
git commit -m "feat: add RingBuffer for waveform visualizer"
```

---

### Task 6: Audio engine (`audio_engine.py`)

**Files:**
- Create: `audio_prototype/audio_engine.py`
- Test: `audio_prototype/tests/test_audio_engine.py`

**Interfaces:**
- Consumes: `layers.LayerRegistry`, `modulation.combine_layers`, `ring_buffer.RingBuffer`, `tape_modulator.TapeModulator` from Tasks 2-5; the bundled `audio_prototype/assets/sample_loop.wav` from Task 1 as a test fixture.
- Produces: `AudioEngine(samplerate=44100, blocksize=1024, seed=None)` with `.registry` (a `LayerRegistry`), `.visual_buffer` (a `RingBuffer`), `load_loop(path: str) -> None` (raises `ValueError` on sample-rate mismatch), `generate_block(frames: int) -> np.ndarray` (device-independent, used both by tests and by the real-time callback), `start() -> None` / `stop() -> None` (open/close the real `sounddevice.OutputStream`).

- [ ] **Step 1: Write the failing tests**

Create `audio_prototype/tests/test_audio_engine.py`:

```python
from pathlib import Path

import numpy as np
import pytest

from audio_engine import AudioEngine

SAMPLE_LOOP = Path(__file__).parent.parent / "assets" / "sample_loop.wav"


def test_load_loop_reads_bundled_sample():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    assert engine.loop_array is not None
    assert engine.loop_array.dtype == np.float32
    assert len(engine.loop_array) > 44100  # more than one second


def test_load_loop_rejects_mismatched_samplerate(tmp_path):
    import soundfile as sf

    bad_path = tmp_path / "wrong_rate.wav"
    sf.write(str(bad_path), np.zeros(1000, dtype=np.float32), 22050)
    engine = AudioEngine(samplerate=44100, seed=1)
    with pytest.raises(ValueError):
        engine.load_loop(str(bad_path))


def test_generate_block_requires_loaded_loop():
    engine = AudioEngine(seed=1)
    with pytest.raises(RuntimeError):
        engine.generate_block(512)


def test_generate_block_dry_matches_loop_with_no_layers():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)


def test_generate_block_changes_with_active_layer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    dry = engine.generate_block(1024)

    engine2 = AudioEngine(seed=1)
    engine2.load_loop(str(SAMPLE_LOOP))
    engine2.registry.add(hue=1.0, sat=1.0, val=1.0, bpm=120)
    wet = engine2.generate_block(1024)

    assert not np.allclose(dry, wet)


def test_generate_block_writes_to_visual_buffer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.generate_block(512)
    latest = engine.visual_buffer.read_latest(512)
    assert not np.allclose(latest, np.zeros(512))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd audio_prototype && pytest tests/test_audio_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'audio_engine'`

- [ ] **Step 3: Implement `audio_engine.py`**

Create `audio_prototype/audio_engine.py`:

```python
import soundfile as sf
import sounddevice as sd

from layers import LayerRegistry
from modulation import combine_layers
from ring_buffer import RingBuffer
from tape_modulator import TapeModulator

VISUALIZER_BUFFER_SECONDS = 2.0


class AudioEngine:
    def __init__(self, samplerate=44100, blocksize=1024, seed=None):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.registry = LayerRegistry()
        self.modulator = TapeModulator(samplerate=samplerate, seed=seed)
        self.visual_buffer = RingBuffer(int(samplerate * VISUALIZER_BUFFER_SECONDS))
        self.loop_array = None
        self._stream = None

    def load_loop(self, path):
        data, file_rate = sf.read(path, dtype="float32", always_2d=True)
        if file_rate != self.samplerate:
            raise ValueError(
                f"Loop file sample rate {file_rate} does not match engine "
                f"sample rate {self.samplerate}"
            )
        self.loop_array = data.mean(axis=1).astype("float32")

    def generate_block(self, frames):
        if self.loop_array is None:
            raise RuntimeError("No loop loaded; call load_loop() first")
        layers = self.registry.snapshot()
        combined = combine_layers(layers)
        block = self.modulator.process(
            self.loop_array,
            frames,
            combined["warble_depth"],
            combined["bloom_depth"],
            combined["rate_hz"],
        )
        self.visual_buffer.write(block)
        return block

    def _callback(self, outdata, frames, time_info, status):
        outdata[:, 0] = self.generate_block(frames)

    def start(self):
        self._stream = sd.OutputStream(
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            channels=1,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd audio_prototype && pytest tests/test_audio_engine.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/audio_engine.py audio_prototype/tests/test_audio_engine.py
git commit -m "feat: add AudioEngine tying modulator, registry, and ring buffer to sounddevice"
```

---

### Task 7: GUI (`gui.py`)

**Files:**
- Create: `audio_prototype/gui.py`

**Interfaces:**
- Consumes: `AudioEngine` instance from Task 6 (specifically `.registry.add/remove`, `.load_loop`, `.start`, `.visual_buffer.read_latest`).
- Produces: `RedPoleGUI(root: tk.Tk, engine: AudioEngine, default_loop_path: str)` — builds the full window (scan controls, active-layer list, waveform canvas) and starts the periodic waveform refresh.

This task's GUI code needs a display and audio device, so it is not covered by automated tests — verification is the manual checklist in Task 8. Still write it fully, no placeholders.

- [ ] **Step 1: Implement `gui.py`**

Create `audio_prototype/gui.py`:

```python
import colorsys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

WAVEFORM_WINDOW_SAMPLES = 4096
REFRESH_MS = 50


class RedPoleGUI:
    def __init__(self, root, engine, default_loop_path):
        self.root = root
        self.engine = engine
        self.root.title("RedPole Audio Prototype")
        self._layer_rows = {}

        self.hue_var = tk.DoubleVar(value=0.5)
        self.sat_var = tk.DoubleVar(value=0.7)
        self.val_var = tk.DoubleVar(value=0.7)
        self.bpm_var = tk.DoubleVar(value=70.0)

        self._build_controls()
        self._build_layer_list()
        self._build_waveform()
        self._load_initial_loop(default_loop_path)
        self._schedule_refresh()

    def _build_controls(self):
        frame = ttk.LabelFrame(self.root, text="Scan Input")
        frame.grid(row=0, column=0, sticky="new", padx=8, pady=8)

        ttk.Button(frame, text="Load Loop...", command=self._on_load_loop).grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        ttk.Label(frame, text="Hue").grid(row=1, column=0, sticky="w")
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.hue_var,
            command=lambda _: self._update_swatch(),
        ).grid(row=1, column=1, sticky="ew")

        ttk.Label(frame, text="Saturation").grid(row=2, column=0, sticky="w")
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.sat_var,
            command=lambda _: self._update_swatch(),
        ).grid(row=2, column=1, sticky="ew")

        ttk.Label(frame, text="Value").grid(row=3, column=0, sticky="w")
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.val_var,
            command=lambda _: self._update_swatch(),
        ).grid(row=3, column=1, sticky="ew")

        ttk.Label(frame, text="BPM").grid(row=4, column=0, sticky="w")
        ttk.Scale(frame, from_=40.0, to=180.0, variable=self.bpm_var).grid(
            row=4, column=1, sticky="ew"
        )

        self.swatch = tk.Canvas(frame, width=40, height=40, highlightthickness=1)
        self.swatch.grid(row=1, column=2, rowspan=3, padx=8)
        self._update_swatch()

        ttk.Button(frame, text="Send", command=self._on_send).grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )

    def _hue_to_rgb_hex(self, hue_norm):
        # Hue slider is normalized 0..1 across a red-only span (-10deg..+10deg
        # through 0deg), matching what the real finger-scan sensor can return.
        hue_degrees = (-10.0 + hue_norm * 20.0) % 360.0
        r, g, b = colorsys.hsv_to_rgb(
            hue_degrees / 360.0, self.sat_var.get(), self.val_var.get()
        )
        return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

    def _update_swatch(self):
        self.swatch.configure(bg=self._hue_to_rgb_hex(self.hue_var.get()))

    def _build_layer_list(self):
        frame = ttk.LabelFrame(self.root, text="Active Layers")
        frame.grid(row=1, column=0, sticky="new", padx=8, pady=8)
        self.layer_list_frame = frame

    def _build_waveform(self):
        frame = ttk.LabelFrame(self.root, text="Waveform")
        frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=8, pady=8)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

        fig = Figure(figsize=(5, 3))
        self.ax = fig.add_subplot(111)
        (self.line,) = self.ax.plot(np.zeros(WAVEFORM_WINDOW_SAMPLES))
        self.ax.set_ylim(-1.05, 1.05)
        self.ax.set_xticks([])

        self.canvas = FigureCanvasTkAgg(fig, master=frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _load_initial_loop(self, path):
        try:
            self.engine.load_loop(path)
            self.engine.start()
        except Exception as exc:
            messagebox.showerror("Failed to start audio", str(exc))

    def _on_load_loop(self):
        path = filedialog.askopenfilename(filetypes=[("WAV files", "*.wav")])
        if not path:
            return
        try:
            self.engine.load_loop(path)
        except Exception as exc:
            messagebox.showerror("Failed to load audio", str(exc))

    def _on_send(self):
        layer_id = self.engine.registry.add(
            hue=self.hue_var.get(),
            sat=self.sat_var.get(),
            val=self.val_var.get(),
            bpm=self.bpm_var.get(),
        )
        self._add_layer_row(layer_id, self.bpm_var.get())

    def _add_layer_row(self, layer_id, bpm):
        row = ttk.Frame(self.layer_list_frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=f"Layer {layer_id} (BPM {bpm:.0f})").pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(
            row, text="Remove", command=lambda: self._on_remove(layer_id, row)
        ).pack(side="right")
        self._layer_rows[layer_id] = row

    def _on_remove(self, layer_id, row):
        self.engine.registry.remove(layer_id)
        row.destroy()
        del self._layer_rows[layer_id]

    def _schedule_refresh(self):
        self._refresh_waveform()
        self.root.after(REFRESH_MS, self._schedule_refresh)

    def _refresh_waveform(self):
        data = self.engine.visual_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        self.line.set_ydata(data)
        self.canvas.draw_idle()
```

- [ ] **Step 2: Byte-compile check (no test suite for GUI code)**

Run: `cd audio_prototype && python -m py_compile gui.py`
Expected: no output, exit code 0

- [ ] **Step 3: Commit**

```bash
git add audio_prototype/gui.py
git commit -m "feat: add Tkinter GUI (scan controls, layer list, waveform view)"
```

---

### Task 8: Entry point and manual end-to-end verification

**Files:**
- Create: `audio_prototype/main.py`

**Interfaces:**
- Consumes: `AudioEngine` from Task 6, `RedPoleGUI` from Task 7, bundled `assets/sample_loop.wav` from Task 1.
- Produces: runnable prototype via `python main.py`.

- [ ] **Step 1: Implement `main.py`**

Create `audio_prototype/main.py`:

```python
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from audio_engine import AudioEngine
from gui import RedPoleGUI

DEFAULT_LOOP_PATH = Path(__file__).parent / "assets" / "sample_loop.wav"


def main():
    engine = AudioEngine()
    root = tk.Tk()
    try:
        RedPoleGUI(root, engine, str(DEFAULT_LOOP_PATH))
    except Exception as exc:
        messagebox.showerror("RedPole Audio Prototype", f"Failed to start: {exc}")
        sys.exit(1)
    root.mainloop()
    engine.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the full automated test suite**

Run: `cd audio_prototype && pytest -v`
Expected: all tests from Tasks 1-6 pass (31 passed)

- [ ] **Step 3: Manual end-to-end verification**

Run: `cd audio_prototype && python main.py`

Walk through and confirm each of these (matching the spec's Testing section):
1. Window opens, default sample loop plays audibly with no layers (dry, unmodulated).
2. Move Hue/Saturation/Value/BPM sliders, click "Send" — a row appears in "Active Layers" and the loop audibly gains a subtle organic warble/bloom (not a clean rhythmic effect).
3. Click "Send" 3-4 more times with different slider positions — the effect thickens/stacks further, still no harsh clipping or dropouts.
4. Click "Remove" on one layer — the effect audibly lessens and its row disappears.
5. Waveform view updates live and visibly reflects the modulated (not flat/dry) signal.
6. Use "Load Loop..." to pick a different WAV file at 44100 Hz — playback switches to it. Try a WAV at a different sample rate — confirm an error dialog appears rather than a crash.
7. Close the window — process exits cleanly (no hanging audio thread).

- [ ] **Step 4: Commit**

```bash
git add audio_prototype/main.py
git commit -m "feat: add entry point wiring engine and GUI together"
```

---

## Self-Review Notes

- **Spec coverage:** loop playback + looping (Task 6), Send/Remove layers (Tasks 4, 7), HSV→warble/bloom depth and BPM→rate mapping (Task 2), organic wow/flutter/noise character instead of clean LFO (Task 3), waveform visualizer (Tasks 5, 7), soft-clip/no-hard-clip guarantee (Tasks 2, 3), error handling for bad file / mismatched sample rate (Tasks 6, 7), manual test checklist mirrors the spec's Testing section (Task 8). Explicitly deferred items (tape wear, spectral resynthesis, hardware integration) are not implemented, matching the spec.
- **Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.
- **Type consistency:** `combine_layers` keys (`warble_depth`, `bloom_depth`, `rate_hz`) match `TapeModulator.process`'s parameter names throughout Tasks 2, 3, 6. `LayerRegistry` layer dict keys (`hue`, `sat`, `val`, `bpm`) match what `combine_layers`, `hue_to_warble_depth`, and `sat_val_to_bloom_depth` expect, and what `gui.py`'s `_on_send` passes to `registry.add`.
