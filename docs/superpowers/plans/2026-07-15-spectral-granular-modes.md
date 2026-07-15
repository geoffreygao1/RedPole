# Spectral & Granular Engine Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two pronounced, per-layer-voiced processing modes — Panharmonium-style spectral resynthesis and heartbeat-clustered granular synthesis — selectable from a GUI dropdown alongside the existing tape mode.

**Architecture:** `AudioEngine.generate_block` becomes a mode dispatcher. Tape mode keeps its existing path. Spectral/Granular modes play the dry loop from a shared read position and add per-layer voices from a new processor module each (`spectral_processor.py`, `granular_processor.py`); the summed voices ("wet") also feed a new ring buffer for visualization. `LayerRegistry.snapshot()` gains an `id` per layer so processors can keep per-layer voice state across blocks.

**Tech Stack:** Same as base prototype (numpy, soundfile, sounddevice, matplotlib, Tkinter, pytest). No new dependencies.

## Global Constraints

- Sample rate stays 44100 Hz; spectral analysis constants: `FFT_SIZE = 4096`, `HOP_SIZE = 1024`, `N_PARTIALS = 24`.
- Hue→pitch mappings treat hue as circular with red (0.0/1.0) at center: `semitones = span * (hue if hue <= 0.5 else hue - 1.0)`; span is 14 for spectral (±7 st) and 24 for granular (±12 st).
- Spectral analysis runs only in `load_loop` (GUI thread), never in the audio callback; a missing/failed analysis makes Spectral mode dry-only, not a crash.
- 0 layers in any mode must reproduce the dry loop exactly (existing tape passthrough tests must keep passing).
- Wet output is normalized by `sqrt(layer_count)` then soft-clipped with the existing `modulation.soft_clip`.
- All code in `audio_prototype/`, tests in `audio_prototype/tests/`, run with `.venv/Scripts/python.exe -m pytest`.

---

### Task 1: LayerRegistry snapshot includes layer ids

**Files:**
- Modify: `audio_prototype/layers.py`
- Test: `audio_prototype/tests/test_layers.py`

**Interfaces:**
- Produces: `LayerRegistry.snapshot() -> list[dict]` where each dict now has keys `id`, `hue`, `sat`, `val`, `bpm`. Later tasks key per-voice state on `layer["id"]`.

- [ ] **Step 1: Update the snapshot test to expect ids**

In `audio_prototype/tests/test_layers.py`, replace `test_snapshot_reflects_added_layers` with:

```python
def test_snapshot_reflects_added_layers():
    reg = LayerRegistry()
    layer_id = reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
    snap = reg.snapshot()
    assert len(snap) == 1
    assert snap[0] == {"id": layer_id, "hue": 0.1, "sat": 0.5, "val": 0.5, "bpm": 70}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_layers.py -v`
Expected: FAIL (`id` key missing from snapshot dict)

- [ ] **Step 3: Include the id in stored layers**

In `audio_prototype/layers.py`, change `add` to store the id inside the dict:

```python
    def add(self, hue, sat, val, bpm):
        with self._lock:
            layer_id = self._next_id
            self._next_id += 1
            self._layers[layer_id] = {
                "id": layer_id, "hue": hue, "sat": sat, "val": val, "bpm": bpm
            }
            return layer_id
```

- [ ] **Step 4: Run full suite to verify nothing else broke**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest -q`
Expected: all pass (`combine_layers` only reads `hue`/`sat`/`val`/`bpm`, ignores `id`)

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/layers.py audio_prototype/tests/test_layers.py
git commit -m "feat: include layer id in registry snapshots"
```

---

### Task 2: Spectral analysis (`analyze_loop`)

**Files:**
- Create: `audio_prototype/spectral_processor.py`
- Test: `audio_prototype/tests/test_spectral_processor.py`

**Interfaces:**
- Produces: `analyze_loop(loop_array, samplerate, n_partials=24, fft_size=4096, hop_size=1024) -> dict` with keys `freqs` (ndarray `[n_frames, n_partials]`, Hz), `amps` (same shape, normalized to global max 1.0), `frame_rate` (analysis frames per second of original audio = `samplerate / hop_size`). Constants `N_PARTIALS`, `FFT_SIZE`, `HOP_SIZE` exported.

- [ ] **Step 1: Write the failing tests**

Create `audio_prototype/tests/test_spectral_processor.py`:

