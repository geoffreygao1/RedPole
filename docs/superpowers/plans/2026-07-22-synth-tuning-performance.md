# Synth Tuning and Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retune synth mode so many voices form a calm, varied ambient wash instead of a bright constant chord stack.

**Architecture:** Keep the existing synth-mode architecture, but change the source palette and gain behavior locally. `synth_source.py` owns pitch/timbre/breathing; `web_engine.py` owns dry-density trim; tests lock the intended behavior.

**Tech Stack:** Python 3.11, NumPy, pytest, shared browser/desktop DSP modules.

---

### Task 1: Pitch Palette and Voice Motion Tests

**Files:**
- Modify: `audio_prototype/tests/test_synth_source.py`

- [ ] **Step 1: Write failing pitch and motion tests**

Add tests asserting the first eight synth pitches are restrained, non-monotonic,
and include similar as well as harmonic relationships. Add a rendered-voice
test that compares RMS windows and requires slow amplitude motion.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_synth_source.py -v` from `audio_prototype/`.
Expected: failures against the current upward overtone ladder and constant
rendered voice.

### Task 2: Retune Synth Source

**Files:**
- Modify: `audio_prototype/synth_source.py`

- [ ] **Step 1: Replace the drone ladder with a balanced palette**

Use a fixed ratio palette with near-unisons, harmonic anchors, and neighboring
tones. Keep pitches in register by folding into a low/mid range instead of
raising every table wrap by an octave.

- [ ] **Step 2: Soften rendered voices**

Reduce seed brightness and apply brightness-controlled one-pole low-pass plus
slow amplitude breathing during `_render`.

- [ ] **Step 3: Run source tests**

Run: `python -m pytest tests/test_synth_source.py -v`.
Expected: pass.

### Task 3: Dense Dry Mix Guardrail

**Files:**
- Modify: `audio_prototype/tests/test_web_engine_synth.py`
- Modify: `audio_prototype/web_engine.py`

- [ ] **Step 1: Write failing dense dry mix test**

Add a test that compares one dry synth voice with 20 dry synth voices and
requires the dense dry bed to be normalized enough to avoid dominating.

- [ ] **Step 2: Implement density dry trim**

In `_generate_synth_block`, reduce dry gain as active layer count rises before
the final dry/wet mix.

- [ ] **Step 3: Run synth engine tests**

Run: `python -m pytest tests/test_web_engine_synth.py -v`.
Expected: pass.

### Task 4: Verification

**Files:**
- No additional source files.

- [ ] **Step 1: Run focused DSP tests**

Run: `python -m pytest tests/test_synth_source.py tests/test_web_engine_synth.py tests/test_web_engine.py -v`.
Expected: pass.

- [ ] **Step 2: Run full suite**

Run: `python -m pytest tests/ -v`.
Expected: pass.
