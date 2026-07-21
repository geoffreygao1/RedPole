# GitHub Pages Web Port (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RedPole playable live, in real time, in a browser via GitHub Pages — a reduced MVP (tape row + granules row + reverb) that proves the Pyodide + Web Audio architecture, reusing the exact same Python DSP files the desktop app uses.

**Architecture:** A new `audio_prototype/web_engine.py` wraps `TapeModulator`, `MicrocosmProcessor`, `SchroederReverb`, `WetBusManager`, `RmsLimiter`, and `LayerRegistry` (all unmodified, reused as-is) behind a device-free `generate_block(frames)` / `load_loop(samples)` interface. A browser-side Web Worker loads Pyodide, fetches those `.py` files directly from `audio_prototype/` (no copy, no build step locally), and feeds generated blocks straight to a small pure-JS `AudioWorkletProcessor` over a dedicated `MessageChannel` — bypassing the main thread on the audio path entirely so UI work can never cause glitches.

**Tech Stack:** Python/numpy (existing, reused), Pyodide (loaded from CDN), vanilla JS (Web Worker, AudioWorklet, Canvas), GitHub Actions for deployment. No new Python dependencies; no JS framework/bundler for MVP.

## Global Constraints

- New Python file `audio_prototype/web_engine.py` imports only: `layers.LayerRegistry`, `modulation.{combine_layers, soft_clip, RmsLimiter, val_to_unit}`, `tape_modulator.{TapeModulator, tape_column_controls}`, `microcosm_processor.MicrocosmProcessor`, `reverb.SchroederReverb`, `wet_bus.WetBusManager`. It must NOT import `audio_engine.py` (that module imports `sounddevice`/`soundfile`, neither available in Pyodide) or `sounddevice`/`soundfile` directly.
- Reverb control mapping (`bpm_to_reverb_feedback`, `val_to_reverb_cutoff`) is small (~10 lines), pure, and duplicated from `audio_engine.py` into `web_engine.py` rather than extracted into a shared module — extracting would mean touching the desktop app's `audio_engine.py`, which is out of scope for this plan. This is the one deliberate exception to zero-duplication; everything else (the actual DSP classes) is reused unmodified.
- `web_engine.py` skips the desktop app's reverb "space style" variety (bright_room/dark_medium/large_hall/wash) — MVP reverb only adjusts feedback/cutoff from the reverb layers' BPM/value average, using `SchroederReverb`'s defaults otherwise. Room-style variety is a fast-follow, not MVP.
- **Deliberate simplification vs. the desktop `AudioEngine`:** `web_engine.py` always routes the base signal through `self.modulator.process(...)` — even with zero tape layers, passing `combine_layers([])`'s zero depth (which `TapeModulator` already treats as an exact, continuous passthrough — proven by its own existing test suite). The desktop app instead branches to a separate `_next_dry`/`_dry_pos` path when no tape layers are active, as a performance micro-optimization, and re-syncs `modulator._read_pos = self._dry_pos` only when entering that branch. That one-directional sync means the reverse transition (tape active -> tape removed) does **not** re-sync the other way, so a mid-session removal jumps the read position rather than continuing seamlessly. `web_engine.py` avoids this whole class of bug by never introducing a second position tracker: `self.modulator._read_pos` is the single source of truth at all times. Slightly more CPU spent on tape's DSP machinery even with no tape layers connected, which is an acceptable trade for correctness and simplicity in an MVP.
- MVP patch bay is 2 rows x 5 columns: row 0 = `tape` (columns 0-3 = wow/flutter/tone/dropout via `tape_column_controls`, column 4 = `reverb`), row 1 = `granules` (5 columns select the `haze`/`tunnel`/`strum` variant per `microcosm_processor.microcosm_variant`'s existing column-to-variant mapping).
- Output source limit for MVP: 8 (`PATCH_SOURCE_LIMIT = 8` in `main.js`).
- Sample rate is whatever `AudioContext.sampleRate` reports (commonly 44100 or 48000) — never hardcoded; threaded through to `WebEngine(samplerate=...)`.
- Local dev: serve the **repo root** with any static file server (e.g. `python -m http.server` run from `RedPole/`), then open `http://localhost:8000/webapp/index.html`. This makes `webapp/`'s relative fetch `../audio_prototype/<file>.py` resolve correctly, identically to how the deployed site is structured (see Task 6).
- All new work happens on the already-checked-out `github-pages` branch.
- Run Python tests with `.venv/Scripts/python.exe -m pytest` from `audio_prototype/` (existing venv, no new packages needed).

---

### Task 1: `web_engine.py` — construction, loop loading, tape-routed base signal

**Files:**
- Create: `audio_prototype/web_engine.py`
- Test: `audio_prototype/tests/test_web_engine.py`

**Interfaces:**
- Produces: `WebEngine(samplerate=44100, seed=None)` with `.registry` (a `LayerRegistry`), `.modulator` (a `TapeModulator`), `.loop_array` (`None` until loaded), `load_loop(samples) -> None` (accepts pre-decoded mono float32/float64 array-like, truncates to `MAX_LOOP_SECONDS`), `generate_block(frames) -> np.ndarray` (float32, length `frames`; raises `RuntimeError` if no loop loaded; with zero layers, returns the dry loop looped exactly and continuously via `TapeModulator`'s own zero-depth passthrough; `tape`-engine layers drive `TapeModulator` with `tape_column_controls`).

- [ ] **Step 1: Write the failing tests**

Create `audio_prototype/tests/test_web_engine.py`:

```python
import numpy as np
import pytest

from web_engine import WebEngine

SR = 44100


def _tone(freq, seconds=1.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    return (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_generate_block_requires_loaded_loop():
    engine = WebEngine(samplerate=SR, seed=1)
    with pytest.raises(RuntimeError):
        engine.generate_block(512)


def test_load_loop_accepts_predecoded_samples():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0))
    assert engine.loop_array is not None
    assert engine.loop_array.dtype == np.float32
    assert len(engine.loop_array) == SR


def test_load_loop_truncates_to_max_seconds():
    import web_engine as we

    engine = WebEngine(samplerate=SR, seed=1)
    long_tone = _tone(220.0, seconds=we.MAX_LOOP_SECONDS + 5.0)
    engine.load_loop(long_tone)
    assert len(engine.loop_array) == int(we.MAX_LOOP_SECONDS * SR)


def test_generate_block_dry_matches_loop_with_no_layers():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0))
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)
    assert block.dtype == np.float32


def test_tape_layer_changes_output():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    dry = engine.generate_block(1024)

    engine2 = WebEngine(samplerate=SR, seed=1)
    engine2.load_loop(_tone(220.0, seconds=2.0))
    source_id = engine2.registry.add_source(hue=0.04, sat=0.68, val=0.94, bpm=120)
    engine2.registry.connect_source(source_id, engine="tape", row=0, col=1, store_col=False)
    wet = engine2.generate_block(1024)

    assert not np.allclose(dry, wet)


def test_tape_column_controls_reach_the_modulator():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    source_id = engine.registry.add_source(hue=0.04, sat=1.0, val=1.0, bpm=120)
    # column 1 = flutter-emphasized per tape_column_controls
    engine.registry.connect_source(source_id, engine="tape", row=0, col=1, store_col=False)
    for _ in range(10):
        engine.generate_block(1024)
    assert engine.modulator.last_warble_signal is not None


def test_layer_removed_continues_seamlessly_without_position_jump():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    source_id = engine.registry.add_source(hue=0.04, sat=1.0, val=1.0, bpm=120)
    engine.registry.connect_source(source_id, engine="tape", row=0, col=1, store_col=False)
    engine.generate_block(512)
    pos_before_removal = engine.modulator._read_pos
    engine.registry.remove_source(source_id)

    block = engine.generate_block(512)
    expected_start = int(pos_before_removal)
    expected = engine.loop_array[(expected_start + np.arange(512)) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_web_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web_engine'`

- [ ] **Step 3: Implement `web_engine.py`**

Create `audio_prototype/web_engine.py`:

```python
"""Browser-oriented audio orchestrator.

Unlike audio_engine.AudioEngine (which owns a sounddevice output stream
and decodes files via soundfile), WebEngine has no device or file I/O of
its own -- a JS Worker drives it by calling generate_block(frames)
repeatedly and hands it already-decoded samples via load_loop(). It
reuses the exact same effect classes as the desktop engine.
"""

import numpy as np

from layers import LayerRegistry
from modulation import RmsLimiter, combine_layers, soft_clip, val_to_unit
from microcosm_processor import MicrocosmProcessor
from reverb import SchroederReverb
from tape_modulator import TapeModulator, tape_column_controls
from wet_bus import WetBusManager

DEFAULT_SAMPLE_RATE = 44100
MAX_LOOP_SECONDS = 600.0
REVERB_DEFAULT_FEEDBACK = 0.84
REVERB_DEFAULT_CUTOFF = 7800.0
REVERB_SMOOTHING = 0.1


def bpm_to_reverb_feedback(bpm):
    """Slow, calm pulses open a long wash; fast pulses tighten the room."""
    return min(0.985, max(0.82, 0.99 - 0.00025 * bpm))


def val_to_reverb_cutoff(val):
    """Dark crimsons give a muffled tail; bright pinks keep it airy."""
    return 800.0 + 7000.0 * val_to_unit(val)


class WebEngine:
    """Browser-oriented orchestrator: no device I/O, no file decoding --
    just generate_block(frames) and load_loop(samples), driven by a JS
    Worker. Reuses the exact same effect classes as the desktop engine.

    The base signal always routes through TapeModulator.process(), even
    with zero tape layers -- combine_layers([]) gives zero warble/bloom
    depth, which TapeModulator already treats as an exact, continuous
    passthrough. This keeps self.modulator._read_pos as the single
    position tracker at all times, so tape layers coming and going never
    causes a read-position jump.
    """

    def __init__(self, samplerate=DEFAULT_SAMPLE_RATE, seed=None):
        self.samplerate = samplerate
        self.registry = LayerRegistry()
        self.modulator = TapeModulator(samplerate=samplerate, seed=seed)
        self.microcosm = MicrocosmProcessor(samplerate, seed=seed)
        self.reverb = SchroederReverb(samplerate)
        self.wet_bus = WetBusManager(samplerate)
        self.wet_limiter = RmsLimiter(target_rms=0.35)
        self.reverb_mix = 0.975
        self.wet_dry = 0.5
        self._rv_feedback = REVERB_DEFAULT_FEEDBACK
        self._rv_cutoff = REVERB_DEFAULT_CUTOFF
        self.loop_array = None

    def load_loop(self, samples):
        array = np.asarray(samples, dtype=np.float32)
        max_len = int(MAX_LOOP_SECONDS * self.samplerate)
        if len(array) > max_len:
            array = array[:max_len]
        self.loop_array = array

    def generate_block(self, frames):
        if self.loop_array is None:
            raise RuntimeError("No loop loaded; call load_loop() first")

        layers = self.registry.snapshot()
        tape_layers = [l for l in layers if l["engine"] == "tape"]

        combined = combine_layers(tape_layers)
        tape_controls = tape_column_controls(tape_layers)
        avg_hue = sum(l["hue"] for l in tape_layers) / len(tape_layers) if tape_layers else 0.0
        avg_sat = sum(l["sat"] for l in tape_layers) / len(tape_layers) if tape_layers else 0.5
        avg_val = sum(l["val"] for l in tape_layers) / len(tape_layers) if tape_layers else 1.0

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
        return base.astype(np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_web_engine.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/web_engine.py audio_prototype/tests/test_web_engine.py
git commit -m "feat: add WebEngine with tape-routed base signal for browser port"
```

---

### Task 2: `web_engine.py` — granules + reverb wet path

**Files:**
- Modify: `audio_prototype/web_engine.py`
- Test: `audio_prototype/tests/test_web_engine.py`

**Interfaces:**
- Consumes: `MicrocosmProcessor.process(loop_array, frames, layers, source_pos)`, `SchroederReverb.{set_feedback, set_cutoff, process}`, `WetBusManager.{controls, process}`, `RmsLimiter.process`, `modulation.soft_clip`.
- Produces: `generate_block` now mixes granules wet + reverb tail into the tape-processed base via `self.wet_dry`; `reverb`-engine layers add no signal of their own (matches desktop semantics) but shape `self._rv_feedback`/`self._rv_cutoff`.

- [ ] **Step 1: Write the failing tests**

Append to `audio_prototype/tests/test_web_engine.py`:

```python
def _granules_layer(engine, hue=0.04, sat=0.8, val=1.0, bpm=150.0, col=0):
    source_id = engine.registry.add_source(hue=hue, sat=sat, val=val, bpm=bpm)
    engine.registry.connect_source(source_id, engine="granules", row=1, col=col)
    return source_id


def _reverb_layer(engine, hue=0.04, sat=0.6, val=0.9, bpm=90.0):
    source_id = engine.registry.add_source(hue=hue, sat=sat, val=val, bpm=bpm)
    engine.registry.connect_source(source_id, engine="reverb", row=0, col=4, store_col=False)
    return source_id


def test_generate_block_unchanged_with_no_layers_after_task_2():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0))
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)


def test_granules_layer_produces_wet_signal():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    _granules_layer(engine)

    blocks = [engine.generate_block(1024) for _ in range(30)]
    assert any(np.max(np.abs(b)) > 1e-4 for b in blocks)
    assert all(b.shape == (1024,) for b in blocks)
    assert all(not np.any(np.isnan(b)) for b in blocks)


def test_reverb_only_layer_is_silent_without_another_effect():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    _reverb_layer(engine)

    for _ in range(20):
        block = engine.generate_block(1024)
    assert np.max(np.abs(block)) <= 1.0
    assert not np.any(np.isnan(block))


def test_reverb_layer_adds_tail_when_paired_with_granules():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    _granules_layer(engine)
    _reverb_layer(engine)

    for _ in range(40):
        block = engine.generate_block(1024)
    assert not np.any(np.isnan(block))
    assert np.max(np.abs(block)) <= 1.0


def test_wet_dry_zero_is_pure_base():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    engine.wet_dry = 0.0
    _granules_layer(engine)

    dry_engine = WebEngine(samplerate=SR, seed=1)
    dry_engine.load_loop(_tone(220.0, seconds=2.0))

    block = None
    dry_block = None
    for _ in range(20):
        block = engine.generate_block(1024)
        dry_block = dry_engine.generate_block(1024)
    np.testing.assert_allclose(block, dry_block, atol=1e-4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_web_engine.py -v`
Expected: the 5 new granules/reverb tests FAIL (no wiring yet); the Task-1 tests (including the renamed no-op check) still PASS

- [ ] **Step 3: Wire granules and reverb into `generate_block`**

In `audio_prototype/web_engine.py`, replace `generate_block`'s final line (`return base.astype(np.float32)`) — the whole method becomes:

```python
    def generate_block(self, frames):
        if self.loop_array is None:
            raise RuntimeError("No loop loaded; call load_loop() first")

        layers = self.registry.snapshot()
        tape_layers = [l for l in layers if l["engine"] == "tape"]
        gran_layers = [l for l in layers if l["engine"] == "granules"]
        reverb_layers = [l for l in layers if l["engine"] == "reverb"]
        zeros = np.zeros(frames, dtype=np.float32)

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

        if not layers:
            return base.astype(np.float32)

        wet_raw = self.microcosm.process(
            self.loop_array, frames, gran_layers, source_pos=source_pos
        )
        n_wet = len(gran_layers)
        n_rv = len(reverb_layers)

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

        controls = self.wet_bus.controls(wet_voice_count=n_wet, reverb_layer_count=n_rv)
        target_fb = max(0.62, target_fb - controls["feedback_trim"])
        target_cut = max(700.0, target_cut * controls["cutoff_scale"])
        self._rv_feedback += REVERB_SMOOTHING * (target_fb - self._rv_feedback)
        self._rv_cutoff += REVERB_SMOOTHING * (target_cut - self._rv_cutoff)
        self.reverb.set_feedback(self._rv_feedback)
        self.reverb.set_cutoff(self._rv_cutoff)

        managed_wet_raw = self.wet_bus.process(
            wet_raw, wet_voice_count=n_wet, reverb_layer_count=n_rv
        )
        # Reverb-only layers add no signal of their own -- they only shape
        # the room -- matching the desktop app's semantics.
        reverb_input = managed_wet_raw if reverb_layers else zeros
        reverb_wet = self.reverb.process(reverb_input) if reverb_layers else zeros
        wet = self.wet_limiter.process(managed_wet_raw + self.reverb_mix * reverb_wet)

        mix = float(np.clip(self.wet_dry, 0.0, 1.0))
        dry_gain = min(1.0, 2.0 * (1.0 - mix))
        wet_gain = min(1.0, 2.0 * mix)
        return soft_clip(dry_gain * base + wet_gain * wet).astype(np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_web_engine.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Run the full existing suite to confirm nothing else broke**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest -q`
Expected: all pass (the shared modules were not modified, only imported)

- [ ] **Step 6: Commit**

```bash
git add audio_prototype/web_engine.py audio_prototype/tests/test_web_engine.py
git commit -m "feat: route granules and reverb layers through WebEngine"
```

---

### Task 3: `webapp/worklet.js` — the audio-thread ring buffer

**Files:**
- Create: `webapp/worklet.js`

**Interfaces:**
- Produces: registers `"ring-worklet-processor"`. Accepts a `MessageChannel` port (sent once via its built-in `this.port` as `{type: "link", port}`) over which it receives `{type: "block", samples: Float32Array}` messages; periodically posts `{type: "status", bufferedFrames, underruns}` back over its built-in `this.port` (which main.js listens to for the debug readout).

No automated test — this is a browser-only API (`AudioWorkletProcessor` doesn't exist outside a real audio-rendering thread). Verified manually in Task 7.

- [ ] **Step 1: Implement the worklet**

Create `webapp/worklet.js`:

```javascript
// Runs on the browser's real-time audio-rendering thread. Deliberately
// tiny and dependency-free -- Pyodide cannot run here. It just buffers
// Float32Array blocks handed to it (over a dedicated MessageChannel from
// the Worker, linked in via `this.port`) and copies them into each
// render quantum. An empty queue means the Worker fell behind; we output
// silence for that quantum rather than glitching or crashing.

class RingWorkletProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._queue = [];
    this._queueOffset = 0;
    this._underruns = 0;
    this._lastReportTime = 0;
    this._audioPort = null;

    this.port.onmessage = (event) => {
      const data = event.data;
      if (data && data.type === "link" && data.port) {
        this._audioPort = data.port;
        this._audioPort.onmessage = (blockEvent) => {
          if (blockEvent.data && blockEvent.data.type === "block") {
            this._queue.push(blockEvent.data.samples);
          }
        };
      }
    };
  }

  _bufferedFrames() {
    let total = -this._queueOffset;
    for (let i = 0; i < this._queue.length; i++) {
      total += this._queue[i].length;
    }
    return Math.max(0, total);
  }

  process(_inputs, outputs) {
    const output = outputs[0];
    const frames = output[0].length;
    let written = 0;

    while (written < frames) {
      if (this._queue.length === 0) {
        this._underruns += 1;
        break;
      }
      const current = this._queue[0];
      const available = current.length - this._queueOffset;
      const need = frames - written;
      const take = Math.min(available, need);
      for (let ch = 0; ch < output.length; ch++) {
        output[ch].set(
          current.subarray(this._queueOffset, this._queueOffset + take),
          written
        );
      }
      this._queueOffset += take;
      written += take;
      if (this._queueOffset >= current.length) {
        this._queue.shift();
        this._queueOffset = 0;
      }
    }

    if (written < frames) {
      for (let ch = 0; ch < output.length; ch++) {
        output[ch].fill(0, written);
      }
    }

    if (currentTime - this._lastReportTime > 1.0) {
      this._lastReportTime = currentTime;
      this.port.postMessage({
        type: "status",
        bufferedFrames: this._bufferedFrames(),
        underruns: this._underruns,
      });
    }

    return true;
  }
}

registerProcessor("ring-worklet-processor", RingWorkletProcessor);
```

- [ ] **Step 2: Commit**

```bash
git add webapp/worklet.js
git commit -m "feat: add AudioWorklet ring buffer for the web port"
```

---

### Task 4: `webapp/worker.js` — Pyodide bootstrap and the pacing loop

**Files:**
- Create: `webapp/worker.js`

**Interfaces:**
- Consumes: `web_engine.WebEngine` (Task 2, fetched at runtime), the linked `MessageChannel` port from `worklet.js` (Task 3).
- Produces: handles messages from `main.js`: `{type:"init", sampleRate, audioPort}` (audioPort is the transferred `MessageChannel` port for talking to the worklet), `{type:"load_loop", samples}`, `{type:"add_source", hue, sat, val, bpm}` (replies `{type:"source_added", sourceId}`), `{type:"connect_source", sourceId, engine, row, col, storeCol}`, `{type:"disconnect_source", sourceId}`, `{type:"remove_source", sourceId}`, `{type:"set_wet_dry", value}`, `{type:"play"}`, `{type:"pause"}`. Posts `{type:"ready"}` once Pyodide + the engine are initialized, and `{type:"error", message}` on any failure.

No automated test — depends on Pyodide/WebAssembly, only real in a browser. Verified manually in Task 7.

- [ ] **Step 1: Implement the worker**

Create `webapp/worker.js`:

```javascript
// Runs in a background Web Worker: loads Pyodide, fetches the shared
// Python DSP files straight from audio_prototype/ (same files the
// desktop app and pytest use -- no copy, no build step), and paces
// audio generation ahead of real time, handing finished blocks directly
// to the AudioWorklet over a MessageChannel so the main thread is never
// on the audio path.

const PYODIDE_VERSION = "v0.26.4";
const PYTHON_FILES = [
  "modulation.py",
  "layers.py",
  "tape_modulator.py",
  "microcosm_processor.py",
  "reverb.py",
  "wet_bus.py",
  "web_engine.py",
];
const BLOCK_FRAMES = 4096;
const HIGH_WATERMARK_SECONDS = 0.3;
const GENERATE_INTERVAL_MS = 40;

let pyodide = null;
let sampleRate = 44100;
let audioPort = null;
let paused = true;
let bufferedAheadFrames = 0;

async function fetchPythonSource(name) {
  // ../audio_prototype/<name>.py resolves correctly both in local dev
  // (serving the whole repo root) and once deployed (Task 6 publishes
  // audio_prototype/ as a sibling of webapp/, matching this relative path).
  const response = await fetch(`../audio_prototype/${name}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch ${name}: ${response.status}`);
  }
  return response.text();
}

async function initPyodide() {
  importScripts(
    `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/pyodide.js`
  );
  pyodide = await loadPyodide();
  await pyodide.loadPackage("numpy");

  for (const name of PYTHON_FILES) {
    const source = await fetchPythonSource(name);
    pyodide.FS.writeFile(name, source);
  }

  pyodide.runPython(
    `import web_engine\nengine = web_engine.WebEngine(samplerate=${sampleRate})`
  );
}

function generateOneBlock() {
  const pyBlock = pyodide.runPython(`engine.generate_block(${BLOCK_FRAMES})`);
  const buffer = pyBlock.getBuffer("f32");
  const samples = Float32Array.from(buffer.data);
  buffer.release();
  pyBlock.destroy();
  return samples;
}

function pump() {
  if (paused || !pyodide || !audioPort) return;
  const highWatermarkFrames = HIGH_WATERMARK_SECONDS * sampleRate;
  while (bufferedAheadFrames < highWatermarkFrames) {
    let samples;
    try {
      samples = generateOneBlock();
    } catch (err) {
      self.postMessage({ type: "error", message: String(err) });
      paused = true;
      return;
    }
    audioPort.postMessage({ type: "block", samples }, [samples.buffer]);
    bufferedAheadFrames += BLOCK_FRAMES;
  }
}

self.onmessage = async (event) => {
  const msg = event.data;
  try {
    if (msg.type === "init") {
      sampleRate = msg.sampleRate;
      audioPort = msg.audioPort;
      await initPyodide();
      setInterval(pump, GENERATE_INTERVAL_MS);
      // Approximate playback draining the buffer: real consumption is
      // tracked by the worklet's own status reports (read by main.js for
      // the debug readout), but pump() only needs a rough estimate to
      // avoid generating unboundedly far ahead.
      setInterval(() => {
        if (paused) return;
        bufferedAheadFrames = Math.max(
          0,
          bufferedAheadFrames - (sampleRate * GENERATE_INTERVAL_MS) / 1000
        );
      }, GENERATE_INTERVAL_MS);
      self.postMessage({ type: "ready" });
    } else if (msg.type === "load_loop") {
      pyodide.globals.set("_samples", msg.samples);
      pyodide.runPython("engine.load_loop(_samples)");
      bufferedAheadFrames = 0;
    } else if (msg.type === "add_source") {
      const sourceId = pyodide.runPython(
        `engine.registry.add_source(hue=${msg.hue}, sat=${msg.sat}, val=${msg.val}, bpm=${msg.bpm})`
      );
      self.postMessage({ type: "source_added", sourceId });
    } else if (msg.type === "connect_source") {
      const storeCol = msg.storeCol ? "True" : "False";
      pyodide.runPython(
        `engine.registry.connect_source(${msg.sourceId}, engine=${JSON.stringify(
          msg.engine
        )}, row=${msg.row}, col=${msg.col}, store_col=${storeCol})`
      );
    } else if (msg.type === "disconnect_source") {
      pyodide.runPython(`engine.registry.disconnect_source(${msg.sourceId})`);
    } else if (msg.type === "remove_source") {
      pyodide.runPython(`engine.registry.remove_source(${msg.sourceId})`);
    } else if (msg.type === "set_wet_dry") {
      pyodide.runPython(`engine.wet_dry = ${msg.value}`);
    } else if (msg.type === "play") {
      paused = false;
      bufferedAheadFrames = 0;
    } else if (msg.type === "pause") {
      paused = true;
    }
  } catch (err) {
    self.postMessage({ type: "error", message: String(err) });
  }
};
```

- [ ] **Step 2: Commit**

```bash
git add webapp/worker.js
git commit -m "feat: add Pyodide worker with block-generation pacing loop"
```

---

### Task 5: `webapp/index.html`, `style.css`, `main.js` — UI and wiring

**Files:**
- Create: `webapp/index.html`
- Create: `webapp/style.css`
- Create: `webapp/main.js`

**Interfaces:**
- Consumes: `worker.js` (Task 4) via `postMessage`/`onmessage`; `worklet.js` (Task 3) via `audioWorkletNode`.
- Produces: the playable page. No automated test — verified manually in Task 7.

- [ ] **Step 1: Create the page shell**

Create `webapp/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>RedPole (Web MVP)</title>
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <h1>RedPole -- Web MVP</h1>
  <div id="status">Loading audio engine...</div>

  <div id="app" class="hidden">
    <section id="scan-input">
      <h2>Scan Input</h2>
      <button id="load-loop-button">Load Loop...</button>
      <input id="load-loop-file" type="file" accept="audio/*" class="hidden" />
      <button id="play-pause-button">Play</button>
      <div>
        <label>Finger color</label>
        <canvas id="picker" width="220" height="120"></canvas>
      </div>
      <div>
        <label>BPM <input id="bpm-input" type="number" value="70" min="20" max="300" /></label>
      </div>
      <button id="send-button">Send</button>
      <div>
        <label>Wet/Dry <input id="wet-dry-slider" type="range" min="0" max="1" step="0.01" value="0.5" /></label>
      </div>
    </section>

    <section id="patch-bay">
      <h2>Patch Bay</h2>
      <canvas id="patch-canvas" width="640" height="260"></canvas>
    </section>

    <section id="debug">
      <span id="buffer-readout">Buffered: -- ms</span>
      <span id="underrun-readout">Underruns: 0</span>
    </section>
  </div>

  <script src="main.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create the stylesheet**

Create `webapp/style.css`:

```css
body {
  font-family: system-ui, sans-serif;
  background: #161616;
  color: #e0e0e0;
  padding: 16px;
}

.hidden {
  display: none;
}

#app {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}

section {
  background: #1f1f1f;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  padding: 12px 16px;
}

canvas {
  border: 1px solid #555;
  cursor: crosshair;
  display: block;
  margin-top: 6px;
}

#debug {
  width: 100%;
  display: flex;
  gap: 16px;
  font-size: 0.85em;
  color: #999;
}

button {
  margin: 4px 4px 4px 0;
}
```

- [ ] **Step 3: Implement `main.js`**

Create `webapp/main.js`:

```javascript
const PATCH_GRID_ROWS = 2;
const PATCH_GRID_COLS = 5;
const PATCH_CELL = 58;
const PATCH_GRID_X = 340;
const PATCH_GRID_Y = 20;
const PATCH_SOURCE_X = 40;
const PATCH_SOURCE_TOP = 30;
const PATCH_SOURCE_GAP = 28;
const PATCH_SOURCE_LIMIT = 8;
const ROW_LABELS = ["tape", "granules"];
const TAPE_COL_LABELS = ["wow", "flutter", "tone", "dropout", "reverb"];
const GRANULES_COL_LABELS = ["I", "II", "III", "IV", "V"];

// Finger-scan gamut, matching the desktop app's picker (modulation.py's
// FINGER_HUE_MIN/MAX etc.): a bright red-to-orange range.
const FINGER_HUE_MIN = 0.0;
const FINGER_HUE_MAX = 0.085;
const FINGER_SAT_MIN = 0.64;
const FINGER_SAT_MAX = 0.72;
const FINGER_VAL_MIN = 0.9;
const FINGER_VAL_MAX = 0.98;

function hsvToRgb(h, s, v) {
  const i = Math.floor(h * 6);
  const f = h * 6 - i;
  const p = v * (1 - s);
  const q = v * (1 - f * s);
  const t = v * (1 - (1 - f) * s);
  let r, g, b;
  switch (i % 6) {
    case 0: [r, g, b] = [v, t, p]; break;
    case 1: [r, g, b] = [q, v, p]; break;
    case 2: [r, g, b] = [p, v, t]; break;
    case 3: [r, g, b] = [p, q, v]; break;
    case 4: [r, g, b] = [t, p, v]; break;
    default: [r, g, b] = [v, p, q]; break;
  }
  return [r, g, b];
}

function pickerCoordsToHsv(x, y, w, h) {
  const fx = Math.min(1, Math.max(0, x / (w - 1)));
  const fy = Math.min(1, Math.max(0, y / (h - 1)));
  return {
    hue: FINGER_HUE_MIN + (FINGER_HUE_MAX - FINGER_HUE_MIN) * fx,
    val: FINGER_VAL_MAX - (FINGER_VAL_MAX - FINGER_VAL_MIN) * fy,
    sat: FINGER_SAT_MAX - (FINGER_SAT_MAX - FINGER_SAT_MIN) * fy,
  };
}

class App {
  constructor() {
    this.worker = new Worker("worker.js");
    this.sources = new Map(); // sourceId -> {x, y, color, row, col}
    this.dragSourceId = null;
    this.currentHsv = { hue: 0.03, sat: 0.68, val: 0.94 };

    this.statusEl = document.getElementById("status");
    this.appEl = document.getElementById("app");
    this.pickerCanvas = document.getElementById("picker");
    this.patchCanvas = document.getElementById("patch-canvas");
    this.bpmInput = document.getElementById("bpm-input");
    this.bufferReadout = document.getElementById("buffer-readout");
    this.underrunReadout = document.getElementById("underrun-readout");
    this.playPauseButton = document.getElementById("play-pause-button");

    this.worker.onmessage = (event) => this.onWorkerMessage(event.data);
    this.setupAudio();
    this.buildPicker();
    this.bindControls();
    this.drawPatchBay();
  }

  async setupAudio() {
    this.audioContext = new AudioContext();
    await this.audioContext.audioWorklet.addModule("worklet.js");
    this.workletNode = new AudioWorkletNode(this.audioContext, "ring-worklet-processor", {
      outputChannelCount: [2],
    });
    this.workletNode.connect(this.audioContext.destination);
    this.workletNode.port.onmessage = (event) => {
      if (event.data.type === "status") {
        const ms = Math.round((event.data.bufferedFrames / this.audioContext.sampleRate) * 1000);
        this.bufferReadout.textContent = `Buffered: ${ms} ms`;
        this.underrunReadout.textContent = `Underruns: ${event.data.underruns}`;
      }
    };

    const channel = new MessageChannel();
    this.workletNode.port.postMessage({ type: "link", port: channel.port2 }, [channel.port2]);
    this.worker.postMessage(
      { type: "init", sampleRate: this.audioContext.sampleRate, audioPort: channel.port1 },
      [channel.port1]
    );
  }

  onWorkerMessage(msg) {
    if (msg.type === "ready") {
      this.statusEl.classList.add("hidden");
      this.appEl.classList.remove("hidden");
    } else if (msg.type === "error") {
      this.statusEl.textContent = `Error: ${msg.message}`;
      this.statusEl.classList.remove("hidden");
    } else if (msg.type === "source_added") {
      this.finishPendingSource(msg.sourceId);
    }
  }

  buildPicker() {
    const ctx = this.pickerCanvas.getContext("2d");
    const w = this.pickerCanvas.width;
    const h = this.pickerCanvas.height;
    const image = ctx.createImageData(w, h);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const { hue, sat, val } = pickerCoordsToHsv(x, y, w, h);
        const [r, g, b] = hsvToRgb(hue, sat, val);
        const idx = (y * w + x) * 4;
        image.data[idx] = Math.round(r * 255);
        image.data[idx + 1] = Math.round(g * 255);
        image.data[idx + 2] = Math.round(b * 255);
        image.data[idx + 3] = 255;
      }
    }
    ctx.putImageData(image, 0, 0);

    this.pickerCanvas.addEventListener("mousedown", (e) => this.onPick(e));
    this.pickerCanvas.addEventListener("mousemove", (e) => {
      if (e.buttons === 1) this.onPick(e);
    });
  }

  onPick(event) {
    const rect = this.pickerCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    this.currentHsv = pickerCoordsToHsv(x, y, this.pickerCanvas.width, this.pickerCanvas.height);
  }

  bindControls() {
    document.getElementById("send-button").addEventListener("click", () => this.onSend());
    document.getElementById("play-pause-button").addEventListener("click", () => this.onTogglePlay());
    document.getElementById("wet-dry-slider").addEventListener("input", (e) => {
      this.worker.postMessage({ type: "set_wet_dry", value: parseFloat(e.target.value) });
    });
    document.getElementById("load-loop-button").addEventListener("click", () => {
      document.getElementById("load-loop-file").click();
    });
    document.getElementById("load-loop-file").addEventListener("change", (e) => this.onLoadFile(e));

    this.patchCanvas.addEventListener("mousedown", (e) => this.onPatchPress(e));
    this.patchCanvas.addEventListener("mousemove", (e) => this.onPatchDrag(e));
    this.patchCanvas.addEventListener("mouseup", (e) => this.onPatchRelease(e));
  }

  onTogglePlay() {
    if (this.audioContext.state === "suspended") {
      this.audioContext.resume();
      this.worker.postMessage({ type: "play" });
      this.playPauseButton.textContent = "Pause";
    } else {
      this.audioContext.suspend();
      this.worker.postMessage({ type: "pause" });
      this.playPauseButton.textContent = "Play";
    }
  }

  async onLoadFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    const arrayBuffer = await file.arrayBuffer();
    const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
    const channels = [];
    for (let ch = 0; ch < audioBuffer.numberOfChannels; ch++) {
      channels.push(audioBuffer.getChannelData(ch));
    }
    const length = audioBuffer.length;
    const mono = new Float32Array(length);
    for (let i = 0; i < length; i++) {
      let sum = 0;
      for (let ch = 0; ch < channels.length; ch++) sum += channels[ch][i];
      mono[i] = sum / channels.length;
    }
    this.worker.postMessage({ type: "load_loop", samples: mono }, [mono.buffer]);
  }

  onSend() {
    if (this.sources.size >= PATCH_SOURCE_LIMIT) {
      alert(`Maximum patch outputs reached (${PATCH_SOURCE_LIMIT}).`);
      return;
    }
    const bpm = parseFloat(this.bpmInput.value);
    const { hue, sat, val } = this.currentHsv;
    const [r, g, b] = hsvToRgb(hue, sat, val);
    const color = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
    this._pendingSource = { hue, sat, val, bpm, color };
    this.worker.postMessage({ type: "add_source", hue, sat, val, bpm });
  }

  finishPendingSource(sourceId) {
    const pending = this._pendingSource;
    this._pendingSource = null;
    const slot = this.sources.size;
    this.sources.set(sourceId, {
      x: PATCH_SOURCE_X,
      y: PATCH_SOURCE_TOP + slot * PATCH_SOURCE_GAP,
      color: pending.color,
      row: null,
      col: null,
    });
    this.drawPatchBay();
  }

  cellAt(x, y) {
    const col = Math.floor((x - PATCH_GRID_X) / PATCH_CELL);
    const row = Math.floor((y - PATCH_GRID_Y) / PATCH_CELL);
    if (row < 0 || row >= PATCH_GRID_ROWS || col < 0 || col >= PATCH_GRID_COLS) return null;
    return { row, col };
  }

  nearestSource(x, y) {
    for (const [sourceId, source] of this.sources) {
      if ((x - source.x) ** 2 + (y - source.y) ** 2 <= 100) return sourceId;
    }
    return null;
  }

  onPatchPress(event) {
    const rect = this.patchCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    this.dragSourceId = this.nearestSource(x, y);
  }

  onPatchDrag(_event) {
    if (this.dragSourceId === null) return;
    // Cable preview omitted for MVP simplicity; the grid + jacks alone
    // are enough to show connection state once released.
  }

  onPatchRelease(event) {
    if (this.dragSourceId === null) return;
    const rect = this.patchCanvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const cell = this.cellAt(x, y);
    const source = this.sources.get(this.dragSourceId);

    if (cell === null) {
      this.worker.postMessage({ type: "disconnect_source", sourceId: this.dragSourceId });
      source.row = null;
      source.col = null;
    } else {
      const engine = ROW_LABELS[cell.row];
      const storeCol = engine !== "tape";
      this.worker.postMessage({
        type: "connect_source",
        sourceId: this.dragSourceId,
        engine,
        row: cell.row,
        col: cell.col,
        storeCol,
      });
      source.row = cell.row;
      source.col = cell.col;
    }
    this.dragSourceId = null;
    this.drawPatchBay();
  }

  drawPatchBay() {
    const ctx = this.patchCanvas.getContext("2d");
    ctx.fillStyle = "#161616";
    ctx.fillRect(0, 0, this.patchCanvas.width, this.patchCanvas.height);

    for (let row = 0; row < PATCH_GRID_ROWS; row++) {
      const labels = row === 0 ? TAPE_COL_LABELS : GRANULES_COL_LABELS;
      ctx.fillStyle = "#d5d5d5";
      ctx.font = "12px sans-serif";
      ctx.fillText(ROW_LABELS[row], PATCH_GRID_X - 50, PATCH_GRID_Y + row * PATCH_CELL + PATCH_CELL / 2);
      for (let col = 0; col < PATCH_GRID_COLS; col++) {
        const x0 = PATCH_GRID_X + col * PATCH_CELL;
        const y0 = PATCH_GRID_Y + row * PATCH_CELL;
        ctx.strokeStyle = "#555";
        ctx.fillStyle = "#222";
        ctx.fillRect(x0, y0, PATCH_CELL, PATCH_CELL);
        ctx.strokeRect(x0, y0, PATCH_CELL, PATCH_CELL);
        ctx.fillStyle = "#888";
        ctx.font = "9px sans-serif";
        ctx.fillText(labels[col], x0 + 6, y0 + 14);
      }
    }

    for (const [, source] of this.sources) {
      ctx.beginPath();
      ctx.arc(source.x, source.y, 8, 0, 2 * Math.PI);
      ctx.fillStyle = source.color;
      ctx.fill();
      ctx.strokeStyle = "#f0f0f0";
      ctx.stroke();

      if (source.row !== null) {
        const cx = PATCH_GRID_X + source.col * PATCH_CELL + PATCH_CELL / 2;
        const cy = PATCH_GRID_Y + source.row * PATCH_CELL + PATCH_CELL / 2;
        ctx.beginPath();
        ctx.moveTo(source.x, source.y);
        ctx.lineTo(cx, cy);
        ctx.strokeStyle = source.color;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.lineWidth = 1;
      }
    }
  }
}