```python
import numpy as np
import pytest

from spectral_processor import N_PARTIALS, SpectralProcessor, analyze_loop

SR = 44100


def _tone(freq, seconds=2.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_analyze_loop_shapes():
    loop = _tone(440.0)
    analysis = analyze_loop(loop, SR)
    n_frames = analysis["freqs"].shape[0]
    assert n_frames > 10
    assert analysis["freqs"].shape == (n_frames, N_PARTIALS)
    assert analysis["amps"].shape == (n_frames, N_PARTIALS)
    assert analysis["frame_rate"] == pytest.approx(SR / 1024)


def test_analyze_loop_finds_test_tone():
    loop = _tone(440.0)
    analysis = analyze_loop(loop, SR)
    # strongest partial of a mid frame should be ~440 Hz
    mid = analysis["freqs"].shape[0] // 2
    strongest = analysis["freqs"][mid][np.argmax(analysis["amps"][mid])]
    assert strongest == pytest.approx(440.0, abs=SR / 4096 * 1.5)


def test_analyze_loop_amps_normalized():
    loop = _tone(440.0)
    analysis = analyze_loop(loop, SR)
    assert analysis["amps"].max() == pytest.approx(1.0)


def test_analyze_loop_handles_short_input():
    loop = _tone(440.0, seconds=0.05)  # shorter than one FFT window
    analysis = analyze_loop(loop, SR)
    assert analysis["freqs"].shape[0] >= 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_spectral_processor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spectral_processor'`

- [ ] **Step 3: Implement `analyze_loop` (and stub the class for the import)**

Create `audio_prototype/spectral_processor.py`:

```python
import numpy as np

N_PARTIALS = 24
FFT_SIZE = 4096
HOP_SIZE = 1024


def analyze_loop(loop_array, samplerate, n_partials=N_PARTIALS,
                 fft_size=FFT_SIZE, hop_size=HOP_SIZE):
    """Precompute the loop's 'spectral movie': per-frame strongest partials.

    Runs offline at load time (never in the audio callback). Returns freqs
    and amps arrays of shape [n_frames, n_partials] plus the analysis
    frame_rate in frames per second of original audio.
    """
    loop_array = np.asarray(loop_array, dtype=np.float64)
    if len(loop_array) < fft_size:
        loop_array = np.pad(loop_array, (0, fft_size - len(loop_array)))

    window = np.hanning(fft_size)
    starts = np.arange(0, len(loop_array) - fft_size + 1, hop_size)
    bin_freqs = np.fft.rfftfreq(fft_size, 1.0 / samplerate)

    freqs = np.zeros((len(starts), n_partials))
    amps = np.zeros((len(starts), n_partials))
    for i, s in enumerate(starts):
        mag = np.abs(np.fft.rfft(loop_array[s:s + fft_size] * window))
        # local-maxima peak picking, strongest first
        peaks = np.where((mag[1:-1] > mag[:-2]) & (mag[1:-1] > mag[2:]))[0] + 1
        if len(peaks) == 0:
            continue
        top = peaks[np.argsort(mag[peaks])[::-1][:n_partials]]
        freqs[i, :len(top)] = bin_freqs[top]
        amps[i, :len(top)] = mag[top]

    peak = amps.max()
    if peak > 0:
        amps /= peak
    return {"freqs": freqs, "amps": amps, "frame_rate": samplerate / hop_size}


class SpectralProcessor:
    """Implemented in Task 3."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self.analysis = None
        self._voices = {}
```

- [ ] **Step 4: Run analysis tests to verify they pass**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_spectral_processor.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/spectral_processor.py audio_prototype/tests/test_spectral_processor.py
git commit -m "feat: add offline spectral analysis (partial extraction)"
```

---

### Task 3: SpectralProcessor per-layer voices

**Files:**
- Modify: `audio_prototype/spectral_processor.py`
- Test: `audio_prototype/tests/test_spectral_processor.py`

**Interfaces:**
- Consumes: `analyze_loop` output; layer dicts with `id`, `hue`, `sat`, `val`, `bpm`.
- Produces: `SpectralProcessor(samplerate, seed=None)` with `set_analysis(analysis_or_None)` and `process(loop_array, frames, layers) -> np.ndarray` (float32, wet-only voices sum; zeros when no layers or no analysis). Per-voice state keyed by `layer["id"]` persists across calls.

- [ ] **Step 1: Add failing tests**

Append to `audio_prototype/tests/test_spectral_processor.py`:

```python
def _layer(layer_id, hue=0.0, sat=0.5, val=1.0, bpm=120.0):
    return {"id": layer_id, "hue": hue, "sat": sat, "val": val, "bpm": bpm}


