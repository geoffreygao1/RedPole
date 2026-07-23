# Synth Patch-Bay Redesign + CPU Headroom Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the desktop Synth tab's button grids with a Loop/webapp-style drag-cable patch bay (two 5×5 jack grids, source→transform cables), and remove the audio clicks/glitching by decoupling synth audio from the GIL-bound callback and lightening the waveform.

**Architecture:** (1) `SynthAudioEngine` switches from `sd.OutputStream(callback=…)` to a producer thread + blocking `stream.write()` at `latency="high"`, so PortAudio's C thread plays from a filled buffer and a UI GIL stall no longer underruns. (2) The synth waveform becomes a lightweight `tk.Canvas` polyline (downsampled, active-tab-only) instead of a matplotlib figure. (3) `ResonantPulseSource` gets an exact-semantics silent early-out. (4) `SynthTab` is rewritten to a canvas drag-cable bay reusing the Loop tab's cable geometry.

**Tech Stack:** Python 3.11 + NumPy + Tkinter/ttk + `sounddevice` (blocking write mode) + `threading`; pytest. No new dependencies.

## Global Constraints

- **Run tests from `audio_prototype/` with `py -3.11`** (tkinter-capable): `py -3.11 -m pytest tests/<file> -v`. The PlatformIO-embedded `python` lacks tkinter and cannot collect Tk tests.
- **Do not change Loop-tab audio or UI.** Only `gui.py` change permitted is none in this plan (the synth tab is built via `synth_tab.SynthTab`, unchanged interface). Do not touch `audio_engine.py`, `layers.py`, `crowd.py`, `web_engine.py`, `webapp/`.
- **No new third-party dependencies.** NumPy-only DSP.
- **Preserve public import surface:** `synth_tab.source_preset_id`, `transform_preset_id`, `ROOT_NOTE_CHOICES`, `parse_bpm` stay importable; `SynthAudioEngine.connect_patch/disconnect_patch/active_patches/generate_block/generate_stereo_block/load_sample/load_sample_array/set_root_midi/root_midi/visual_buffer` keep their signatures.
- **Tk widget tests use a display guard:** construct `tk.Tk()` in a `try/except tk.TclError: pytest.skip(...)`, `root.withdraw()`, and always `root.destroy()` in a `finally`. On this Windows machine a display exists so they run.
- **Threads must not leak in tests:** every test that calls `resume()` must call `stop()` before returning.
- Commit messages end with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer. Use plain `git`. Stage only each task's listed files. After each task's commit, check off that task's `- [ ]` boxes in this plan file and include that edit in the same commit.

## File Structure

**Modify:**
- `audio_prototype/soundscape_sources.py` — `ResonantPulseSource.render` silent early-out (Task 1).
- `audio_prototype/synth_audio_engine.py` — producer-thread + blocking-write lifecycle (Task 2).
- `audio_prototype/synth_tab.py` — new bay geometry helpers (Task 3); `SynthTab` widget rewrite (Task 4).
- `audio_prototype/tests/test_soundscape_sources.py` — resonant early-out tests (Task 1).
- `audio_prototype/tests/test_synth_audio_engine.py` — replace stream-lifecycle tests (Task 2).
- `audio_prototype/tests/test_synth_tab.py` — geometry tests (Task 3), widget tests replaced (Task 4).
- `AGENTS.md` — refresh "Pick up here" (Task 5).

---

## Task 1: `ResonantPulseSource` silent early-out

**Files:**
- Modify: `audio_prototype/soundscape_sources.py` (`ResonantPulseSource.render`)
- Test: `audio_prototype/tests/test_soundscape_sources.py`

**Interfaces:**
- Consumes/produces: unchanged public signature `render(vid, assignment, bpm, frames, preset) -> np.ndarray`. Behavior change: blocks with no pulse and fully-decayed state (`max(|y1|,|y2|) < 1e-6`) return exact zeros without running the per-sample loop.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_soundscape_sources.py


def test_resonant_silent_blocks_are_exact_zero_between_pulses():
    src = ResonantPulseSource(44100, seed=3)
    assignment = _assignment()
    # slow BPM -> long gaps between pulses; render enough blocks to pass a ring
    saw_pulse_energy = False
    saw_exact_zero_block = False
    for _ in range(400):
        block = src.render(1, assignment, 40.0, 1024, RESONANT_PRESETS[0])
        peak = float(np.max(np.abs(block)))
        if peak > 1e-3:
            saw_pulse_energy = True
        if saw_pulse_energy and peak == 0.0:
            saw_exact_zero_block = True
    assert saw_pulse_energy       # pulses still fire and ring
    assert saw_exact_zero_block   # rung-out gaps are skipped to exact zero