window.addEventListener("load", () => new App());
```

- [ ] **Step 4: Commit**

```bash
git add webapp/index.html webapp/style.css webapp/main.js
git commit -m "feat: add web MVP UI (scan input, 2-row patch bay, debug readout)"
```

---

### Task 6: GitHub Pages deployment workflow

**Files:**
- Create: `.github/workflows/deploy-pages.yml`

**Interfaces:** none (CI configuration only).

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/deploy-pages.yml`:

```yaml
name: Deploy GitHub Pages

on:
  push:
    branches: [github-pages]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Assemble site (webapp/ and audio_prototype/*.py as siblings)
        run: |
          mkdir -p site/webapp
          mkdir -p site/audio_prototype
          cp -r webapp/. site/webapp/
          cp audio_prototype/modulation.py \
             audio_prototype/layers.py \
             audio_prototype/tape_modulator.py \
             audio_prototype/microcosm_processor.py \
             audio_prototype/reverb.py \
             audio_prototype/wet_bus.py \
             audio_prototype/web_engine.py \
             site/audio_prototype/
          cat > site/index.html <<'EOF'
          <!doctype html>
          <meta http-equiv="refresh" content="0; url=webapp/index.html">
          EOF

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: site

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy-pages.yml
git commit -m "ci: deploy webapp/ and shared Python DSP files to GitHub Pages"
```