def _dominant_freq(signal, sr=SR):
    mag = np.abs(np.fft.rfft(signal * np.hanning(len(signal))))
    return np.fft.rfftfreq(len(signal), 1.0 / sr)[np.argmax(mag)]


def test_process_no_layers_is_silent():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    out = proc.process(loop, 1024, [])
    np.testing.assert_allclose(out, np.zeros(1024))


def test_process_without_analysis_is_silent():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(None)
    out = proc.process(loop, 1024, [_layer(1)])
    np.testing.assert_allclose(out, np.zeros(1024))


def test_voice_reproduces_tone_pitch():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    layer = _layer(1, hue=0.0)  # red center = no pitch shift
    # run a few blocks so blur settles, then measure
    for _ in range(20):
        out = proc.process(loop, 4096, [layer])
    assert _dominant_freq(out) == pytest.approx(440.0, abs=15.0)


def test_hue_shifts_pitch_up():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    layer = _layer(1, hue=0.25)  # +3.5 semitones
    for _ in range(20):
        out = proc.process(loop, 4096, [layer])
    expected = 440.0 * 2 ** (3.5 / 12)
    assert _dominant_freq(out) == pytest.approx(expected, abs=15.0)


def test_stale_voices_are_dropped():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    proc.process(loop, 1024, [_layer(1), _layer(2)])
    assert set(proc._voices.keys()) == {1, 2}
    proc.process(loop, 1024, [_layer(2)])
    assert set(proc._voices.keys()) == {2}
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_spectral_processor.py -v`
Expected: the 5 new tests FAIL (no `set_analysis`/`process`), 4 analysis tests still pass

- [ ] **Step 3: Implement the processor**

Replace the `SpectralProcessor` stub in `audio_prototype/spectral_processor.py` with:

```python
class SpectralProcessor:
    """Per-layer oscillator-bank resynthesis of the precomputed analysis.

    Each active layer is an independent voice scanning the spectral movie:
    hue -> pitch shift (+/-7 st, red centered), bpm -> scan speed,
    sat -> blur (frame smoothing), val -> voice level.
    """

    VOICE_LEVEL = 0.3

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self.analysis = None
        self._voices = {}

    def set_analysis(self, analysis):
        self.analysis = analysis
        self._voices = {}

    def process(self, loop_array, frames, layers):
        out = np.zeros(frames)
        if self.analysis is None or not layers:
            self._voices = {}
            return out.astype(np.float32)

        freqs_movie = self.analysis["freqs"]
        amps_movie = self.analysis["amps"]
        n_frames = freqs_movie.shape[0]
        n_partials = freqs_movie.shape[1]
        t = np.arange(frames) / self.samplerate

        active = set()
        for layer in layers:
            vid = layer["id"]
            active.add(vid)
            voice = self._voices.get(vid)
            if voice is None:
                voice = {
                    "phases": np.zeros(n_partials),
                    "scan": 0.0,
                    "freqs": freqs_movie[0].copy(),
                    "amps": amps_movie[0].copy(),
                }
                self._voices[vid] = voice

            hue = layer["hue"]
            semitones = 14.0 * (hue if hue <= 0.5 else hue - 1.0)
            shift = 2.0 ** (semitones / 12.0)
            scan_rate = (layer["bpm"] / 120.0) * self.analysis["frame_rate"]
            # sat -> blur: more saturation = slower tracking = more smear
            blur = 0.5 + 0.45 * layer["sat"]
            level = self.VOICE_LEVEL * layer["val"]

            frame_idx = int(voice["scan"]) % n_frames
            voice["freqs"] = blur * voice["freqs"] + (1.0 - blur) * freqs_movie[frame_idx]
            voice["amps"] = blur * voice["amps"] + (1.0 - blur) * amps_movie[frame_idx]
            voice["scan"] = (voice["scan"] + scan_rate * frames / self.samplerate) % n_frames

            omega = 2.0 * np.pi * voice["freqs"] * shift  # rad/s per partial
            out += level * np.sum(
                voice["amps"][:, None]
                * np.sin(voice["phases"][:, None] + omega[:, None] * t[None, :]),
                axis=0,
            )
            voice["phases"] = (voice["phases"] + omega * frames / self.samplerate) % (
                2.0 * np.pi
            )

        self._voices = {k: v for k, v in self._voices.items() if k in active}
        out /= max(1.0, np.sqrt(len(layers)))
        return out.astype(np.float32)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_spectral_processor.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/spectral_processor.py audio_prototype/tests/test_spectral_processor.py
