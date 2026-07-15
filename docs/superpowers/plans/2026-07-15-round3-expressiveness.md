# Round 3: Expressiveness & Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finger-red gradient picker with full-range gamut mapping, live-output spectral analysis, Schroeder reverb on the wet bus, mixed per-layer engine routing, pause/play, and stronger spectral presence.

**Architecture:** `modulation.hue_to_bipolar` becomes the single hue→modulation mapping used by all engines. `reverb.py` adds a chunk-vectorized Schroeder reverb owned by the engine and applied to the additive wet bus. `SpectralProcessor.process` accepts an optional `live_frame` (partials analyzed from the engine's rolling output window). Layers carry an `engine` field; a new `mixed` mode routes per-layer. GUI swaps sliders for a gradient canvas and adds mode/engine/live/reverb/pause controls.

**Tech Stack:** unchanged (numpy, soundfile, sounddevice, matplotlib, Tkinter, pytest).

## Global Constraints

- `FINGER_GAMUT_HALF_WIDTH = 0.06` (hue distance from red mapped to bipolar ±1, clamped beyond).
- Spectral pitch span ±7 st, granular ±12 st, both via `hue_to_bipolar`.
- `SpectralProcessor.VOICE_LEVEL = 0.6`; `LIVE_FEEDBACK_GAIN = 0.85`.
- Dry ducking in additive modes: `duck = max(0.5, 1.0 / (1.0 + 0.12 * n_wet_layers))`.
- Reverb: comb delays (44.1k samples) 1310, 1636, 1813, 1927 with feedback 0.84; allpasses 556, 225 with g 0.7; wet output averaged over combs. Default `reverb_mix = 0.35`.
- 0 layers must remain bit-exact dry in every mode.
- All work in `audio_prototype/`; run tests with `.venv/Scripts/python.exe -m pytest`.

---

### Task 1: `hue_to_bipolar` gamut mapping

**Files:** Modify `audio_prototype/modulation.py`; Test `audio_prototype/tests/test_modulation.py`

**Interfaces:** Produces `hue_to_bipolar(hue) -> float` in [-1, 1] (0 at red, +1 at hue=+0.06, -1 at hue=0.94, clamped outside); `hue_to_warble_depth` now maps |bipolar| across PER_LAYER_MIN/MAX_WARBLE.

Steps: add tests (`hue_to_bipolar(0)==0`, `(0.06)==1`, `(0.03)==0.5`, `(0.94)==-1`, `(0.97)==-0.5`, `(0.5)` clamps to 1, `(0.9)` clamps to -1; warble depth: hue 0 → MIN, hue 0.06 → MAX, hue 0.94 → MAX); run to fail; implement:

```python
FINGER_GAMUT_HALF_WIDTH = 0.06

def hue_to_bipolar(hue):
    d = ((hue + 0.5) % 1.0) - 0.5  # signed distance from red, [-0.5, 0.5)
    return clamp(d / FINGER_GAMUT_HALF_WIDTH, -1.0, 1.0)

def hue_to_warble_depth(hue_norm):
    strength = abs(hue_to_bipolar(hue_norm))
    return PER_LAYER_MIN_WARBLE + strength * (PER_LAYER_MAX_WARBLE - PER_LAYER_MIN_WARBLE)
```

Run suite; fix `test_combine_layers_*` fixtures (they use `hue=1.0` which now maps to bipolar 0 → MIN depth; change fixture hues to `0.06` so summed max depth expectations hold). Commit `feat: map hue through finger-gamut bipolar scale`.

---

### Task 2: Schroeder reverb

**Files:** Create `audio_prototype/reverb.py`; Test `audio_prototype/tests/test_reverb.py`

**Interfaces:** `SchroederReverb(samplerate=44100)` with `process(x: np.ndarray) -> np.ndarray` (float32, same length, 100% wet, state persists).

Tests: silence from clean state → silence; impulse block then silent blocks → tail energy present for >0.5 s then decaying; length correctness for frames 300 (smaller than shortest delay) and 5000 (larger); dtype float32. Implement combs/allpasses with chunk-vectorized feedback (chunk = delay length, exact recursion since feedback only reaches ≥ delay samples back):

```python
class _Comb:
    def __init__(self, delay, feedback):
        self.delay, self.feedback = delay, feedback
        self.buf = np.zeros(delay)  # last `delay` output samples, oldest first
    def process(self, x):
        n, out, i = len(x), np.empty(len(x)), 0
        while i < n:
            m = min(self.delay, n - i)
            y = x[i:i + m] + self.feedback * self.buf[:m]
            out[i:i + m] = y
            self.buf = np.concatenate([self.buf[m:], y])
            i += m
        return out

class _Allpass:  # y[n] = -g*x[n] + x[n-D] + g*y[n-D]
    ...same chunking with xbuf/ybuf...

class SchroederReverb:
    def __init__(self, samplerate=44100):
        self._combs = [_Comb(d, 0.84) for d in (1310, 1636, 1813, 1927)]
        self._allpasses = [_Allpass(556, 0.7), _Allpass(225, 0.7)]
    def process(self, x):
        y = sum(c.process(x) for c in self._combs) / 4.0
        for ap in self._allpasses:
            y = ap.process(y)
        return y.astype(np.float32)
```

Commit `feat: add Schroeder reverb for the wet bus`.

---

### Task 3: Spectral — bipolar pitch, louder voices, live-frame support

**Files:** Modify `audio_prototype/spectral_processor.py`; Test `audio_prototype/tests/test_spectral_processor.py`

**Interfaces:** `analyze_frame(window, samplerate, n_partials=N_PARTIALS) -> (freqs, amps)` single-frame partials (amps normalized to that frame's max, silent window → zeros); `SpectralProcessor.process(loop_array, frames, layers, live_frame=None)`; `VOICE_LEVEL = 0.6`; `LIVE_FEEDBACK_GAIN = 0.85` applied to live-frame amps.

Tests: update `test_hue_shifts_pitch_up` (hue 0.03 → +3.5 st); add `analyze_frame` finds 440 Hz tone; silent window → zero amps, no NaN; `process` with `live_frame=(f, a)` containing a 660 Hz partial produces output whose dominant freq approaches 660 (run ~20 blocks, bpm high for fast tracking). Implementation: pitch `semitones = 7.0 * hue_to_bipolar(hue)` (import from modulation); when `live_frame` is not None, per-voice target = live frame, tracking alpha from bpm: `alpha = clamp(0.97 - 0.5 * (bpm / 300.0), 0.3, 0.97)` combined with sat blur `alpha = clamp(alpha + 0.02 + 0.2*sat, 0.0, 0.985)`; amps target scaled by `LIVE_FEEDBACK_GAIN`; scan position unused in live mode. Commit `feat: spectral live-frame tracking, bipolar pitch, louder voices`.

---

### Task 4: Granular bipolar pitch

**Files:** Modify `audio_prototype/granular_processor.py`; Test `audio_prototype/tests/test_granular_processor.py`

`semitones = 12.0 * hue_to_bipolar(hue)`. Add test: two processors, same seed, layers differing only in hue (0.0 vs 0.06) produce different output; hue 0.5 and 0.06 produce identical output (both clamp... 0.5 clamps to +1 == 0.06's +1). Commit `feat: granular pitch via finger-gamut bipolar mapping`.

---

### Task 5: Layer engine assignment

**Files:** Modify `audio_prototype/layers.py`; Test `audio_prototype/tests/test_layers.py`

`add(hue, sat, val, bpm, engine="tape")` stores `engine` in the dict; snapshot test updated to expect it; invalid engine raises ValueError (`engine not in ("tape", "spectral", "granular")`). Commit `feat: per-layer engine assignment`.

---

### Task 6: Engine — mixed mode, ducking, reverb, live analysis, pause

**Files:** Modify `audio_prototype/audio_engine.py`; Test `audio_prototype/tests/test_audio_engine.py`

**Interfaces:** `MODES = ("tape", "spectral", "granular", "mixed")`; `live_analysis: bool` attribute; `reverb_mix: float` (default 0.35); `reverb: SchroederReverb`; `paused` property, `pause()`, `resume()` (guard when no stream); rolling `_analysis_window` (FFT_SIZE) of output fed each block.

Block flow for additive modes (`spectral`, `granular`, `mixed`):
1. Split layers: single modes → all layers to that engine; mixed → by `layer["engine"]`.
2. Base: mixed → tape modulator with combined tape-layer params (zero-depth passthrough when none); spectral/granular modes → `_next_dry`.
3. `live_frame = analyze_frame(self._analysis_window, sr)` if `live_analysis` and spectral layers active, else None.
4. `wet_raw = spectral.process(loop, frames, spec_layers, live_frame) + granular.process(loop, frames, gran_layers)` (skip a processor when its layer list is empty and write no stale voices — call with empty list to clear).
5. `duck = max(0.5, 1/(1 + 0.12 * n_wet_layers))`; `wet = wet_raw + reverb_mix * reverb.process(wet_raw)`; `block = soft_clip(duck * base + wet)`.
6. Update `_analysis_window` with block; write wet/visual buffers (tape-mode branch unchanged).

Tests: mixed mode with one granular layer produces wet ≠ 0 and base intact; mixed with only tape layer equals tape-mode output for same seed; ducking (2 spectral layers → dry portion scaled, verify block != dry and 0-layer still exact); `pause()/resume()` flip `paused` without a stream; reverb tail: block after wet activity with layers removed still nonzero wet buffer briefly. Keep all existing tests passing (0-layer dry-exact: duck=1, reverb(0)=0 from clean state). Commit `feat: mixed routing, wet-bus reverb, live analysis, pause state`.

---

### Task 7: GUI — gradient picker and new controls

**Files:** Modify `audio_prototype/gui.py`

- Replace Hue/Sat/Val sliders + Pick Color with a gradient canvas (220×120 `tk.PhotoImage`, built once): x → hue `(-0.06 + 0.12 * x/(w-1)) % 1.0`; y → `val = 1.0 - 0.72 * y/(h-1)` (top bright), `sat = 0.55 + 0.4 * y/(h-1)` (darker = more saturated). Click/drag moves a marker (canvas oval) and sets `hue_var/sat_var/val_var`; swatch preview retained.
- Mode dropdown values now include `mixed`; "Engine" dropdown (tape/spectral/granular, default spectral) next to Send → passed to `registry.add(engine=...)`; layer rows show `Layer N (BPM x, engine)`.
- "Live analysis" Checkbutton → `engine.live_analysis`.
- "Reverb" scale 0–1 → `engine.reverb_mix`.
- Pause/Play toggle button: calls `engine.pause()`/`engine.resume()`, flips its own text.
- Compile check `py_compile`, smoke launch. Commit `feat: gradient finger-color picker and playback/routing controls`.

---

### Task 8: Verification

Full suite; benchmark all four modes (8 layers, mixed split across engines + reverb + live analysis) under the 23 ms block budget; smoke launch; manual checklist: picker drag updates swatch; realistic reds now audibly shift spectral pitch both directions; live analysis blooms without runaway; granular tails smooth with reverb up; mixed mode plays all three engines at once with per-send routing; pause/play works; 0 layers dry in all modes.

## Self-Review Notes

- Spec coverage: picker+gamut (T1, T7), live analysis (T3, T6, T7), reverb (T2, T6, T7), mixed routing (T5, T6, T7), pause (T6, T7), spectral presence (T3 level, T6 ducking).
- Types: layer dicts `{id, hue, sat, val, bpm, engine}` everywhere; `process(loop, frames, layers, live_frame=None)` only on spectral; reverb 100% wet, engine owns the mix.
- Ducking floor 0.5 and duck=1.0 at n=0 keeps dry-exact tests green.
