# Synth Tab (Phase 2, interactive) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an interactive **Synth** tab to the desktop Tkinter app (`audio_prototype/main.py`) that drives the Phase 1 `SoundscapeEngine` live — the user builds patches from two 5×5 preset grids (source + transform), sets a finger-scan color and BPM, and hears the evolving soundscape through `sounddevice`.

**Architecture:** Two independent vertical slices. A new `SynthAudioEngine` wraps `soundscape_engine.SoundscapeEngine` and adds `sounddevice` stream lifecycle + a visualizer ring buffer + a thread lock (the Phase 1 engine has no locking of its own). `gui.py` is wrapped in a `ttk.Notebook`: the existing layout becomes the "Loop" tab (behavior unchanged); a new "Synth" tab (built in `synth_tab.py`) hosts the grids/controls. `<<NotebookTabChanged>>` pauses the outgoing engine's stream and resumes the incoming one so only one stream plays at a time. `main.py` builds both engines and stops both on exit.

**Tech Stack:** Python 3.11 + NumPy + Tkinter/ttk + matplotlib (`FigureCanvasTkAgg`) + `sounddevice` + `soundfile`; pytest. All already present in `audio_prototype/`.

## Global Constraints

- **Do not modify the Phase 1 engine internals.** No edits to `soundscape_engine.py`, `soundscape_sources.py`, `soundscape_transforms.py`, `soundscape_harmony.py`, `soundscape_density.py`, `soundscape_color.py`, `soundscape_voices.py`.
- **Do not change Loop-mode audio behavior.** `layers.py`, `crowd.py`, `web_engine.py`, and the audio path of `audio_engine.py` stay behavior-identical. The only allowed `audio_engine.py` edit is moving two pure functions into `audio_io.py` and re-importing them (Task 1).
- **No new third-party dependencies.** NumPy-only DSP; reuse existing helpers.
- **Keep the existing public import surface intact.** `audio_engine.read_mono_audio` and `audio_engine.resample_linear` must remain importable (existing tests/importers depend on them). `gui._picker_coords_to_hsv`, `gui._random_scan_values`, `gui.PICKER_W`, `gui.PICKER_H` must remain importable (`test_gui.py` imports them).
- **Run tests from `audio_prototype/`**: `python -m pytest tests/<file> -v` (the existing `conftest.py` puts the module dir on `sys.path`). Use the tkinter-capable Python (`py -3.11` on this machine); the PlatformIO-embedded Python lacks tkinter and cannot collect `test_gui.py`.
- **Prefix shell/build/git commands with `rtk`** per project convention when running interactively; the exact `git` commands below omit `rtk` so they work verbatim in any shell.
- **Every commit message** ends with the `Co-Authored-By` trailer used elsewhere in this repo.

## File Structure

**Create:**
- `audio_prototype/audio_io.py` — `read_mono_audio`, `resample_linear` (lifted verbatim from `audio_engine.py`) + the constants they need.
- `audio_prototype/synth_audio_engine.py` — `SynthAudioEngine`.
- `audio_prototype/synth_tab.py` — pure grid/selection/root-note/bpm helpers + `SynthTab` widget class.
- `audio_prototype/tests/test_audio_io.py`
- `audio_prototype/tests/test_synth_audio_engine.py`
- `audio_prototype/tests/test_synth_tab.py`

**Modify:**
- `audio_prototype/audio_engine.py` — import + re-export the two lifted functions (no behavior change).
- `audio_prototype/gui.py` — Notebook wrapper, Loop tab reparent, Synth tab integration, tab-switch handoff.
- `audio_prototype/main.py` — build both engines, pass both to `RedPoleGUI`, stop both on exit.
- `AGENTS.md` — refresh "Pick up here" (Task 8 only).

---

## Task 1: Extract shared audio I/O helpers

**Files:**
- Create: `audio_prototype/audio_io.py`
- Modify: `audio_prototype/audio_engine.py` (lines 32-35 constants + 98-131 functions → import instead)
- Test: `audio_prototype/tests/test_audio_io.py`

**Interfaces:**
- Consumes: `soundfile` (`sf`), `numpy`.
- Produces:
  - `read_mono_audio(path, max_seconds=None) -> tuple[np.ndarray(float32), int]` — mono samples + source samplerate.
  - `resample_linear(data, source_rate, target_rate) -> np.ndarray(float32)`.
  - `MAX_LOOP_SECONDS = 600.0`, `LOAD_CHUNK_FRAMES = 262144` (module constants the functions use).

- [x] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_audio_io.py
import numpy as np
import soundfile as sf

from audio_io import read_mono_audio, resample_linear


def test_resample_linear_is_identity_when_rates_match():
    data = np.linspace(-1.0, 1.0, 100, dtype=np.float32)
    out = resample_linear(data, 44100, 44100)
    np.testing.assert_array_equal(out, data)


def test_resample_linear_changes_length_on_rate_change():
    data = np.zeros(1000, dtype=np.float32)
    out = resample_linear(data, 44100, 22050)
    assert abs(len(out) - 500) <= 1
    assert out.dtype == np.float32


def test_read_mono_audio_downmixes_stereo(tmp_path):
    path = tmp_path / "stereo.wav"
    stereo = np.stack([
        np.ones(2048, dtype=np.float32),
        -np.ones(2048, dtype=np.float32),
    ], axis=1)
    sf.write(str(path), stereo, 44100)
    mono, rate = read_mono_audio(str(path))
    assert rate == 44100
    assert mono.ndim == 1
    assert mono.dtype == np.float32
    # +1 and -1 average to ~0
    assert float(np.max(np.abs(mono))) < 1e-3


def test_read_mono_audio_respects_max_seconds(tmp_path):
    path = tmp_path / "long.wav"
    sf.write(str(path), np.zeros(44100 * 3, dtype=np.float32), 44100)
    mono, _rate = read_mono_audio(str(path), max_seconds=1.0)
    assert len(mono) <= 44100 + 1


def test_audio_engine_still_reexports_helpers():
    import audio_engine
    assert audio_engine.read_mono_audio is read_mono_audio
    assert audio_engine.resample_linear is resample_linear
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_audio_io.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_io'`.

- [x] **Step 3: Write minimal implementation**

Create `audio_prototype/audio_io.py` with the two functions moved verbatim from `audio_engine.py`:

```python
# audio_prototype/audio_io.py
"""Shared audio file I/O helpers used by both the loop engine and the
soundscape/synth engine. Moved out of audio_engine.py so the synth engine
can load samples without importing the whole loop-mode engine."""

import numpy as np
import soundfile as sf

MAX_LOOP_SECONDS = 600.0
LOAD_CHUNK_FRAMES = 262144


def resample_linear(data, source_rate, target_rate):
    if source_rate == target_rate or len(data) == 0:
        return data.astype(np.float32)
    target_len = max(1, int(round(len(data) * target_rate / source_rate)))
    source_x = np.linspace(0.0, 1.0, len(data), endpoint=False)
    target_x = np.linspace(0.0, 1.0, target_len, endpoint=False)
    return np.interp(target_x, source_x, data).astype(np.float32)


def read_mono_audio(path, max_seconds=None):
    if max_seconds is None:
        max_seconds = MAX_LOOP_SECONDS
    chunks = []
    with sf.SoundFile(path) as file:
        file_rate = file.samplerate
        frames_to_read = len(file)
        if max_seconds is not None:
            frames_to_read = min(frames_to_read, max(1, int(max_seconds * file_rate)))

        remaining = frames_to_read
        while remaining > 0:
            block = file.read(
                min(LOAD_CHUNK_FRAMES, remaining),
                dtype="float32",
                always_2d=True,
            )
            if len(block) == 0:
                break
            chunks.append(block.mean(axis=1).astype(np.float32))
            remaining -= len(block)

    if not chunks:
        return np.zeros(0, dtype=np.float32), file_rate
    return np.concatenate(chunks).astype(np.float32), file_rate
```

Now edit `audio_engine.py`. Delete the `MAX_LOOP_SECONDS`/`LOAD_CHUNK_FRAMES` assignments (lines 33, 35) **only if** they are not referenced elsewhere in the file — `MAX_LOOP_SECONDS` is used only inside the moved `read_mono_audio`, and `LOAD_CHUNK_FRAMES` likewise; `MAX_ANALYSIS_SECONDS` (line 34) stays. Delete the `resample_linear` (lines 98-104) and `read_mono_audio` (lines 107-131) function definitions. Add this import near the other imports at the top of `audio_engine.py` (after the existing `import numpy as np` block):

```python
from audio_io import (  # re-exported for existing importers/tests
    LOAD_CHUNK_FRAMES,
    MAX_LOOP_SECONDS,
    read_mono_audio,
    resample_linear,
)
```

Leave every other line of `audio_engine.py` unchanged. `read_mono_audio`/`resample_linear` are still module attributes of `audio_engine` (now via import), so `audio_engine.read_mono_audio` keeps working.

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_audio_io.py tests/test_audio_engine.py -v`
Expected: PASS — the 5 new `test_audio_io` tests plus every existing `test_audio_engine` test (behavior unchanged).

- [x] **Step 5: Commit**

```bash
git add audio_prototype/audio_io.py audio_prototype/audio_engine.py audio_prototype/tests/test_audio_io.py
git commit -m "refactor(audio): extract shared read_mono_audio/resample_linear into audio_io

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `SynthAudioEngine` — patch control + block generation

**Files:**
- Create: `audio_prototype/synth_audio_engine.py`
- Test: `audio_prototype/tests/test_synth_audio_engine.py`

**Interfaces:**
- Consumes: `soundscape_engine.SoundscapeEngine`, `ring_buffer.RingBuffer`, `numpy`, `threading`.
- Produces:
  - `class SynthAudioEngine(samplerate=44100, blocksize=1024, seed=None, root_midi=62)`.
  - `.connect_patch(hue, sat, val, bpm, source_preset, transform_preset=None) -> int`.
  - `.disconnect_patch(patch_id) -> None`.
  - `.active_patches() -> list[dict]` with keys `id, hue, sat, val, bpm, source_preset, transform_preset`.
  - `.generate_block(frames) -> np.ndarray(float32, shape (frames,))`.
  - `.generate_stereo_block(frames) -> np.ndarray(float32, shape (frames, 2))`.
  - `.visual_buffer` (`RingBuffer`), `.root_midi` (int), `.engine` (`SoundscapeEngine`).

- [x] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_synth_audio_engine.py
import numpy as np

from synth_audio_engine import SynthAudioEngine


def test_connect_patch_returns_increasing_ids():
    eng = SynthAudioEngine(seed=1)
    a = eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    b = eng.connect_patch(0.03, 0.68, 0.94, 90.0, "granular_1")
    assert b > a


def test_no_patches_is_silence():
    eng = SynthAudioEngine(seed=1)
    block = eng.generate_block(1024)
    assert block.shape == (1024,)
    assert block.dtype == np.float32
    np.testing.assert_allclose(block, np.zeros(1024))