git commit -m "feat: add SpectralProcessor per-layer oscillator-bank voices"
```

---

### Task 4: GranularProcessor

**Files:**
- Create: `audio_prototype/granular_processor.py`
- Test: `audio_prototype/tests/test_granular_processor.py`

**Interfaces:**
- Consumes: layer dicts with `id`, `hue`, `sat`, `val`, `bpm`.
- Produces: `GranularProcessor(samplerate, seed=None)` with `process(loop_array, frames, layers) -> np.ndarray` (float32, wet-only grain mix; zeros when no layers). Per-voice state keyed by `layer["id"]`; grains burst at each layer's heartbeat period (`samplerate * 60 / bpm`).

- [ ] **Step 1: Write the failing tests**

Create `audio_prototype/tests/test_granular_processor.py`:

```python
import numpy as np

from granular_processor import GranularProcessor

SR = 44100


def _tone(freq, seconds=2.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _layer(layer_id, hue=0.0, sat=0.5, val=1.0, bpm=120.0):
    return {"id": layer_id, "hue": hue, "sat": sat, "val": val, "bpm": bpm}


def test_no_layers_is_silent():
    proc = GranularProcessor(SR, seed=1)
    out = proc.process(_tone(220.0), 1024, [])
    np.testing.assert_allclose(out, np.zeros(1024))
    assert out.dtype == np.float32


def test_layer_produces_grains():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    total = np.concatenate(
        [proc.process(loop, 1024, [_layer(1, bpm=120)]) for _ in range(50)]
    )
    assert np.max(np.abs(total)) > 0.01


def test_bursts_follow_heartbeat_period():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    layer = _layer(1, bpm=120, sat=0.0)  # short grains, pulse every 0.5s
    seconds = 3.0
    total = np.concatenate(
        [proc.process(loop, 1024, [layer])
         for _ in range(int(seconds * SR / 1024) + 1)]
    )
    # energy envelope in 50ms windows: bursts every ~0.5s -> at least 5
    # distinct peaks separated by quiet gaps in 3 seconds
    win = int(0.05 * SR)
    n_win = len(total) // win
    env = np.array([np.abs(total[i * win:(i + 1) * win]).max() for i in range(n_win)])
    threshold = env.max() * 0.2
    loud = env > threshold
    onsets = np.sum(loud[1:] & ~loud[:-1])
    assert onsets >= 4


def test_stale_voices_are_dropped():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    proc.process(loop, 1024, [_layer(1), _layer(2)])
    assert set(proc._voices.keys()) == {1, 2}
    proc.process(loop, 1024, [_layer(2)])
    assert set(proc._voices.keys()) == {2}


def test_output_length_and_state_persist():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    a = proc.process(loop, 700, [_layer(1)])
    b = proc.process(loop, 700, [_layer(1)])
    assert a.shape == (700,)
    assert b.shape == (700,)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_granular_processor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'granular_processor'`

- [ ] **Step 3: Implement the processor**

Create `audio_prototype/granular_processor.py`:

```python
import numpy as np

GRAIN_MIN_SECONDS = 0.06
GRAIN_MAX_SECONDS = 0.25
BURST_GRAINS = 4
BURST_JITTER_SECONDS = 0.08


class GranularProcessor:
    """Per-layer grain streams sampled from the loop.

    hue -> grain pitch shift (+/-12 st, red centered), bpm -> grain bursts
    at the heartbeat period, sat -> grain size, val -> stream level.
    Grains are rendered into a per-voice overlap-add buffer at trigger
    time, so per-block cost is just mixing.
    """

    STREAM_LEVEL = 0.5

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._seed = seed
        self._voices = {}

    def _new_voice(self, vid, frames):
        seed = None if self._seed is None else self._seed + vid
        return {
            "rng": np.random.default_rng(seed),
            "buffer": np.zeros(frames),
            "until_pulse": 0,
        }

    def process(self, loop_array, frames, layers):
        out = np.zeros(frames)
        if not layers or len(loop_array) == 0:
            self._voices = {}
            return out.astype(np.float32)

        active = set()
        for layer in layers:
            vid = layer["id"]
            active.add(vid)
            voice = self._voices.get(vid)
            if voice is None:
                voice = self._new_voice(vid, frames)
                self._voices[vid] = voice

            min_len = frames + int(
                (GRAIN_MAX_SECONDS + BURST_JITTER_SECONDS) * self.samplerate * 2
            )
            if len(voice["buffer"]) < min_len:
                voice["buffer"] = np.concatenate(
                    [voice["buffer"], np.zeros(min_len - len(voice["buffer"]))]
                )

            hue = layer["hue"]
            semitones = 24.0 * (hue if hue <= 0.5 else hue - 1.0)
            ratio = 2.0 ** (semitones / 12.0)
            grain_len = int(
                (GRAIN_MIN_SECONDS
                 + layer["sat"] * (GRAIN_MAX_SECONDS - GRAIN_MIN_SECONDS))
                * self.samplerate
            )
            level = self.STREAM_LEVEL * layer["val"]
            pulse_period = int(self.samplerate * 60.0 / max(layer["bpm"], 1.0))

            t = voice["until_pulse"]
            while t < frames:
                self._emit_burst(voice, loop_array, t, grain_len, ratio, level)
                t += pulse_period
            voice["until_pulse"] = t - frames

            out += voice["buffer"][:frames]
            voice["buffer"] = np.concatenate(
                [voice["buffer"][frames:], np.zeros(frames)]
            )

        self._voices = {k: v for k, v in self._voices.items() if k in active}
        out /= max(1.0, np.sqrt(len(layers)))
        return out.astype(np.float32)

    def _emit_burst(self, voice, loop_array, offset, grain_len, ratio, level):
        rng = voice["rng"]
        loop_len = len(loop_array)
        for _ in range(BURST_GRAINS):
            jitter = int(rng.uniform(0, BURST_JITTER_SECONDS) * self.samplerate)
            start = int(rng.uniform(0, loop_len))
            src_len = max(2, int(grain_len * ratio))
            idx = (start + np.arange(src_len)) % loop_len
            src = loop_array[idx]
            # compress src_len samples into grain_len -> pitch shift by ratio
            grain = np.interp(
                np.linspace(0.0, src_len - 1.0, grain_len),
                np.arange(src_len),
                src,
            )
            grain *= np.hanning(grain_len) * level * rng.uniform(0.6, 1.0)
            pos = offset + jitter
            end = pos + grain_len
            if end > len(voice["buffer"]):
                voice["buffer"] = np.concatenate(
                    [voice["buffer"], np.zeros(end - len(voice["buffer"]))]
                )
            voice["buffer"][pos:end] += grain
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_granular_processor.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/granular_processor.py audio_prototype/tests/test_granular_processor.py
git commit -m "feat: add GranularProcessor with heartbeat-clustered grain bursts"
```

---

### Task 5: AudioEngine mode dispatch

**Files:**
- Modify: `audio_prototype/audio_engine.py`
- Test: `audio_prototype/tests/test_audio_engine.py`

**Interfaces:**
- Consumes: `SpectralProcessor`, `analyze_loop` (Task 2/3), `GranularProcessor` (Task 4), `modulation.soft_clip`.
- Produces: `AudioEngine.MODES = ("tape", "spectral", "granular")`; `engine.mode` property (thread-safe getter) and `engine.set_mode(mode)` (raises `ValueError` on unknown mode); `engine.wet_buffer` (RingBuffer, wet-only signal each block — zeros in tape mode); `load_loop` also runs `analyze_loop` and feeds `spectral.set_analysis` (`None` on analysis failure).

- [ ] **Step 1: Add failing tests**

Append to `audio_prototype/tests/test_audio_engine.py`:

```python
def test_default_mode_is_tape():
    engine = AudioEngine(seed=1)
    assert engine.mode == "tape"


def test_set_mode_validates():
    engine = AudioEngine(seed=1)
    engine.set_mode("spectral")
    assert engine.mode == "spectral"
    with pytest.raises(ValueError):
        engine.set_mode("reverb")


def test_spectral_mode_zero_layers_is_dry():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("spectral")
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)


