# Generative 25 Slot Synth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove copyrighted sample-pack dependency and make synth mode fully generative with 25 distinct patch-slot voice characters.

**Architecture:** Browser synth mode must not fetch or send sample assets. `SynthVoiceBank` renders generated voices only, with sound identity derived from the 5x5 patch slot and scan color/BPM shaping timbre, motion, and phrase timing. Legacy synth option methods remain compatibility no-ops so old worker/API paths do not matter.

**Tech Stack:** Python/numpy DSP, vanilla JS Worker/main thread, pytest.

---

### Task 1: Tests

- [x] Update synth tests to assert no `family` field in scan params.
- [x] Add `voice_character_for_slot()` tests for 25 distinct generated recipes.
- [x] Replace sample-backed synth tests with generated soft-start/headroom tests.
- [x] Update web static tests to reject sample manifest, `assets/samples/`, and `load_synth_sample`.

### Task 2: Implementation

- [x] Remove web sample manifest and main-thread decode/send path.
- [x] Remove worker pending sample queue and sample message handler.
- [x] Remove Python `WebEngine.load_synth_sample`.
- [x] Add `.gitignore` entry for `webapp/assets/samples/`.
- [x] Make `SynthVoiceBank` generate voices from slot-specific recipes only.

### Task 3: Verification

- [x] Run focused synth/web static tests.
- [x] Run full non-GUI test suite.
- [x] Update `AGENTS.md` handoff.