def test_one_patch_is_audible_bounded_nan_free():
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    total = np.concatenate([eng.generate_block(1024) for _ in range(80)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-3
    assert float(np.sqrt(np.mean(total[-8192:] ** 2))) > 0.01


def test_disconnect_last_patch_returns_to_silence():
    eng = SynthAudioEngine(seed=1)
    pid = eng.connect_patch(0.03, 0.68, 0.94, 90.0, "noise_2")
    eng.generate_block(512)
    eng.disconnect_patch(pid)
    np.testing.assert_allclose(eng.generate_block(512), np.zeros(512))


def test_active_patches_snapshot_shape():
    eng = SynthAudioEngine(seed=1)
    pid = eng.connect_patch(0.02, 0.7, 0.9, 88.0, "resonant_1", "spatial_1")
    patches = eng.active_patches()
    assert len(patches) == 1
    p = patches[0]
    assert p["id"] == pid
    assert p["source_preset"] == "resonant_1"
    assert p["transform_preset"] == "spatial_1"
    assert p["bpm"] == 88.0


def test_stereo_block_duplicates_mono():
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    stereo = eng.generate_stereo_block(256)
    assert stereo.shape == (256, 2)
    np.testing.assert_array_equal(stereo[:, 0], stereo[:, 1])


def test_generate_block_writes_visual_buffer():
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    for _ in range(20):
        eng.generate_block(1024)
    latest = eng.visual_buffer.read_latest(1024)
    assert float(np.max(np.abs(latest))) > 0.0


def test_render_exception_yields_silent_block(monkeypatch):
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")

    def boom(frames):
        raise RuntimeError("render failed")

    monkeypatch.setattr(eng.engine, "generate_block", boom)
    block = eng.generate_block(512)
    np.testing.assert_allclose(block, np.zeros(512))
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synth_audio_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'synth_audio_engine'`.

- [x] **Step 3: Write minimal implementation**

```python
# audio_prototype/synth_audio_engine.py
"""Interactive desktop wrapper around the Phase 1 SoundscapeEngine.

Adds a sounddevice output-stream lifecycle, a visualizer ring buffer, and a
thread lock (SoundscapeEngine mutates plain dicts/lists with no locking of
its own, so connect/disconnect from the UI thread must be serialized against
the audio callback's generate_block). Deliberately far thinner than
AudioEngine: no loop, no LayerRegistry, no reverb/wet-bus -- SoundscapeEngine
already does its own mixing and limiting."""

import threading

import numpy as np
import sounddevice as sd

from ring_buffer import RingBuffer
from soundscape_engine import SoundscapeEngine

VISUALIZER_BUFFER_SECONDS = 2.0


class SynthAudioEngine:
    def __init__(self, samplerate=44100, blocksize=1024, seed=None, root_midi=62):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self._seed = seed
        self._root_midi = int(root_midi)
        self._lock = threading.Lock()
        self.engine = SoundscapeEngine(
            samplerate=samplerate, seed=seed, root_midi=self._root_midi
        )
        self.visual_buffer = RingBuffer(int(samplerate * VISUALIZER_BUFFER_SECONDS))
        self._stream = None
        self._paused = True

    @property
    def root_midi(self):
        return self._root_midi

    # ---------- patch control ----------

    def connect_patch(self, hue, sat, val, bpm, source_preset, transform_preset=None):
        with self._lock:
            return self.engine.connect_patch(
                hue, sat, val, bpm, source_preset, transform_preset
            )

    def disconnect_patch(self, patch_id):
        with self._lock:
            self.engine.disconnect_patch(patch_id)

    def active_patches(self):
        with self._lock:
            return [
                {
                    "id": p.id,
                    "hue": p.hue,
                    "sat": p.sat,
                    "val": p.val,
                    "bpm": p.bpm,
                    "source_preset": p.source_preset,
                    "transform_preset": p.transform_preset,
                }
                for p in self.engine._patches.values()
            ]

    # ---------- audio ----------

    def generate_block(self, frames):
        with self._lock:
            try:
                block = self.engine.generate_block(frames)
            except Exception:
                block = np.zeros(frames, dtype=np.float32)
        self.visual_buffer.write(block)
        return block

    def generate_stereo_block(self, frames):
        mono = self.generate_block(frames)
        return np.column_stack([mono, mono]).astype(np.float32)
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synth_audio_engine.py -v`
Expected: PASS (8 tests).

- [x] **Step 5: Commit**

```bash
git add audio_prototype/synth_audio_engine.py audio_prototype/tests/test_synth_audio_engine.py
git commit -m "feat(synth): add SynthAudioEngine patch control and block generation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `SynthAudioEngine` — stream lifecycle

**Files:**
- Modify: `audio_prototype/synth_audio_engine.py`
- Test: `audio_prototype/tests/test_synth_audio_engine.py`

**Interfaces:**
- Consumes: `sounddevice` (`sd.OutputStream`), the Task 2 class.
- Produces: `.start()`, `.stop()`, `.pause()`, `.resume()`, `.paused -> bool`, `._callback(outdata, frames, time_info, status)`. `resume()` lazily opens the stream on first call so no stream is opened until the Synth tab is actually shown.

- [x] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_synth_audio_engine.py


def _fake_stream_factory(events):
    class FakeStream:
        def __init__(self, **kwargs):
            events.append(("init", kwargs["channels"]))
            self.callback = kwargs["callback"]

        def start(self):
            events.append(("start",))

        def stop(self):
            events.append(("stop",))

        def close(self):
            events.append(("close",))

    return FakeStream


def test_starts_paused_and_opens_no_stream(monkeypatch):
    events = []
    monkeypatch.setattr(
        "synth_audio_engine.sd.OutputStream", _fake_stream_factory(events)
    )
    eng = SynthAudioEngine(seed=1)
    assert eng.paused is True
    eng.start()  # start() while paused should not begin playback
    assert ("start",) not in events


def test_resume_opens_and_starts_stream(monkeypatch):
    events = []
    monkeypatch.setattr(
        "synth_audio_engine.sd.OutputStream", _fake_stream_factory(events)
    )
    eng = SynthAudioEngine(seed=1)
    eng.resume()
    assert eng.paused is False
    assert ("init", 2) in events
    assert events.count(("start",)) == 1


def test_pause_stops_without_closing(monkeypatch):
    events = []
    monkeypatch.setattr(
        "synth_audio_engine.sd.OutputStream", _fake_stream_factory(events)
    )
    eng = SynthAudioEngine(seed=1)
    eng.resume()
    eng.pause()
    assert eng.paused is True
    assert ("stop",) in events
    assert ("close",) not in events


def test_stop_closes_stream(monkeypatch):
    events = []
    monkeypatch.setattr(
        "synth_audio_engine.sd.OutputStream", _fake_stream_factory(events)
    )
    eng = SynthAudioEngine(seed=1)
    eng.resume()
    eng.stop()
    assert ("close",) in events


def test_callback_fills_outdata_stereo(monkeypatch):
    events = []
    monkeypatch.setattr(
        "synth_audio_engine.sd.OutputStream", _fake_stream_factory(events)
    )
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    out = np.zeros((256, 2), dtype=np.float32)
    eng._callback(out, 256, None, None)
    assert out.shape == (256, 2)
    np.testing.assert_array_equal(out[:, 0], out[:, 1])
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synth_audio_engine.py -k "stream or resume or pause or stop or callback" -v`
Expected: FAIL — `AttributeError: 'SynthAudioEngine' object has no attribute 'resume'`.

- [x] **Step 3: Write minimal implementation**

Append these methods to the `SynthAudioEngine` class in `synth_audio_engine.py`:

```python
    # ---------- stream lifecycle ----------

    @property
    def paused(self):
        return self._paused

    def _open_stream(self):
        self._stream = sd.OutputStream(
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            channels=2,
            callback=self._callback,
        )

    def _callback(self, outdata, frames, time_info, status):
        outdata[:, :] = self.generate_stereo_block(frames)

    def start(self):
        if self._stream is None:
            self._open_stream()
        if not self._paused:
            self._stream.start()

    def resume(self):
        self._paused = False
        if self._stream is None:
            self._open_stream()
        self._stream.start()

    def pause(self):
        self._paused = True
        if self._stream is not None:
            self._stream.stop()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synth_audio_engine.py -v`
Expected: PASS (13 tests total).

- [x] **Step 5: Commit**

```bash
git add audio_prototype/synth_audio_engine.py audio_prototype/tests/test_synth_audio_engine.py
git commit -m "feat(synth): add SynthAudioEngine sounddevice stream lifecycle

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `SynthAudioEngine` — load sample + set root note

**Files:**
- Modify: `audio_prototype/synth_audio_engine.py`
- Test: `audio_prototype/tests/test_synth_audio_engine.py`

**Interfaces:**
- Consumes: `audio_io.read_mono_audio`/`resample_linear` (Task 1), `SourceBank.texture.load_sample` (Phase 1).
- Produces:
  - `.load_sample(path) -> None` — reads + resamples the file and forwards it to the texture source; a re-loadable sample survives a later `set_root_midi` rebuild.
  - `.load_sample_array(samples) -> None` — forwards an already-decoded mono array (used by the file path and by tests).
  - `.set_root_midi(root_midi) -> None` — rebuilds a fresh `SoundscapeEngine` at the new root (drops all patches by design), re-applying the last loaded sample if any.

- [ ] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_synth_audio_engine.py


def test_load_sample_array_changes_texture_output():
    a = SynthAudioEngine(seed=6)
    b = SynthAudioEngine(seed=6)
    b.load_sample_array(np.sin(2 * np.pi * 440 * np.arange(44100 * 3) / 44100))
    a.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    b.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    out_a = np.concatenate([a.generate_block(1024) for _ in range(20)])
    out_b = np.concatenate([b.generate_block(1024) for _ in range(20)])
    assert not np.allclose(out_a, out_b)


def test_load_sample_reads_file(tmp_path):
    import soundfile as sf

    path = tmp_path / "tex.wav"
    sf.write(str(path), np.sin(2 * np.pi * 330 * np.arange(44100) / 44100), 44100)
    eng = SynthAudioEngine(seed=6)
    eng.load_sample(str(path))  # should not raise
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    out = np.concatenate([eng.generate_block(1024) for _ in range(10)])
    assert not np.any(np.isnan(out))


def test_set_root_midi_rebuilds_and_clears_patches():
    eng = SynthAudioEngine(seed=1, root_midi=62)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    assert len(eng.active_patches()) == 1
    eng.set_root_midi(60)
    assert eng.root_midi == 60
    assert eng.active_patches() == []


def test_set_root_midi_reapplies_loaded_sample():
    eng = SynthAudioEngine(seed=6)
    eng.load_sample_array(np.sin(2 * np.pi * 440 * np.arange(44100 * 3) / 44100))
    eng.set_root_midi(65)
    baseline = SynthAudioEngine(seed=6)  # same seed, no sample loaded
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    baseline.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    out = np.concatenate([eng.generate_block(1024) for _ in range(20)])
    base = np.concatenate([baseline.generate_block(1024) for _ in range(20)])
    assert not np.allclose(out, base)  # loaded sample carried across the rebuild
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synth_audio_engine.py -k "sample or root_midi" -v`
Expected: FAIL — `AttributeError: 'SynthAudioEngine' object has no attribute 'load_sample_array'`.

- [ ] **Step 3: Write minimal implementation**

Add `from audio_io import read_mono_audio, resample_linear` to the imports at the top of `synth_audio_engine.py`, add `self._loaded_sample = None` to `__init__` (right after `self.engine = ...`), and append these methods to the class:

```python
    # ---------- sample + tuning ----------

    def load_sample(self, path):
        mono, file_rate = read_mono_audio(path)
        samples = resample_linear(mono, file_rate, self.samplerate)
        self.load_sample_array(samples)

    def load_sample_array(self, samples):
        samples = np.asarray(samples, dtype=np.float64)
        with self._lock:
            self._loaded_sample = samples
            self.engine.sources.texture.load_sample(samples)

    def set_root_midi(self, root_midi):
        with self._lock:
            self._root_midi = int(root_midi)
            self.engine = SoundscapeEngine(
                samplerate=self.samplerate, seed=self._seed, root_midi=self._root_midi
            )
            if self._loaded_sample is not None:
                self.engine.sources.texture.load_sample(self._loaded_sample)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synth_audio_engine.py -v`
Expected: PASS (17 tests total).

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/synth_audio_engine.py audio_prototype/tests/test_synth_audio_engine.py
git commit -m "feat(synth): add SynthAudioEngine sample loading and root-note retune

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Synth-tab pure helpers

**Files:**
- Create: `audio_prototype/synth_tab.py`
- Test: `audio_prototype/tests/test_synth_tab.py`

**Interfaces:**
- Consumes: `soundscape_sources.SOURCE_PRESETS`, `soundscape_transforms.TRANSFORM_PRESETS`.
- Produces:
  - `SYNTH_SOURCE_ROWS = ("additive", "granular", "resonant", "noise", "texture")`.
  - `SYNTH_TRANSFORM_ROWS = ("delay", "spectral", "pitch", "grainfx", "spatial")`.
  - `SYNTH_GRID_SIZE = 5`.
  - `source_preset_id(row, col) -> str`, `transform_preset_id(row, col) -> str`.
  - `ROOT_NOTE_CHOICES -> list[tuple[str, int]]` including `("D4", 62)`.
  - `next_selection(current, clicked) -> tuple|None` (single-select toggle).
  - `BPM_MIN = 20.0`, `BPM_MAX = 300.0`, `parse_bpm(text) -> float|None`.

- [ ] **Step 1: Write the failing test**

```python
# audio_prototype/tests/test_synth_tab.py
from soundscape_sources import SOURCE_PRESETS
from soundscape_transforms import TRANSFORM_PRESETS
from synth_tab import (
    BPM_MAX,
    BPM_MIN,
    ROOT_NOTE_CHOICES,
    SYNTH_GRID_SIZE,
    SYNTH_SOURCE_ROWS,
    SYNTH_TRANSFORM_ROWS,
    next_selection,
    parse_bpm,
    source_preset_id,
    transform_preset_id,
)


def test_source_grid_covers_all_25_source_presets():
    ids = {
        source_preset_id(r, c)
        for r in range(SYNTH_GRID_SIZE)
        for c in range(SYNTH_GRID_SIZE)
    }
    assert ids == {p["id"] for p in SOURCE_PRESETS}
    assert len(ids) == 25


def test_transform_grid_covers_all_25_transform_presets():
    ids = {
        transform_preset_id(r, c)
        for r in range(SYNTH_GRID_SIZE)
        for c in range(SYNTH_GRID_SIZE)
    }
    assert ids == {p["id"] for p in TRANSFORM_PRESETS}
    assert len(ids) == 25


def test_grid_rows_map_to_declared_engines():
    assert SYNTH_SOURCE_ROWS == ("additive", "granular", "resonant", "noise", "texture")
    assert SYNTH_TRANSFORM_ROWS == ("delay", "spectral", "pitch", "grainfx", "spatial")
    # every id in a source row belongs to that row's engine
    by_engine = {}
    for p in SOURCE_PRESETS:
        by_engine.setdefault(p["engine"], []).append(p["id"])
    for r, engine in enumerate(SYNTH_SOURCE_ROWS):
        row_ids = [source_preset_id(r, c) for c in range(SYNTH_GRID_SIZE)]
        assert row_ids == by_engine[engine]


def test_root_note_choices_include_default_d4():
    assert ("D4", 62) in ROOT_NOTE_CHOICES
    for label, midi in ROOT_NOTE_CHOICES:
        assert isinstance(label, str)
        assert isinstance(midi, int)


def test_next_selection_single_select_toggle():
    assert next_selection(None, (0, 0)) == (0, 0)
    assert next_selection((0, 0), (1, 2)) == (1, 2)
    assert next_selection((1, 2), (1, 2)) is None  # click selected cell -> clear


def test_parse_bpm_clamps_and_rejects_garbage():
    assert parse_bpm("90") == 90.0
    assert parse_bpm("5") == BPM_MIN
    assert parse_bpm("9000") == BPM_MAX
    assert parse_bpm("not a number") is None
    assert parse_bpm("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synth_tab.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'synth_tab'`.

- [ ] **Step 3: Write minimal implementation**

```python
# audio_prototype/synth_tab.py
"""Synth tab: two 5x5 preset grids (source + transform) driving a
SynthAudioEngine. This module holds the pure grid/selection/parsing helpers
(unit-tested without Tk) and the SynthTab widget builder (added in a later
task)."""

from soundscape_sources import SOURCE_PRESETS
from soundscape_transforms import TRANSFORM_PRESETS

SYNTH_GRID_SIZE = 5
SYNTH_SOURCE_ROWS = ("additive", "granular", "resonant", "noise", "texture")
SYNTH_TRANSFORM_ROWS = ("delay", "spectral", "pitch", "grainfx", "spatial")

BPM_MIN = 20.0
BPM_MAX = 300.0

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def _grouped(presets, rows):
    by_engine = {}
    for p in presets:
        by_engine.setdefault(p["engine"], []).append(p["id"])
    return [tuple(by_engine[row]) for row in rows]


_SOURCE_GRID = _grouped(SOURCE_PRESETS, SYNTH_SOURCE_ROWS)
_TRANSFORM_GRID = _grouped(TRANSFORM_PRESETS, SYNTH_TRANSFORM_ROWS)


def source_preset_id(row, col):
    return _SOURCE_GRID[row][col]


def transform_preset_id(row, col):
    return _TRANSFORM_GRID[row][col]


def _midi_label(midi):
    return f"{_NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


ROOT_NOTE_CHOICES = [(_midi_label(m), m) for m in range(48, 85)]  # C3..C6


def next_selection(current, clicked):
    """Single-select toggle: clicking a new cell selects it; clicking the
    currently-selected cell clears the selection."""
    return None if current == clicked else clicked


def parse_bpm(text):
    try:
        bpm = float(text)
    except (TypeError, ValueError):
        return None
    return float(min(BPM_MAX, max(BPM_MIN, bpm)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synth_tab.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/synth_tab.py audio_prototype/tests/test_synth_tab.py
git commit -m "feat(synth): add synth-tab grid/selection/bpm pure helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `SynthTab` widget

**Files:**
- Modify: `audio_prototype/synth_tab.py`
- Test: `audio_prototype/tests/test_synth_tab.py`

**Interfaces:**
- Consumes: `tkinter`/`ttk`, `matplotlib`, `colorsys`, the Task 5 helpers, `gui._picker_coords_to_hsv`/`_random_scan_values`/`PICKER_W`/`PICKER_H` (module-level import — `gui` imports `synth_tab` only lazily, so no cycle), `synth_audio_engine.SynthAudioEngine` (passed in, not imported).
- Produces: `class SynthTab(parent, synth_engine)` that builds the full Synth-tab UI into `parent` and starts its own waveform-refresh `after` loop. Exposes `.frame` (the container), `.selected_source`, `.selected_transform`, `.refresh_ms`, and calls `synth_engine.connect_patch/disconnect_patch/load_sample/set_root_midi`.

- [ ] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_synth_tab.py
import tkinter as tk

import pytest

from synth_audio_engine import SynthAudioEngine
from synth_tab import SYNTH_GRID_SIZE, SynthTab


def _tk_root_or_skip():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk widget test")
    root.withdraw()
    return root


def test_synth_tab_builds_two_grids_of_buttons():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        assert len(tab.source_cells) == SYNTH_GRID_SIZE * SYNTH_GRID_SIZE
        assert len(tab.transform_cells) == SYNTH_GRID_SIZE * SYNTH_GRID_SIZE
    finally:
        root.destroy()


def test_synth_tab_connect_adds_a_patch():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        tab._select_source(0, 1)          # additive_2
        tab.bpm_var.set("90")
        tab._on_connect()
        assert len(eng.active_patches()) == 1
        assert eng.active_patches()[0]["source_preset"] == "additive_2"
    finally:
        root.destroy()


def test_synth_tab_connect_without_source_is_noop():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        tab.bpm_var.set("90")
        tab._on_connect()  # no source selected
        assert eng.active_patches() == []
    finally:
        root.destroy()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synth_tab.py -k widget -v` (and the three new tests)
Expected: FAIL — `ImportError: cannot import name 'SynthTab'`.

- [ ] **Step 3: Write minimal implementation**

Append to `synth_tab.py`:

```python
import colorsys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from gui import PICKER_H, PICKER_W, _picker_coords_to_hsv, _random_scan_values

WAVEFORM_WINDOW_SAMPLES = 4096
WAVEFORM_FIGSIZE = (7.2, 1.7)
REFRESH_MS = 50
SYNTH_CELL_W = 6  # button width in text units


class SynthTab:
    """Builds the Synth-tab UI: two 5x5 preset grids, a finger-color picker,
    BPM entry, root-note selector, Connect button, active-patch list, a
    Load Sample button, and a waveform view fed by the SynthAudioEngine."""

    def __init__(self, parent, synth_engine):
        self.parent = parent
        self.engine = synth_engine
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="both", expand=True)
        self.refresh_ms = REFRESH_MS

        self.selected_source = None
        self.selected_transform = None
        self.source_cells = {}
        self.transform_cells = {}
        self._patch_rows = {}

        self.hue_var = tk.DoubleVar(value=0.0)
        self.sat_var = tk.DoubleVar(value=0.75)
        self.val_var = tk.DoubleVar(value=0.64)
        self.bpm_var = tk.StringVar(value="70")
        self.root_var = tk.StringVar()

        self._build_grids()
        self._build_color_controls()
        self._build_root_control()
        self._build_action_controls()
        self._build_patch_list()
        self._build_waveform()
        self._schedule_refresh()

    # ---------- grids ----------

    def _build_grids(self):
        wrapper = ttk.Frame(self.frame)
        wrapper.grid(row=0, column=0, columnspan=2, sticky="nw", padx=8, pady=8)
        self._build_one_grid(
            wrapper, 0, "Sources", SYNTH_SOURCE_ROWS, self.source_cells,
            self._select_source,
        )
        self._build_one_grid(
            wrapper, 1, "Transforms (optional)", SYNTH_TRANSFORM_ROWS,
            self.transform_cells, self._select_transform,
        )

    def _build_one_grid(self, parent, col, title, rows, cells, on_click):
        box = ttk.LabelFrame(parent, text=title)
        box.grid(row=0, column=col, sticky="nw", padx=(0, 16))
        for c in range(SYNTH_GRID_SIZE):
            ttk.Label(box, text=str(c + 1)).grid(row=0, column=c + 1, padx=1)
        for r, name in enumerate(rows):
            ttk.Label(box, text=name).grid(row=r + 1, column=0, sticky="e", padx=(0, 4))
            for c in range(SYNTH_GRID_SIZE):
                btn = tk.Button(
                    box, width=SYNTH_CELL_W, relief="raised",
                    command=lambda rr=r, cc=c: on_click(rr, cc),
                )
                btn.grid(row=r + 1, column=c + 1, padx=1, pady=1)
                cells[(r, c)] = btn

    def _paint_grid(self, cells, selected):
        for (r, c), btn in cells.items():
            btn.configure(
                relief="sunken" if (r, c) == selected else "raised",
                bg="#ffd27f" if (r, c) == selected else "SystemButtonFace",
            )

    def _select_source(self, row, col):
        self.selected_source = next_selection(self.selected_source, (row, col))
        self._paint_grid(self.source_cells, self.selected_source)

    def _select_transform(self, row, col):
        self.selected_transform = next_selection(self.selected_transform, (row, col))
        self._paint_grid(self.transform_cells, self.selected_transform)

    # ---------- color ----------

    def _build_color_controls(self):
        frame = ttk.LabelFrame(self.frame, text="Finger color + BPM")
        frame.grid(row=1, column=0, sticky="nw", padx=8, pady=(0, 8))
        self.picker = tk.Canvas(
            frame, width=PICKER_W, height=PICKER_H, highlightthickness=1, cursor="cross"
        )
        self.picker.grid(row=0, column=0, columnspan=3, sticky="w")
        self._picker_image = self._build_picker_image()
        self.picker.create_image(0, 0, anchor="nw", image=self._picker_image)
        self._marker = self.picker.create_oval(0, 0, 0, 0, outline="white", width=2)
        self.picker.bind("<Button-1>", lambda e: self._set_pick(e.x, e.y))
        self.picker.bind("<B1-Motion>", lambda e: self._set_pick(e.x, e.y))

        ttk.Label(frame, text="BPM").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(frame, textvariable=self.bpm_var, width=8).grid(
            row=1, column=1, sticky="w", pady=(6, 0)
        )
        self.swatch = tk.Canvas(frame, width=40, height=40, highlightthickness=1)
        self.swatch.grid(row=1, column=2, padx=8)
        ttk.Button(frame, text="Random", command=self._on_random).grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
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

    # ---------- root note ----------

    def _build_root_control(self):
        frame = ttk.LabelFrame(self.frame, text="Harmonic root")
        frame.grid(row=1, column=1, sticky="nw", padx=8, pady=(0, 8))
        labels = [label for label, _midi in ROOT_NOTE_CHOICES]
        self._root_by_label = {label: midi for label, midi in ROOT_NOTE_CHOICES}
        current = next(
            label for label, midi in ROOT_NOTE_CHOICES if midi == self.engine.root_midi
        )
        self.root_var.set(current)
        ttk.Combobox(
            frame, textvariable=self.root_var, values=labels, state="readonly", width=6
        ).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(frame, text="Apply (clears patches)", command=self._on_apply_root).grid(
            row=0, column=1, padx=4
        )

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

    # ---------- actions ----------

    def _build_action_controls(self):
        frame = ttk.Frame(self.frame)
        frame.grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))
        ttk.Button(frame, text="Connect patch", command=self._on_connect).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(frame, text="Load Sample...", command=self._on_load_sample).grid(
            row=0, column=1
        )

    def _on_connect(self):
        if self.selected_source is None:
            messagebox.showinfo("No source", "Select a source preset first.")
            return
        bpm = parse_bpm(self.bpm_var.get())
        if bpm is None:
            messagebox.showerror("Invalid BPM", f"BPM must be a number ({self.bpm_var.get()!r}).")
            return
        source_id = source_preset_id(*self.selected_source)
        transform_id = (
            transform_preset_id(*self.selected_transform)
            if self.selected_transform is not None
            else None
        )
        pid = self.engine.connect_patch(
            self.hue_var.get(), self.sat_var.get(), self.val_var.get(),
            bpm, source_id, transform_id,
        )
        self._add_patch_row(pid, bpm, source_id, transform_id, self._color_hex())

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

    # ---------- patch list ----------

    def _build_patch_list(self):
        frame = ttk.LabelFrame(self.frame, text="Active patches")
        frame.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        self.frame.rowconfigure(3, weight=1)
        self.frame.columnconfigure(0, weight=1)
        canvas = tk.Canvas(frame, height=140, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
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
        row = self._patch_rows.pop(pid, None)
        if row is not None:
            row.destroy()

    # ---------- waveform ----------

    def _build_waveform(self):
        frame = ttk.LabelFrame(self.frame, text="Waveform")
        frame.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        fig = Figure(figsize=WAVEFORM_FIGSIZE)
        self.ax = fig.add_subplot(111)
        (self.line,) = self.ax.plot(
            np.zeros(WAVEFORM_WINDOW_SAMPLES), color="tab:blue", linewidth=1.2
        )
        self.ax.set_ylim(-1.05, 1.05)
        self.ax.set_xticks([])
        self.canvas = FigureCanvasTkAgg(fig, master=frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _schedule_refresh(self):
        data = self.engine.visual_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        self.line.set_ydata(data)
        self.canvas.draw_idle()
        self.parent.after(self.refresh_ms, self._schedule_refresh)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synth_tab.py -v`
Expected: PASS (9 tests total; the 3 Tk widget tests run on a machine with a display and `skip` headless).

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/synth_tab.py audio_prototype/tests/test_synth_tab.py
git commit -m "feat(synth): add SynthTab widget (grids, picker, patch list, waveform)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Wrap `gui.py` in a Notebook and mount the Synth tab

**Files:**
- Modify: `audio_prototype/gui.py`
- Test: `audio_prototype/tests/test_gui.py`

**Interfaces:**
- Consumes: `synth_tab.SynthTab` (lazy import inside a method to avoid an import cycle — `synth_tab` imports `gui` at module level).
- Produces: `RedPoleGUI(root, engine, synth_engine, default_loop_path)` — a `ttk.Notebook` with "Loop" (existing widgets, reparented, behavior unchanged) and "Synth" tabs; `<<NotebookTabChanged>>` pauses the outgoing engine and resumes the incoming one. Adds `.notebook`, `.loop_tab`, `.synth_tab_frame`, `.synth_tab`, `._on_tab_changed(event)`.

- [ ] **Step 1: Write the failing test**

```python
# append to audio_prototype/tests/test_gui.py
import tkinter as tk

import pytest


class _StubEngine:
    """Minimal engine stand-in: records pause/resume, no real stream."""

    def __init__(self):
        self.paused = True
        self.calls = []

    def pause(self):
        self.paused = True
        self.calls.append("pause")

    def resume(self):
        self.paused = False
        self.calls.append("resume")


def _tk_root_or_skip():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk widget test")
    root.withdraw()
    return root


def test_gui_constructor_accepts_synth_engine():
    import inspect

    from gui import RedPoleGUI

    params = list(inspect.signature(RedPoleGUI.__init__).parameters)
    assert params == ["self", "root", "engine", "synth_engine", "default_loop_path"]


def test_switching_to_synth_tab_pauses_loop_and_resumes_synth():
    root = _tk_root_or_skip()
    try:
        from synth_audio_engine import SynthAudioEngine
        from gui import RedPoleGUI

        loop = _StubEngine()
        loop.registry = None  # not touched before a tab switch
        synth = SynthAudioEngine(seed=1)
        # Avoid opening a real audio device in the test.
        synth.resume = lambda: synth.__dict__.__setitem__("_resumed", True)
        synth.pause = lambda: None
        # Build with a stub loop engine that also has the attributes the Loop
        # tab needs; simpler to skip full loop-tab wiring by monkeypatching.
        pytest.skip("covered by manual launch; see Task 8 Step 2")
    finally:
        root.destroy()
```

> Note: the second test is intentionally skipped — fully constructing `RedPoleGUI` needs a loaded loop and audio device, which belongs to the manual launch check in Task 8. The `inspect`-based signature test is the real automated guard that the constructor gained `synth_engine` without breaking its shape.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_gui.py -k synth_engine -v`
Expected: FAIL — `AssertionError` on the parameter-list check (current signature is `[self, root, engine, default_loop_path]`).

- [ ] **Step 3: Write minimal implementation**

Make these edits to `gui.py`:

1. Add `Notebook`-based layout. Change `__init__` signature and the layout bootstrap:

```python
    def __init__(self, root, engine, synth_engine, default_loop_path):
        self.root = root
        self.engine = engine
        self.synth_engine = synth_engine
        self.root.title("RedPole Audio Prototype")
        self._layer_rows = {}
        self._source_colors = {}
        self._drag_source_id = None
        self._drag_line = None

        self.hue_var = tk.DoubleVar(value=0.0)
        self.sat_var = tk.DoubleVar(value=0.75)
        self.val_var = tk.DoubleVar(value=0.64)
        self.bpm_var = tk.StringVar(value="70")
        self.wet_dry_var = tk.DoubleVar(value=self.engine.wet_dry)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        self.loop_tab = ttk.Frame(self.notebook)
        self.synth_tab_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.loop_tab, text="Loop")
        self.notebook.add(self.synth_tab_frame, text="Synth")

        self._build_layout_frames()
        self._build_controls()
        self._build_audition_controls()
        self._build_layer_list()
        self._build_waveform()
        self._build_patch_bay()
        self._build_synth_tab()
        self._load_initial_loop(default_loop_path)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._schedule_refresh()
```

2. Reparent the Loop widgets from `self.root` to `self.loop_tab`. In `_build_layout_frames`, `_build_waveform`, and `_build_patch_bay`, replace every `self.root` used as a **grid parent or grid geometry target** with `self.loop_tab`:

```python
    def _build_layout_frames(self):
        self.left_column = ttk.Frame(self.loop_tab)
        self.left_column.grid(**LEFT_COLUMN_GRID)
        self.left_column.columnconfigure(0, weight=1)
        self.left_column.rowconfigure(LEFT_STACK_ROWS["scan_sources"], weight=1)
```

```python
    def _build_waveform(self):
        frame = ttk.LabelFrame(self.loop_tab, text="Waveform")
        frame.grid(row=1, column=1, sticky="nsew", padx=8, pady=(0, 8))
        self.loop_tab.columnconfigure(1, weight=1)
        self.loop_tab.rowconfigure(0, weight=3)
        self.loop_tab.rowconfigure(1, weight=1)
        # ... rest of the method body is UNCHANGED ...
```

```python
    def _build_patch_bay(self):
        frame = ttk.LabelFrame(self.loop_tab, text="Patch Bay")
        frame.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        # ... rest of the method body is UNCHANGED ...
```

(Leave `_build_controls`, `_build_audition_controls`, `_build_layer_list` unchanged — they already parent into `self.left_column`, which now lives under `loop_tab`.)

3. Add the Synth-tab builder and the tab-change handler (new methods, e.g. after `_build_patch_bay`):

```python
    def _build_synth_tab(self):
        from synth_tab import SynthTab  # lazy import avoids gui<->synth_tab cycle

        self.synth_tab = SynthTab(self.synth_tab_frame, self.synth_engine)

    def _on_tab_changed(self, _event):
        tab = self.notebook.tab(self.notebook.select(), "text")
        if tab == "Synth":
            self.engine.pause()
            try:
                self.synth_engine.resume()
            except Exception as exc:  # audio device failed to open
                messagebox.showerror("Synth audio", f"Could not start synth audio: {exc}")
                self.notebook.select(self.loop_tab)
                self.engine.resume()
        else:
            self.synth_engine.pause()
            self.engine.resume()
```

4. Make the waveform refresh read the active tab's engine. Replace `_refresh_waveform` so the Loop waveform only updates when the Loop tab is active (the Synth tab runs its own refresh loop inside `SynthTab`):

```python
    def _refresh_waveform(self):
        if self.notebook.tab(self.notebook.select(), "text") != "Loop":
            return
        data = self.engine.visual_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        warble = self.engine.warble_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        bloom = self.engine.bloom_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        wet = self.engine.wet_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        self.line.set_ydata(data)
        self.warble_line.set_ydata(warble / MAX_WARBLE_DEPTH)
        self.bloom_line.set_ydata(bloom / MAX_BLOOM_DEPTH)
        self.wet_line.set_ydata(wet)
        self.canvas.draw_idle()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_gui.py -v`
Expected: PASS — the signature test passes and every pre-existing `test_gui` helper test is unchanged (they import module-level helpers/constants, none of which moved).

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/gui.py audio_prototype/tests/test_gui.py
git commit -m "feat(synth): mount Synth tab in a Notebook alongside the Loop tab

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Wire both engines in `main.py`, verify, refresh brief

**Files:**
- Modify: `audio_prototype/main.py`
- Modify: `AGENTS.md` (lines 6-14, "Pick up here")

**Interfaces:**
- Consumes: `AudioEngine`, `synth_audio_engine.SynthAudioEngine`, `gui.RedPoleGUI`.
- Produces: an app that builds both engines, passes both to `RedPoleGUI`, and stops both on exit.

- [ ] **Step 1: Update `main.py`**

Replace the body of `main()` so both engines are built and both are stopped on exit:

```python
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from audio_engine import AudioEngine
from gui import RedPoleGUI
from synth_audio_engine import SynthAudioEngine

DEFAULT_LOOP_PATH = Path(__file__).parent / "assets" / "sample_loop.wav"


def main():
    engine = AudioEngine()
    synth_engine = SynthAudioEngine()
    root = tk.Tk()
    try:
        RedPoleGUI(root, engine, synth_engine, str(DEFAULT_LOOP_PATH))
    except Exception as exc:
        messagebox.showerror("RedPole Audio Prototype", f"Failed to start: {exc}")
        sys.exit(1)
    root.mainloop()
    engine.stop()
    synth_engine.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual launch verification (has a display; do NOT run in headless CI)**

Run from `audio_prototype/`: `py -3.11 main.py`
Expected:
- Window opens on the **Loop** tab; the loop plays exactly as before.
- Switching to the **Synth** tab silences the loop; clicking a source cell (e.g. `additive` col 2), optionally a transform cell, setting BPM, and pressing **Connect** adds an audible patch and a row in "Active patches"; the waveform moves.
- **Remove** silences that patch; **Load Sample...** loads a file for `texture_*` patches; **Apply** on a new root note warns, then clears patches.
- Switching back to **Loop** resumes the loop; closing the window exits cleanly with no stream errors.

This step is a human check — a subagent without a display should mark it done-by-inspection and note that automated coverage lives in Tasks 2-7.

- [ ] **Step 3: Run the full suite**

Run from `audio_prototype/`: `py -3.11 -m pytest tests/ -v`
Expected: PASS — every pre-existing test (378 baseline) plus the new `test_audio_io` (5), `test_synth_audio_engine` (17), `test_synth_tab` (6 headless / 9 with display), and the `test_gui` signature test. Zero pre-existing tests changed or broke.

- [ ] **Step 4: Refresh the "Pick up here" brief**

Update `AGENTS.md` lines 6-14 to:

```markdown
## ⏱ Pick up here   ← LIVING; refresh at session end
- **Status:**       Prototype — the desktop app (audio_prototype/main.py) now has a ttk.Notebook with two tabs: the existing **Loop** tab (unchanged) and a new **Synth** tab that drives the Phase 1 SoundscapeEngine live via SynthAudioEngine (synth_audio_engine.py) + SynthTab (synth_tab.py). Users pick a source preset and optional transform preset from two 5x5 grids, set a finger-scan color + BPM, Connect/Remove patches, Load a texture sample, and retune the harmonic root. Only the active tab's stream plays. Web app Loop/Synth modes untouched; firmware/TD integration still WIP.
- **Last session:** 2026-07-23 — implemented the interactive Synth tab (phase 2, first pass) per docs/superpowers/plans/2026-07-23-synth-tab-phase2.md: extracted audio_io.py, added SynthAudioEngine (stream lifecycle + sample load + root retune, thread-guarded) and the SynthTab UI, wrapped gui.py in a Notebook with tab-based stream handoff.
- **Next up:**
  - Tune by ear in the Synth tab: slot/preset ordering, color->timbre feel, transform intensities, root-note choices.
  - Consider a drag-and-drop patch bay for Synth mode and persisting patches between sessions.
  - Wire hardware finger-scan input into the Synth tab (spec Phase 3).
  - Document the firmware serial message shape (base64 JPEG framing).
- **Blockers / open questions:** Is TD driven by the web app, the Python engine, or the device directly?
```

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/main.py AGENTS.md
git commit -m "feat(synth): wire SynthAudioEngine into main.py and refresh brief

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Notes (for the implementer)

- **Import cycle:** `synth_tab` imports `gui` at module level; `gui` imports `synth_tab` **only** inside `_build_synth_tab` (lazy). Do not move the `synth_tab` import to the top of `gui.py` or you will create a cycle.
- **Re-exports:** after Task 1, confirm `python -c "import audio_engine; audio_engine.read_mono_audio"` still resolves; after Task 7, confirm `from gui import _picker_coords_to_hsv, _random_scan_values, PICKER_W, PICKER_H` still resolves (these never moved).
- **Thread safety:** all `self.engine` mutation/reads in `SynthAudioEngine` go through `self._lock`; never call `self.engine.*` from `SynthTab` directly — always via the `SynthAudioEngine` methods.
- **Two open streams:** on a tab switch the outgoing stream is `stop()`-ed (not closed), so both `OutputStream`s stay open but only one is running — this matches the existing `AudioEngine.pause()` pattern and is intentional.