def test_spectral_mode_layer_changes_output_and_wet_buffer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("spectral")
    engine.registry.add(hue=0.25, sat=0.5, val=1.0, bpm=120)
    block = engine.generate_block(2048)
    dry = engine.loop_array[np.arange(2048) % len(engine.loop_array)]
    assert not np.allclose(block, dry)
    wet = engine.wet_buffer.read_latest(2048)
    assert not np.allclose(wet, np.zeros(2048))


def test_granular_mode_layer_changes_output():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("granular")
    engine.registry.add(hue=0.25, sat=0.5, val=1.0, bpm=180)
    blocks = [engine.generate_block(1024) for _ in range(30)]
    total_wet = engine.wet_buffer.read_latest(1024 * 20)
    assert not np.allclose(total_wet, np.zeros_like(total_wet))
    assert all(b.shape == (1024,) for b in blocks)


def test_tape_mode_writes_zero_wet_buffer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.registry.add(hue=1.0, sat=1.0, val=1.0, bpm=120)
    engine.generate_block(512)
    np.testing.assert_allclose(engine.wet_buffer.read_latest(512), np.zeros(512))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest tests/test_audio_engine.py -v`
Expected: new tests FAIL (`mode`/`set_mode`/`wet_buffer` missing), old tests pass

- [ ] **Step 3: Implement mode dispatch**

Rewrite `audio_prototype/audio_engine.py`:

```python
import threading

