# Local Sample Soundbath Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current generative-first synth MVP with local sample-backed source playback and direct soundbath effect rows.

**Architecture:** Browser UI decodes user-selected local samples and sends mono buffers to the Pyodide worker. `SynthVoiceBank` stores those samples and uses them for source voices when available, falling back to generated tones only when no bank has been loaded. `SynthBathProcessor` maps synth rows to Stretch/Delay/Reverb/Stereo/Shape roles without pitch shifting.

**Tech Stack:** Vanilla JS, AudioWorklet, Pyodide, Python, NumPy, pytest.

---

### Task 1: Add failing sample-bank source tests

**Files:**
- Modify: `audio_prototype/tests/test_synth_source.py`
- Modify: `audio_prototype/tests/test_web_engine_synth.py`

- [ ] Add tests that call `load_sample()` on `SynthVoiceBank`/`WebEngine`, confirm loaded samples are used, and confirm different output slots select different cached sample buffers.
- [ ] Run targeted tests and confirm they fail because `load_sample` does not exist.

### Task 2: Implement cached local sample playback

**Files:**
- Modify: `audio_prototype/synth_source.py`
- Modify: `audio_prototype/web_engine.py`
- Modify: `webapp/worker.js`

- [ ] Add `SynthVoiceBank.load_sample(name, samples)`.
- [ ] Add `WebEngine.load_synth_sample(name, samples)`.
- [ ] Add worker handling for `load_synth_sample`.
- [ ] Keep generated tones as fallback when the sample bank is empty.

### Task 3: Add browser local sample controls

**Files:**
- Modify: `webapp/index.html`
- Modify: `webapp/main.js`
- Modify: `webapp/style.css`
- Modify: `audio_prototype/tests/test_webapp_static.py`

- [ ] Add a synth-visible `Load Samples...` button and multi-file audio input.
- [ ] Decode selected files to mono and send them to the worker.
- [ ] Keep local sample directories ignored by git.

### Task 4: Rename and separate synth effect rows

**Files:**
- Modify: `audio_prototype/synth_bath_processor.py`
- Modify: `audio_prototype/tests/test_synth_bath_processor.py`
- Modify: `webapp/main.js`
- Modify: `audio_prototype/tests/test_webapp_static.py`

- [ ] Change synth row labels to Stretch/Delay/Reverb/Stereo/Shape.
- [ ] Map rows to distinct effect roles with unison reads.
- [ ] Verify dense output remains bounded.

### Task 5: Verify

**Files:**
- Test: `audio_prototype/tests/`

- [ ] Run targeted source, bath, engine, and web static tests.
- [ ] Run `python -m pytest audio_prototype/tests/ --ignore=audio_prototype/tests/test_gui.py -v`.