def test_resonant_ring_is_not_prematurely_zeroed():
    src = ResonantPulseSource(44100, seed=3)
    assignment = _assignment()
    # the block right after the first pulse must be non-zero (ring not skipped)
    first_pulse_block = None
    for _ in range(200):
        block = src.render(1, assignment, 40.0, 1024, RESONANT_PRESETS[0])
        if float(np.max(np.abs(block))) > 1e-3:
            first_pulse_block = block
            break
    assert first_pulse_block is not None
    next_block = src.render(1, assignment, 40.0, 1024, RESONANT_PRESETS[0])
    # immediately after a pulse the resonator is still ringing well above 1e-6
    assert float(np.max(np.abs(next_block))) > 1e-6
```

- [x] **Step 2: Run test to verify it fails**

Run: `py -3.11 -m pytest tests/test_soundscape_sources.py -k resonant_silent -v`
Expected: FAIL — `test_resonant_silent_blocks_are_exact_zero_between_pulses` fails because the current loop returns tiny non-zero values (never exactly `0.0`) in the rung-out gaps.

- [x] **Step 3: Write minimal implementation**

In `soundscape_sources.py`, inside `ResonantPulseSource.render`, locate the block that currently reads:

```python
        pulse_interval = max(1, int(self.samplerate * 60.0 / max(20.0, bpm)))
        out = np.zeros(frames, dtype=np.float64)
        y1, y2 = voice["y1"], voice["y2"]
        rng = voice["rng"]
        next_pulse = voice["next_pulse"]
        for i in range(frames):
```

and insert the early-out **between** the `next_pulse = voice["next_pulse"]` line and the `for i in range(frames):` line, so that section becomes:

```python
        pulse_interval = max(1, int(self.samplerate * 60.0 / max(20.0, bpm)))
        out = np.zeros(frames, dtype=np.float64)
        y1, y2 = voice["y1"], voice["y2"]
        rng = voice["rng"]
        next_pulse = voice["next_pulse"]
        # Silent early-out: between the sparse pulses the resonators ring out
        # within tens of ms and then sit at (numerically) zero for hundreds of
        # ms. When no pulse fires this block and the state has fully decayed,
        # skip the per-sample loop -- the samples it would produce are already
        # below 1e-6, so returning exact zeros is behaviour-preserving.
        rung_out = max(
            float(np.max(np.abs(y1))), float(np.max(np.abs(y2)))
        ) < 1e-6
        if next_pulse >= frames and rung_out:
            voice["next_pulse"] = next_pulse - frames
            return out
        for i in range(frames):
```

Leave the rest of the method (the loop body, state write-back, and peak normalization) exactly as-is.

- [x] **Step 4: Run test to verify it passes**

Run: `py -3.11 -m pytest tests/test_soundscape_sources.py -v`
Expected: PASS — the two new tests plus every existing `test_soundscape_sources` test (audible/bounded/deterministic/voice-dropped) unchanged.

- [x] **Step 5: Commit**

```bash
git add audio_prototype/soundscape_sources.py audio_prototype/tests/test_soundscape_sources.py
git commit -m "perf(soundscape): skip resonant per-sample loop when rung out and no pulse

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `SynthAudioEngine` producer thread + blocking write

**Files:**
- Modify: `audio_prototype/synth_audio_engine.py`
- Test: `audio_prototype/tests/test_synth_audio_engine.py`

**Interfaces:**
- Consumes: `sounddevice` (`sd.OutputStream(... latency="high")` in blocking/write mode), `threading`, `time`.
- Produces: same public methods. `__init__` default `blocksize=2048`. `resume()` opens the stream (if needed), starts it, and launches a daemon producer thread that renders blocks and calls `stream.write()`. `pause()` sets `_paused` (producer writes silence, stream stays open). `stop()` stops the producer and closes the stream. Removes `_callback`.

- [x] **Step 1: Write the failing test**

Replace the existing stream-lifecycle tests in `tests/test_synth_audio_engine.py` (the ones named `_fake_stream_factory`, `test_starts_paused_and_opens_no_stream`, `test_resume_opens_and_starts_stream`, `test_pause_stops_without_closing`, `test_stop_closes_stream`, `test_callback_fills_outdata_stereo`) with the following. Keep every other test in the file unchanged.

```python
import time


class _FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.writes = 0
        self.started = False
        self.closed = False
        self.last = None

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    def write(self, block):
        self.writes += 1
        self.last = np.array(block)
        time.sleep(0.001)


def _install_fake_stream(monkeypatch):
    created = {}

    def factory(**kwargs):
        stream = _FakeStream(**kwargs)
        created["stream"] = stream
        return stream

    monkeypatch.setattr("synth_audio_engine.sd.OutputStream", factory)
    return created


def test_start_while_paused_opens_no_stream(monkeypatch):
    created = _install_fake_stream(monkeypatch)
    eng = SynthAudioEngine(seed=1)
    eng.start()
    assert eng.paused is True
    assert "stream" not in created
    assert eng._stream is None


def test_resume_opens_high_latency_stream_and_produces(monkeypatch):
    created = _install_fake_stream(monkeypatch)
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    eng.resume()
    time.sleep(0.05)
    eng.stop()
    stream = created["stream"]
    assert stream.kwargs.get("latency") == "high"
    assert stream.kwargs.get("channels") == 2
    assert stream.writes > 0
    assert stream.closed is True
    assert eng._running is False


def test_pause_writes_silence_but_keeps_stream_open(monkeypatch):
    created = _install_fake_stream(monkeypatch)
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    eng.resume()
    time.sleep(0.03)
    eng.pause()
    time.sleep(0.05)
    stream = created["stream"]
    assert eng.paused is True
    assert stream.closed is False
    # the most recent block written while paused is silent
    assert float(np.max(np.abs(stream.last))) == 0.0
    eng.stop()


def test_stop_joins_producer_and_closes(monkeypatch):
    created = _install_fake_stream(monkeypatch)
    eng = SynthAudioEngine(seed=1)
    eng.resume()
    time.sleep(0.02)
    eng.stop()
    assert eng._running is False
    assert eng._producer is None
    assert created["stream"].closed is True


def test_produces_stereo_blocks(monkeypatch):
    created = _install_fake_stream(monkeypatch)
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    eng.resume()
    time.sleep(0.05)
    eng.stop()
    assert created["stream"].last.shape[1] == 2
```