import soundfile as sf
import sounddevice as sd
import numpy as np

from granular_processor import GranularProcessor
from layers import LayerRegistry
from modulation import combine_layers, soft_clip
from ring_buffer import RingBuffer
from spectral_processor import SpectralProcessor, analyze_loop
from tape_modulator import TapeModulator

VISUALIZER_BUFFER_SECONDS = 2.0


class AudioEngine:
    MODES = ("tape", "spectral", "granular")

    def __init__(self, samplerate=44100, blocksize=1024, seed=None):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.registry = LayerRegistry()
        self.modulator = TapeModulator(samplerate=samplerate, seed=seed)
        self.spectral = SpectralProcessor(samplerate, seed=seed)
        self.granular = GranularProcessor(samplerate, seed=seed)
        buf_len = int(samplerate * VISUALIZER_BUFFER_SECONDS)
        self.visual_buffer = RingBuffer(buf_len)
        # Tape-mode control signals (warble pitch deviation, bloom gain-1):
        self.warble_buffer = RingBuffer(buf_len)
        self.bloom_buffer = RingBuffer(buf_len)
        # Spectral/granular wet-only signal (added texture, no dry loop):
        self.wet_buffer = RingBuffer(buf_len)
        self.loop_array = None
        self._stream = None
        self._mode = "tape"
        self._mode_lock = threading.Lock()
        self._dry_pos = 0

    @property
    def mode(self):
        with self._mode_lock:
            return self._mode

    def set_mode(self, mode):
        if mode not in self.MODES:
            raise ValueError(f"Unknown mode {mode!r}; expected one of {self.MODES}")
        with self._mode_lock:
            self._mode = mode

    def load_loop(self, path):
        data, file_rate = sf.read(path, dtype="float32", always_2d=True)
        if file_rate != self.samplerate:
            raise ValueError(
                f"Loop file sample rate {file_rate} does not match engine "
                f"sample rate {self.samplerate}"
            )
        self.loop_array = data.mean(axis=1).astype("float32")
        self._dry_pos = 0
        try:
            self.spectral.set_analysis(analyze_loop(self.loop_array, self.samplerate))
        except Exception:
            # Spectral mode degrades to dry playback rather than crashing.
            self.spectral.set_analysis(None)

    def _next_dry(self, frames):
        idx = (self._dry_pos + np.arange(frames)) % len(self.loop_array)
        self._dry_pos = int((self._dry_pos + frames) % len(self.loop_array))
        return self.loop_array[idx]

    def generate_block(self, frames):
        if self.loop_array is None:
            raise RuntimeError("No loop loaded; call load_loop() first")
        layers = self.registry.snapshot()
        mode = self.mode
        zeros = np.zeros(frames, dtype=np.float32)

        if mode == "tape":
            combined = combine_layers(layers)
            block = self.modulator.process(
                self.loop_array,
                frames,
                combined["warble_depth"],
                combined["bloom_depth"],
                combined["rate_hz"],
            )
            self.warble_buffer.write(self.modulator.last_warble_signal)
            self.bloom_buffer.write(self.modulator.last_gain - 1.0)
            self.wet_buffer.write(zeros)
        else:
            dry = self._next_dry(frames)
            processor = self.spectral if mode == "spectral" else self.granular
            wet = processor.process(self.loop_array, frames, layers)
            block = soft_clip(dry + wet).astype(np.float32)
            self.warble_buffer.write(zeros)
            self.bloom_buffer.write(zeros)
            self.wet_buffer.write(wet)

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