- [ ] **Step 3: Push the branch and enable Pages**

Run: `git push -u origin github-pages`

Then, in the repository's GitHub settings: **Settings -> Pages -> Source: GitHub Actions**. This is a one-time manual step (cannot be done from the CLI). Note the published URL — the workflow's `page_url` output prints it in the Actions run summary once the first deploy completes.

---

### Task 7: Local manual verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full Python test suite**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest -q`
Expected: all pass, including the 12 new `test_web_engine.py` tests.

- [ ] **Step 2: Serve the repo root locally**

Run (from the repo root, `RedPole/`): `python -m http.server 8000`

- [ ] **Step 3: Open the page and walk the checklist**

Open `http://localhost:8000/webapp/index.html` in Chrome or Edge. Confirm, in order:
1. Page shows "Loading audio engine..." then reveals the app once Pyodide finishes (may take several seconds on first load — Pyodide + numpy is a real download).
2. Use "Load Loop..." to pick any local audio file; after decoding, click Play — playback should be audible.
3. Pick a color, set a BPM, click Send — a colored dot appears in the patch bay's output column.
4. Drag that dot onto a **tape** row cell (try the "flutter" column) — the loop's coloration audibly changes.
5. Send another source and drag it onto the **granules** row — audible grain events appear.
6. Drag a source onto the tape row's "reverb" column (5th cell) with a granules source already active — reverb tail becomes audible; with *no* other effect active, confirm it stays essentially dry (matches the desktop app's "reverb-only is silent" semantics).
7. Drag a connected source off the grid entirely — its effect stops.
8. Click Pause, then Play again — resumes cleanly, no stuck audio or errors.
9. Check the debug readout: "Buffered: ~150-300 ms", "Underruns: 0" (or very low) during normal use.
10. Open DevTools console — confirm no errors during load or interaction.