- [x] **Step 2: Run test to verify it fails**

Run: `py -3.11 -m pytest tests/test_synth_audio_engine.py -k "resume_opens_high_latency or pause_writes_silence or stop_joins or produces_stereo or start_while_paused" -v`
Expected: FAIL — `AttributeError: 'SynthAudioEngine' object has no attribute '_running'` (and the fake stream has no `write` calls because the current engine is callback-based).

- [x] **Step 3: Write minimal implementation**

In `synth_audio_engine.py`: add `import time` next to `import threading`. In `__init__`, change the default and add producer fields — replace the signature line and add two fields:

```python
    def __init__(self, samplerate=44100, blocksize=2048, seed=None, root_midi=62):
```

and after the existing `self._paused = True` line add:

```python
        self._running = False
        self._producer = None
```

Then replace the entire `# ---------- stream lifecycle ----------` section (from `@property def paused` down through `stop`) with:

```python
    # ---------- stream lifecycle ----------

    @property
    def paused(self):
        return self._paused

    def _open_stream(self):
        # Blocking/write mode (no callback): PortAudio pulls audio in its own
        # C thread from a large internal buffer (latency="high"), so a GIL
        # stall on the Tk/main thread delays the producer's next write() but
        # does not underrun playback. This removes the callback-needs-the-GIL
        # glitch that a matplotlib redraw could trigger.
        self._stream = sd.OutputStream(
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            channels=2,
            latency="high",
        )

    def _run_producer(self):
        silence = np.zeros((self.blocksize, 2), dtype=np.float32)
        while self._running:
            block = (
                self.generate_stereo_block(self.blocksize)
                if not self._paused
                else silence
            )
            try:
                self._stream.write(block)
            except Exception:
                # A closed/aborted stream during shutdown, or a transient
                # backend error, must not kill the producer loop.
                if not self._running:
                    break

    def start(self):
        # Mirrors the prior contract: start() while paused opens nothing.
        if not self._paused:
            self.resume()

    def resume(self):
        self._paused = False
        if self._stream is None:
            self._open_stream()
        self._stream.start()
        if not self._running:
            self._running = True
            self._producer = threading.Thread(target=self._run_producer, daemon=True)
            self._producer.start()

    def pause(self):
        # Keep the stream + producer alive but feed silence, so playback stays
        # glitch-free and resumes instantly.
        self._paused = True

    def stop(self):
        self._running = False
        if self._producer is not None:
            self._producer.join(timeout=1.0)
            self._producer = None
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
```

Delete the old `_callback` method entirely.

- [x] **Step 4: Run test to verify it passes**

Run: `py -3.11 -m pytest tests/test_synth_audio_engine.py -v`
Expected: PASS — the new lifecycle tests plus all retained `generate_block`/`load_sample`/`set_root_midi` tests.

- [x] **Step 5: Commit**

```bash
git add audio_prototype/synth_audio_engine.py audio_prototype/tests/test_synth_audio_engine.py
git commit -m "fix(synth): render audio on a producer thread with blocking write for headroom

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Patch-bay geometry helpers

**Files:**
- Modify: `audio_prototype/synth_tab.py` (add pure helpers near the top, before the widget code)
- Test: `audio_prototype/tests/test_synth_tab.py`

**Interfaces:**
- Consumes: `SYNTH_GRID_SIZE` (existing).
- Produces: constants `SYNTH_CANVAS_W`, `SYNTH_CANVAS_H`, `SYNTH_CELL`, `SYNTH_JACK_RADIUS`, `SYNTH_SOURCE_ORIGIN`, `SYNTH_TRANSFORM_ORIGIN`, `SYNTH_PATCH_LIMIT`, `WAVEFORM_POINTS`; functions `source_cell_center(row,col)`, `transform_cell_center(row,col)`, `source_cell_at(x,y)`, `transform_cell_at(x,y)`.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_synth_tab.py
from synth_tab import (
    SYNTH_GRID_SIZE as _GRID,
    source_cell_at,
    source_cell_center,
    transform_cell_at,
    transform_cell_center,
)


def test_source_cell_center_round_trips_through_cell_at():
    for r in range(_GRID):
        for c in range(_GRID):
            cx, cy = source_cell_center(r, c)
            assert source_cell_at(cx, cy) == (r, c)


def test_transform_cell_center_round_trips_through_cell_at():
    for r in range(_GRID):
        for c in range(_GRID):
            cx, cy = transform_cell_center(r, c)
            assert transform_cell_at(cx, cy) == (r, c)


def test_cell_at_returns_none_outside_grids():
    assert source_cell_at(-50, -50) is None
    assert transform_cell_at(0, 0) is None            # left of the transform grid
    assert source_cell_at(*transform_cell_center(0, 0)) is None  # transform area is not source


def test_source_grid_is_left_of_transform_grid():
    assert source_cell_center(0, _GRID - 1)[0] < transform_cell_center(0, 0)[0]
```

