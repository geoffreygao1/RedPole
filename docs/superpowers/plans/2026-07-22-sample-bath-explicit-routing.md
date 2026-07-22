# Sample Bath Explicit Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make synth sample playback behave like a same-tone sound bath and make patch output assignment explicit via drag from the Sources list.

**Architecture:** Keep backend synth options compatible but remove Tone/Harmony from the visible web UI. Render sample-backed synth voices at the original C pitch with tiny detune, random body offsets, soft fades, and existing wet-effect budgeting. In the browser, scans create source records only; the user routes them by dragging from the Sources panel onto output slots.

**Tech Stack:** Python/numpy audio engine tests, vanilla JS DOM/canvas UI, pytest static tests.

---

### Task 1: Regression Tests

**Files:**
- Modify: `audio_prototype/tests/test_synth_source.py`
- Modify: `audio_prototype/tests/test_web_engine_synth.py`
- Modify: `audio_prototype/tests/test_webapp_static.py`

- [ ] Write tests asserting harmony modes do not repitch synth sample bath voices, loaded samples expose a near-1.0 playback ratio, sample voices have a random body offset and soft start, Tone/Harmony controls are absent from `index.html`, and `main.js` supports source-list dragging without automatic output slot assignment.
- [ ] Run targeted tests and verify they fail for missing behavior.

### Task 2: Same-Tone Sample Bath

**Files:**
- Modify: `audio_prototype/synth_source.py`

- [ ] Make `drone_pitch_hz(..., harmony_mode=...)` ignore harmony mode for pitch selection.
- [ ] Render loaded samples with `sample_playback_ratio = 2 ** (detune_cents / 1200)` instead of `pitch_hz / DRONE_ROOT_HZ`.
- [ ] Choose a non-zero random `sample_start` in the sample body, loop from that offset, and store `sample_start` plus `sample_playback_ratio` in voice timbre.
- [ ] Store `buffer_for_effects` on each voice and apply a slow sample fade-in so starts feel like swells, not triggered playback.

### Task 3: Explicit Source Routing UI

**Files:**
- Modify: `webapp/index.html`
- Modify: `webapp/main.js`
- Modify: `webapp/style.css`

- [ ] Move the `Sources` section before `Patch Bay`.
- [ ] Remove visible Tone/Harmony controls.
- [ ] When a scan is confirmed, create an unassigned source list item with `slot`, `row`, and `col` set to `null`.
- [ ] Add pointer/mouse drag from source list items and existing output jacks onto output slots.
- [ ] On drop over an output slot, connect that source to the slot's engine/row/col and replace any previous source occupying the slot.
- [ ] Do not send `connect_source` when the scan is added.

### Task 4: Verification and Handoff

**Files:**
- Modify: `AGENTS.md`

- [ ] Run targeted audio/static tests.
- [ ] Run `python -m pytest tests/ --ignore=tests/test_gui.py -v`.
- [ ] Update the living handoff note with the new sample-bath and explicit-routing state.
