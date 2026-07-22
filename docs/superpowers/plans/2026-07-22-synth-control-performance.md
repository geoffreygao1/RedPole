# Synth Control and Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add clearer Synth controls, stronger scan-to-sound mapping, tone/harmony audition modes, and dense-voice performance budgeting.

**Architecture:** Keep existing WebEngine/SynthVoiceBank boundaries. `synth_source.py` owns voice parameter mapping and tone rendering; `web_engine.py` owns synth options and wet voice budgeting; `webapp/*` owns controls and Worker messages.

**Tech Stack:** Python 3.11 + NumPy + pytest; vanilla JavaScript/CSS/HTML; Pyodide Worker.

---

### Task 1: Source Mapping and Harmony Tests

**Files:**
- Modify: `audio_prototype/tests/test_synth_source.py`

- [ ] Write tests for `voice_params_from_scan`, fixed harmony modes, and tone-family spectral variation.
- [ ] Run `python -m pytest tests/test_synth_source.py -v`; expect failures for missing mapping/options.

### Task 2: Implement Source Mapping

**Files:**
- Modify: `audio_prototype/synth_source.py`

- [ ] Add tone/harmony constants and `voice_params_from_scan`.
- [ ] Update `drone_pitch_hz` and `SynthVoiceBank` to use tone and harmony options.
- [ ] Render BPM-dependent loop length, event spacing, attack/release, and tone-family filtering.
- [ ] Run `python -m pytest tests/test_synth_source.py -v`; expect pass.

### Task 3: Engine Options and Wet Budget

**Files:**
- Modify: `audio_prototype/tests/test_web_engine_synth.py`
- Modify: `audio_prototype/web_engine.py`

- [ ] Add tests for `set_synth_options` and heavy wet subset budgeting.
- [ ] Implement `WebEngine.set_synth_options` and a rotating wet-layer budget.
- [ ] Run `python -m pytest tests/test_web_engine_synth.py tests/test_web_engine.py -v`; expect pass.

### Task 4: Web Controls

**Files:**
- Modify: `audio_prototype/tests/test_webapp_static.py`
- Modify: `webapp/index.html`
- Modify: `webapp/main.js`
- Modify: `webapp/worker.js`
- Modify: `webapp/style.css`

- [ ] Add static tests for the pill switch, Tone/Harmony selects, and Worker `set_synth_options`.
- [ ] Implement the UI controls and messages.
- [ ] Run `python -m pytest tests/test_webapp_static.py -v`; expect pass.

### Task 5: Verification

**Files:**
- Modify: `AGENTS.md`

- [ ] Update handoff notes.
- [ ] Run `python -m pytest tests/test_synth_source.py tests/test_web_engine_synth.py tests/test_web_engine.py tests/test_webapp_static.py -v`.
- [ ] Run `python -m pytest tests/ --ignore=tests/test_gui.py -v`.