- [ ] **Step 4: Run the full suite**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest -q`
Expected: all pass (existing tape tests unchanged: tape path is identical)

- [ ] **Step 5: Commit**

```bash
git add audio_prototype/audio_engine.py audio_prototype/tests/test_audio_engine.py
git commit -m "feat: add engine mode dispatch (tape/spectral/granular) and wet buffer"
```

---

### Task 6: GUI mode selector and wet-signal trace

**Files:**
- Modify: `audio_prototype/gui.py`

**Interfaces:**
- Consumes: `engine.set_mode`, `engine.MODES`, `engine.wet_buffer` from Task 5.
- Produces: mode dropdown in the Scan Input panel; a third faint plot trace showing the wet-only signal.

No automated test (GUI); verified by compile check + manual pass in Task 7.

- [ ] **Step 1: Add the mode dropdown**

In `gui.py` `__init__`, after `self.bpm_var = ...` add:

```python
        self.mode_var = tk.StringVar(value="tape")
```

In `_build_controls`, after the "Load Loop..." button grid call, insert (and shift later rows' `row=` indices down by one — Pick Color to row 2, Hue 3, Sat 4, Val 5, BPM 6, swatch `row=2`, Send `row=7`):

```python
        ttk.Label(frame, text="Mode").grid(row=1, column=0, sticky="w")
        mode_box = ttk.Combobox(
            frame, textvariable=self.mode_var, state="readonly",
            values=list(self.engine.MODES), width=10,
        )
        mode_box.grid(row=1, column=1, sticky="w", pady=(0, 4))
        mode_box.bind("<<ComboboxSelected>>",
                      lambda _e: self.engine.set_mode(self.mode_var.get()))
```

- [ ] **Step 2: Add the wet trace to the waveform panel**

In `_build_waveform`, after the bloom line, add:

```python
        (self.wet_line,) = self.ax.plot(
            zeros, color="tab:purple", alpha=0.35, linewidth=1.0,
            label="added texture (wet)",
        )
```

In `_refresh_waveform`, add:

```python
        wet = self.engine.wet_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        self.wet_line.set_ydata(wet)
```

- [ ] **Step 3: Compile check**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m py_compile gui.py`
Expected: exit 0

- [ ] **Step 4: Commit**

```bash
git add audio_prototype/gui.py
git commit -m "feat: add engine mode dropdown and wet-signal trace to GUI"
```

---

### Task 7: Full suite + manual verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full automated suite**

Run: `cd audio_prototype && .venv/Scripts/python.exe -m pytest -q`
Expected: all pass

- [ ] **Step 2: Smoke-test launch**

Launch `main.py` in the background, confirm the process survives 5 seconds with an empty error log, then kill that exact PID only.

- [ ] **Step 3: Manual end-to-end checklist (user)**

1. Default mode is Tape and behaves as before.
2. Switch to Spectral with 0 layers — sound is unchanged (dry loop).
3. Send a layer in Spectral mode — a distinctly pitched, shimmering resynthesized ghost of the loop appears; different hues give clearly different pitches; slower BPM smears, faster BPM tracks.
4. Send several layers with different colors — each voice is individually audible; purple wet trace shows the added texture.
5. Switch to Granular — grains burst in heartbeat pulses at each layer's BPM; hue audibly transposes grains.
6. Switch modes back and forth — layers persist, no clicks/crashes.
7. Many layers — thickens without harsh clipping.

- [ ] **Step 4: Commit any tuning changes from the manual pass**

## Self-Review Notes

- **Spec coverage:** mode selector (Tasks 5, 6), offline analysis + fallback-to-dry (Tasks 2, 5), per-layer spectral voices with hue/BPM/sat/val mapping (Task 3), heartbeat-clustered grains (Task 4), 0-layer exact passthrough (Task 5 tests), sqrt-layer-count normalization + soft clip (Tasks 3, 4, 5), wet-only visualization buffer (Tasks 5, 6), layers persist across mode switches (shared registry, Task 5).
- **Placeholder scan:** none; all steps carry complete code.
- **Type consistency:** layer dicts everywhere are `{id, hue, sat, val, bpm}` (Task 1); both processors expose `process(loop_array, frames, layers)`; `set_analysis` only on spectral.