- [x] **Step 2: Run test to verify it fails**

Run: `py -3.11 -m pytest tests/test_synth_tab.py -k "cell_center or cell_at or left_of" -v`
Expected: FAIL — `ImportError: cannot import name 'source_cell_center'`.

- [x] **Step 3: Write minimal implementation**

In `synth_tab.py`, immediately after the `parse_bpm` function (and before the `import colorsys`/widget section), add:

```python
# ---- patch-bay geometry (pure; unit-tested without Tk) ----

SYNTH_CANVAS_W = 980
SYNTH_CANVAS_H = 380
SYNTH_CELL = 56
SYNTH_JACK_RADIUS = 9
SYNTH_SOURCE_ORIGIN = (90, 60)       # (x, y) top-left of the source grid
SYNTH_TRANSFORM_ORIGIN = (620, 60)   # (x, y) top-left of the transform grid
SYNTH_PATCH_LIMIT = 25
WAVEFORM_POINTS = 480
VARIANT_LABELS = ("I", "II", "III", "IV", "V")   # per-column preset variant labels


def _cell_center(origin, row, col):
    ox, oy = origin
    return (ox + col * SYNTH_CELL + SYNTH_CELL / 2, oy + row * SYNTH_CELL + SYNTH_CELL / 2)


def _cell_at(origin, x, y):
    ox, oy = origin
    if x < ox or y < oy:
        return None
    col = int((x - ox) // SYNTH_CELL)
    row = int((y - oy) // SYNTH_CELL)
    if 0 <= row < SYNTH_GRID_SIZE and 0 <= col < SYNTH_GRID_SIZE:
        return (row, col)
    return None


def source_cell_center(row, col):
    return _cell_center(SYNTH_SOURCE_ORIGIN, row, col)


def transform_cell_center(row, col):
    return _cell_center(SYNTH_TRANSFORM_ORIGIN, row, col)


def source_cell_at(x, y):
    return _cell_at(SYNTH_SOURCE_ORIGIN, x, y)


def transform_cell_at(x, y):
    return _cell_at(SYNTH_TRANSFORM_ORIGIN, x, y)
```

- [x] **Step 4: Run test to verify it passes**

Run: `py -3.11 -m pytest tests/test_synth_tab.py -k "cell_center or cell_at or left_of" -v`
Expected: PASS (4 tests). (The button-widget tests from the previous plan may still exist and will be replaced in Task 4 — ignore their state here; run only the `-k` subset.)

- [x] **Step 5: Commit**

```bash
git add audio_prototype/synth_tab.py audio_prototype/tests/test_synth_tab.py
git commit -m "feat(synth): add two-grid patch-bay geometry helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Rewrite `SynthTab` as a drag-cable patch bay + Tk-canvas waveform

**Files:**
- Modify: `audio_prototype/synth_tab.py` (replace everything from the `import colorsys` widget section onward)
- Test: `audio_prototype/tests/test_synth_tab.py` (replace the button-widget tests)

**Interfaces:**
- Consumes: Task 3 geometry helpers, `source_preset_id`/`transform_preset_id`/`parse_bpm`/`ROOT_NOTE_CHOICES` (existing), `gui._picker_coords_to_hsv`/`_random_scan_values`/`_patch_cable_points`/`PICKER_W`/`PICKER_H`, `SynthAudioEngine` (passed in).
- Produces: `class SynthTab(parent, synth_engine)` with a canvas bay (`self.bay`), drag handlers `_on_press`/`_on_drag`/`_on_release`, `_connect(source_cell, transform_cell)`, `_remove_patch(pid)`, patch state `self._patches`, and a `tk.Canvas` waveform refreshed only while visible. No buttons, no matplotlib.

- [x] **Step 1: Write the failing test**

Replace the three button-widget tests in `tests/test_synth_tab.py` (`test_synth_tab_builds_two_grids_of_buttons`, `test_synth_tab_connect_adds_a_patch`, `test_synth_tab_connect_without_source_is_noop`) and the now-obsolete `next_selection` import/test with:

```python
class _Ev:
    def __init__(self, x, y):
        self.x = x
        self.y = y