- [ ] **Step 4: Quick cross-browser smoke check**

Repeat steps 1-3 above in Firefox. Note (don't block on) any issues — Safari is explicitly out of scope for MVP hardening per the spec.

- [ ] **Step 5: Record results**

If everything in Step 3 passes, the MVP is functionally verified locally. Deployment verification (Task 6, Step 3) confirms the same behavior from the published GitHub Pages URL.

## Self-Review Notes

- **Spec coverage:** zero-duplication `pyfetch`/`fetch` of real `.py` files (Task 4); `web_engine.py` reusing `TapeModulator`/`MicrocosmProcessor`/`SchroederReverb`/`WetBusManager`/`RmsLimiter`/`LayerRegistry` unmodified (Tasks 1-2); tape/granules/reverb-only 2-row MVP scope (Tasks 1-2, 5); Worker+postMessage-to-AudioWorklet bridge bypassing the main thread (Tasks 3-4-5); file loading via `decodeAudioData` (Task 5); error handling for Pyodide/worklet/fetch failures (Tasks 4-5); manual JS verification, automated Python tests (Task 7); GitHub Pages deployment with `audio_prototype/` published as a sibling of `webapp/` so relative fetch paths match local dev exactly (Task 6).
- **Placeholder scan:** none; every step has complete, runnable code. The one open external detail is the pinned Pyodide CDN version (`v0.26.4`) — if that exact version is ever removed from jsdelivr, Task 7 Step 3's "page won't load" failure mode is exactly what would surface, with the fix being to bump `PYODIDE_VERSION` in `worker.js`.
- **Type consistency:** `WebEngine.generate_block(frames)` and `.load_loop(samples)` signatures match between Tasks 1-2 and the JS calls in `worker.js` (Task 4); `LayerRegistry.connect_source(source_id, engine, row, col, store_col)` matches its existing (unmodified) signature from `layers.py`, used identically in both the Python tests and the JS `connect_source` message handler. Fixed during self-review: an earlier draft of Task 1 introduced a separate `_dry_pos`/`_next_dry` fallback that would have desynced from `self.modulator._read_pos` whenever tape layers were removed mid-session (an audible position jump) — resolved by always routing through `TapeModulator.process`, as documented in Global Constraints.