def test_drag_source_jack_to_transform_jack_creates_patch():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        tab.bpm_var.set("90")
        sx, sy = source_cell_center(0, 1)        # additive_2
        tx, ty = transform_cell_center(0, 0)     # delay_1
        tab._on_press(_Ev(sx, sy))
        tab._on_release(_Ev(tx, ty))
        patches = eng.active_patches()
        assert len(patches) == 1
        assert patches[0]["source_preset"] == "additive_2"
        assert patches[0]["transform_preset"] == "delay_1"
    finally:
        root.destroy()


def test_release_off_transform_grid_makes_source_only_patch():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        tab.bpm_var.set("90")
        sx, sy = source_cell_center(2, 0)        # resonant_1
        tab._on_press(_Ev(sx, sy))
        tab._on_release(_Ev(5, 5))               # off any transform jack
        patches = eng.active_patches()
        assert len(patches) == 1
        assert patches[0]["source_preset"] == "resonant_1"
        assert patches[0]["transform_preset"] is None
    finally:
        root.destroy()


def test_press_off_source_grid_starts_no_cable():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        tab._on_press(_Ev(5, 5))                 # not on a source jack
        tab._on_release(_Ev(*transform_cell_center(0, 0)))
        assert eng.active_patches() == []
    finally:
        root.destroy()


def test_remove_patch_disconnects_voice():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        tab.bpm_var.set("90")
        tab._on_press(_Ev(*source_cell_center(0, 0)))
        tab._on_release(_Ev(*transform_cell_center(1, 0)))
        pid = eng.active_patches()[0]["id"]
        tab._remove_patch(pid)
        assert eng.active_patches() == []
    finally:
        root.destroy()
```

Ensure the file still has the `_tk_root_or_skip` helper and `import pytest`, `import tkinter as tk`, `from synth_audio_engine import SynthAudioEngine`, and now also `from synth_tab import SynthTab, source_cell_center, transform_cell_center` at the top of the widget-test section. Remove the `next_selection` import and its `test_next_selection_single_select_toggle` test.

- [x] **Step 2: Run test to verify it fails**

Run: `py -3.11 -m pytest tests/test_synth_tab.py -k "creates_patch or source_only or no_cable or disconnects" -v`
Expected: FAIL — `AttributeError: 'SynthTab' object has no attribute '_on_press'`.

- [x] **Step 3: Write minimal implementation**

In `synth_tab.py`, replace **everything from the `import colorsys` line (the widget section) to the end of the file** with the following. (The pure helpers above — presets, root notes, `parse_bpm`, and the Task 3 geometry — stay untouched. Delete the now-unused `next_selection` function too.)

```python
import colorsys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from gui import (
    PICKER_H,
    PICKER_W,
    _patch_cable_points,
    _picker_coords_to_hsv,
    _random_scan_values,
)

WAVEFORM_WINDOW_SAMPLES = 4096
REFRESH_MS = 50


class SynthTab:
    """Drag-cable patch bay for the SoundscapeEngine: two 5x5 jack grids
    (sources left, transforms right). Drag a cable from a source jack to a
    transform jack to create a voice; release off the transform grid for a
    source-only voice. Mirrors the Loop tab's cable interaction."""

    def __init__(self, parent, synth_engine):
        self.parent = parent
        self.engine = synth_engine
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="both", expand=True)
        self.refresh_ms = REFRESH_MS

        # patch_id -> {color, source_cell, transform_cell, bpm, source_id, transform_id}
        self._patches = {}
        self._patch_rows = {}
        self._drag_source_cell = None
        self._drag_pos = None

        self.hue_var = tk.DoubleVar(value=0.0)
        self.sat_var = tk.DoubleVar(value=0.75)
        self.val_var = tk.DoubleVar(value=0.64)
        self.bpm_var = tk.StringVar(value="70")
        self.root_var = tk.StringVar()

        self._build_controls()
        self._build_bay()
        self._build_patch_list()
        self._build_waveform()
        self._schedule_refresh()

    # ---------- left controls ----------

    def _build_controls(self):
        panel = ttk.Frame(self.frame)
        panel.grid(row=0, column=0, sticky="nw", padx=8, pady=8)

        colorbox = ttk.LabelFrame(panel, text="Finger color + BPM")
        colorbox.pack(fill="x")
        self.picker = tk.Canvas(
            colorbox, width=PICKER_W, height=PICKER_H, highlightthickness=1, cursor="cross"
        )
        self.picker.grid(row=0, column=0, columnspan=3, sticky="w")
        self._picker_image = self._build_picker_image()
        self.picker.create_image(0, 0, anchor="nw", image=self._picker_image)
        self._marker = self.picker.create_oval(0, 0, 0, 0, outline="white", width=2)
        self.picker.bind("<Button-1>", lambda e: self._set_pick(e.x, e.y))
        self.picker.bind("<B1-Motion>", lambda e: self._set_pick(e.x, e.y))
        ttk.Label(colorbox, text="BPM").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(colorbox, textvariable=self.bpm_var, width=8).grid(
            row=1, column=1, sticky="w", pady=(6, 0)
        )
        self.swatch = tk.Canvas(colorbox, width=40, height=40, highlightthickness=1)
        self.swatch.grid(row=1, column=2, padx=8)
        ttk.Button(colorbox, text="Random", command=self._on_random).grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )

        rootbox = ttk.LabelFrame(panel, text="Harmonic root")
        rootbox.pack(fill="x", pady=(8, 0))
        labels = [label for label, _midi in ROOT_NOTE_CHOICES]
        self._root_by_label = {label: midi for label, midi in ROOT_NOTE_CHOICES}
        current = next(
            label for label, midi in ROOT_NOTE_CHOICES if midi == self.engine.root_midi
        )
        self.root_var.set(current)
        ttk.Combobox(
            rootbox, textvariable=self.root_var, values=labels, state="readonly", width=6
        ).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(rootbox, text="Apply (clears patches)", command=self._on_apply_root).grid(
            row=0, column=1, padx=4
        )

        ttk.Button(panel, text="Load Sample...", command=self._on_load_sample).pack(
            fill="x", pady=(8, 0)
        )
        self._set_pick(PICKER_W // 2, PICKER_H // 2)

    def _build_picker_image(self):
        img = tk.PhotoImage(width=PICKER_W, height=PICKER_H)
        rows = []
        for y in range(PICKER_H):
            row = []
            for x in range(PICKER_W):
                hue, sat, val = _picker_coords_to_hsv(x, y)
                r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
                row.append(f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}")
            rows.append("{" + " ".join(row) + "}")
        img.put(" ".join(rows))
        return img

    def _set_pick(self, x, y):
        x = int(min(PICKER_W - 1, max(0, x)))
        y = int(min(PICKER_H - 1, max(0, y)))
        hue, sat, val = _picker_coords_to_hsv(x, y)
        self.hue_var.set(hue)
        self.sat_var.set(sat)
        self.val_var.set(val)
        self.picker.coords(self._marker, x - 5, y - 5, x + 5, y + 5)
        self.swatch.configure(bg=self._color_hex())

    def _color_hex(self):
        r, g, b = colorsys.hsv_to_rgb(
            self.hue_var.get(), self.sat_var.get(), self.val_var.get()
        )
        return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

    def _on_random(self):
        x, y, bpm = _random_scan_values()
        self._set_pick(x, y)
        self.bpm_var.set(f"{bpm:.0f}")

    def _on_apply_root(self):
        if self.engine.active_patches() and not messagebox.askokcancel(
            "Change root note",
            "Changing the harmonic root rebuilds the engine and removes all "
            "active patches. Continue?",
        ):
            return
        self.engine.set_root_midi(self._root_by_label[self.root_var.get()])
        for row in list(self._patch_rows.values()):
            row.destroy()
        self._patch_rows.clear()
        self._patches.clear()
        self._redraw_bay()

    def _on_load_sample(self):
        path = filedialog.askopenfilename(
            filetypes=[("Audio files", "*.wav *.mp3"), ("WAV files", "*.wav")]
        )
        if not path:
            return
        try:
            self.engine.load_sample(path)
        except Exception as exc:
            messagebox.showerror("Failed to load sample", str(exc))

    # ---------- patch bay ----------

    def _build_bay(self):
        box = ttk.LabelFrame(
            self.frame, text="Patch bay - drag a source jack to a transform jack"
        )
        box.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        self.frame.columnconfigure(1, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.bay = tk.Canvas(
            box, width=SYNTH_CANVAS_W, height=SYNTH_CANVAS_H,
            bg="#161616", highlightthickness=0,
        )
        self.bay.pack(fill="both", expand=True)
        self.bay.bind("<Button-1>", self._on_press)
        self.bay.bind("<B1-Motion>", self._on_drag)
        self.bay.bind("<ButtonRelease-1>", self._on_release)
        self._redraw_bay()

    def _draw_grid(self, origin, rows, title):
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
                c.create_text(x0 + 8, y0 + 10, text=VARIANT_LABELS[col],
                              fill="#808080", font=("TkDefaultFont", 8))

    def _draw_jacks(self, origin, filled):
        for r in range(SYNTH_GRID_SIZE):
            for col in range(SYNTH_GRID_SIZE):
                cx, cy = _cell_center(origin, r, col)
                color = filled.get((r, col), "#3a3a3a")
                self.bay.create_oval(
                    cx - SYNTH_JACK_RADIUS, cy - SYNTH_JACK_RADIUS,
                    cx + SYNTH_JACK_RADIUS, cy + SYNTH_JACK_RADIUS,
                    outline="#8a8a8a", fill=color, width=2,
                )

    def _redraw_bay(self):
        c = self.bay
        c.delete("all")
        self._draw_grid(SYNTH_SOURCE_ORIGIN, SYNTH_SOURCE_ROWS, "sources")
        self._draw_grid(SYNTH_TRANSFORM_ORIGIN, SYNTH_TRANSFORM_ROWS, "transforms")

        source_fill = {}
        transform_fill = {}
        for p in self._patches.values():
            source_fill[p["source_cell"]] = p["color"]
            if p["transform_cell"] is not None:
                transform_fill[p["transform_cell"]] = p["color"]

        # cables under the jacks
        for p in self._patches.values():
            sx, sy = source_cell_center(*p["source_cell"])
            if p["transform_cell"] is not None:
                tx, ty = transform_cell_center(*p["transform_cell"])
                c.create_line(*_patch_cable_points(sx, sy, tx, ty),
                              fill=p["color"], width=3)
            else:
                c.create_line(sx, sy, sx + 18, sy, fill=p["color"], width=3)

        if self._drag_source_cell is not None and self._drag_pos is not None:
            sx, sy = source_cell_center(*self._drag_source_cell)
            c.create_line(*_patch_cable_points(sx, sy, *self._drag_pos),
                          fill=self._color_hex(), width=2, dash=(4, 3))

        self._draw_jacks(SYNTH_SOURCE_ORIGIN, source_fill)
        self._draw_jacks(SYNTH_TRANSFORM_ORIGIN, transform_fill)

    def _on_press(self, event):
        self._drag_source_cell = source_cell_at(event.x, event.y)
        self._drag_pos = None

    def _on_drag(self, event):
        if self._drag_source_cell is None:
            return
        self._drag_pos = (event.x, event.y)
        self._redraw_bay()

    def _on_release(self, event):
        if self._drag_source_cell is None:
            return
        source_cell = self._drag_source_cell
        transform_cell = transform_cell_at(event.x, event.y)
        self._drag_source_cell = None
        self._drag_pos = None
        self._connect(source_cell, transform_cell)

    def _connect(self, source_cell, transform_cell):
        if len(self._patches) >= SYNTH_PATCH_LIMIT:
            messagebox.showinfo("Patch bay full", f"Maximum voices reached ({SYNTH_PATCH_LIMIT}).")
            self._redraw_bay()
            return
        bpm = parse_bpm(self.bpm_var.get())
        if bpm is None:
            messagebox.showerror("Invalid BPM", f"BPM must be a number ({self.bpm_var.get()!r}).")
            self._redraw_bay()
            return
        source_id = source_preset_id(*source_cell)
        transform_id = (
            transform_preset_id(*transform_cell) if transform_cell is not None else None
        )
        color = self._color_hex()
        pid = self.engine.connect_patch(
            self.hue_var.get(), self.sat_var.get(), self.val_var.get(),
            bpm, source_id, transform_id,
        )
        self._patches[pid] = {
            "color": color,
            "source_cell": source_cell,
            "transform_cell": transform_cell,
            "bpm": bpm,
            "source_id": source_id,
            "transform_id": transform_id,
        }
        self._add_patch_row(pid, bpm, source_id, transform_id, color)
        self._redraw_bay()

    # ---------- patch list ----------

    def _build_patch_list(self):
        box = ttk.LabelFrame(self.frame, text="Active patches")
        box.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        self.frame.rowconfigure(1, weight=1)
        canvas = tk.Canvas(box, height=120, highlightthickness=0)
        scrollbar = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        self.patch_list_frame = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=self.patch_list_frame, anchor="nw")
        self.patch_list_frame.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _add_patch_row(self, pid, bpm, source_id, transform_id, color_hex):
        row = ttk.Frame(self.patch_list_frame)
        row.pack(fill="x", pady=2)
        tk.Canvas(row, width=16, height=16, highlightthickness=1, bg=color_hex).pack(
            side="left", padx=(0, 6)
        )
        label = f"#{pid}  {source_id}"
        if transform_id:
            label += f" -> {transform_id}"
        label += f"  (BPM {bpm:.0f})"
        ttk.Label(row, text=label).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Remove", command=lambda: self._remove_patch(pid)).pack(
            side="right"
        )
        self._patch_rows[pid] = row

    def _remove_patch(self, pid):
        self.engine.disconnect_patch(pid)
        self._patches.pop(pid, None)
        row = self._patch_rows.pop(pid, None)
        if row is not None:
            row.destroy()
        self._redraw_bay()

    # ---------- waveform (lightweight Tk canvas) ----------

    def _build_waveform(self):
        box = ttk.LabelFrame(self.frame, text="Waveform")
        box.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        self.wave = tk.Canvas(box, height=110, bg="#0b0b0b", highlightthickness=0)
        self.wave.pack(fill="both", expand=True)
        self.wave_line = self.wave.create_line(0, 0, 0, 0, fill="#4da6ff", width=1)

    def _draw_wave(self):
        data = self.engine.visual_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        w = max(2, self.wave.winfo_width())
        h = max(2, self.wave.winfo_height())
        n = WAVEFORM_POINTS
        seg = max(1, len(data) // n)
        pts = []
        for i in range(n):
            chunk = data[i * seg:(i + 1) * seg]
            if len(chunk) == 0:
                v = 0.0
            else:
                v = float(chunk[int(np.argmax(np.abs(chunk)))])
            x = i / (n - 1) * w
            y = h / 2 - v * (h / 2 - 2)
            pts.extend((x, y))
        if len(pts) >= 4:
            self.wave.coords(self.wave_line, *pts)

    def _schedule_refresh(self):
        # Only redraw while this tab is actually visible -- keeps GIL holds
        # tiny so they can't starve the audio producer thread.
        if self.frame.winfo_viewable():
            self._draw_wave()
        self.parent.after(self.refresh_ms, self._schedule_refresh)
```

- [x] **Step 4: Run test to verify it passes**

Run: `py -3.11 -m pytest tests/test_synth_tab.py -v`
Expected: PASS — geometry tests, the retained pure-helper tests (`source_preset_id`/`transform_preset_id`/`ROOT_NOTE_CHOICES`/`parse_bpm`), and the four new drag-cable widget tests. No `next_selection`/button tests remain.

- [x] **Step 5: Commit**

```bash
git add audio_prototype/synth_tab.py audio_prototype/tests/test_synth_tab.py
git commit -m "feat(synth): replace button grids with a drag-cable patch bay and tk waveform

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full-suite verification + brief refresh

**Files:**
- Modify: `AGENTS.md` (lines 6-14, "Pick up here")

- [x] **Step 1: Run the full suite**

Run from `audio_prototype/`: `py -3.11 -m pytest tests/ -v`
Expected: PASS — every pre-existing test plus the changed synth/resonant tests. Zero unrelated regressions. Note the count for the report.

- [x] **Step 2: Manual launch check (human, has display + audio; do NOT run headless)**

Run from `audio_prototype/`: `py -3.11 main.py`
Expected:
- Synth tab shows the two-grid canvas patch bay (sources left, transforms right), no buttons.
- Dragging a cable from a source jack to a transform jack creates an audible voice with a colored cable and a list row; releasing off the transform grid makes a source-only voice.
- **A single source plays with no clicks/glitches**, and several stacked voices stay clean; the waveform tracks without stutter.
- Remove clears the voice + cable; root Apply warns and clears; Load Sample works.
A subagent without a display marks this done-by-inspection (automated coverage is Tasks 1-4); the user verifies by ear.

- [x] **Step 3: Refresh the "Pick up here" brief**

Update `AGENTS.md` lines 6-14 to:

```markdown
## ⏱ Pick up here   ← LIVING; refresh at session end
- **Status:**       Prototype — the desktop app (audio_prototype/main.py) has Loop + Synth tabs. The Synth tab now uses a Loop/webapp-style drag-cable patch bay (synth_tab.py): two 5x5 jack grids (sources additive/granular/resonant/noise/texture, transforms delay/spectral/pitch/grainfx/spatial), cable a source jack to a transform jack to create a SoundscapeEngine voice (release off-grid = source-only), each colored by the captured scan color. Synth audio runs on a producer thread with blocking write() at latency="high" (SynthAudioEngine) and a lightweight tk-canvas waveform, fixing the callback/GIL glitching; resonant sources skip their per-sample loop when rung out. Loop tab untouched; web app + firmware/TD still WIP.
- **Last session:** 2026-07-23 — redesigned the Synth tab to the drag-cable patch bay and fixed synth clipping/CPU headroom per docs/superpowers/plans/2026-07-23-synth-patchbay-and-headroom.md (spec: docs/superpowers/specs/2026-07-23-synth-patchbay-and-headroom-design.md).
- **Next up:**
  - Tune by ear in the Synth tab: source/transform preset feel, color->timbre mapping, register/gain, root-note range.
  - Consider cable-click selection/removal and persisting patches.
  - Wire hardware finger-scan input into the Synth tab (spec Phase 3).
  - Document the firmware serial message shape (base64 JPEG framing).
- **Blockers / open questions:** Is TD driven by the web app, the Python engine, or the device directly?
```

- [x] **Step 4: Commit**

```bash
git add AGENTS.md
git commit -m "docs: mark synth drag-cable patch bay + headroom fix in agent brief

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Notes (for the implementer)

- **Import cycle unchanged:** `synth_tab` still imports `gui` at module level; `gui` still imports `synth_tab` only lazily inside `_build_synth_tab`. Adding `_patch_cable_points` to the existing `from gui import …` line is safe.
- **`gui.py` is NOT modified** by this plan — `SynthTab(parent, synth_engine)` keeps the same constructor signature the GUI already calls.
- **Thread hygiene:** every `test_*` that calls `resume()` must call `stop()` before returning; the producer thread is a daemon so a leaked one won't hang the suite, but `stop()` keeps tests deterministic.
- **Resonant early-out is exact:** it only returns zeros when the loop would have produced sub-`1e-6` values and no pulse fires; the audible path is byte-identical, so existing resonant tests still guard it.
- **Waveform never blocks audio:** `_draw_wave` touches only Tk (main thread); audio is produced on the separate producer thread pulling through PortAudio's C buffer, so a slow redraw delays only the next visual frame.
