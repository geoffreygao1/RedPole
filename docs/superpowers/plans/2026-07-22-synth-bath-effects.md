# Synth Bath Effects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace loop-oriented granular/microloop synth-mode effects with synth-specific ambient sound-bath effects.

**Architecture:** Keep the patch bay and existing engine strings stable for UI compatibility. Add a focused `SynthBathProcessor` used only by `WebEngine._generate_synth_block()`, mapping rows to Bloom, Halo, Tide, Resonance, and Space-style processing with unison-only source reads.

**Tech Stack:** Python, NumPy, existing pytest suite, browser WebEngine/Pyodide bridge.

---

### Task 1: Processor Tests

**Files:**
- Create: `audio_prototype/synth_bath_processor.py`
- Test: `audio_prototype/tests/test_synth_bath_processor.py`

- [ ] Write tests for audible bounded output, distinct row roles, unison-only reads, and dense-layer stability.
- [ ] Run `python -m pytest audio_prototype/tests/test_synth_bath_processor.py -v` and verify failures before implementation.

### Task 2: Processor Implementation

**Files:**
- Create: `audio_prototype/synth_bath_processor.py`

- [ ] Implement `SynthBathProcessor.process(frames, layers, source_arrays, source_positions)`.
- [ ] Map `microloop`, `granules`, `glitch`, `multidelay`, and `tape` to ambient roles without pitch shifting.
- [ ] Run `python -m pytest audio_prototype/tests/test_synth_bath_processor.py -v`.

### Task 3: WebEngine Integration

**Files:**
- Modify: `audio_prototype/web_engine.py`
- Test: `audio_prototype/tests/test_web_engine_synth.py`

- [ ] Add WebEngine tests proving synth mode uses `SynthBathProcessor` and does not call `MicrocosmProcessor` for synth wet layers.
- [ ] Replace synth-mode microcosm/tape wet generation with `SynthBathProcessor`.
- [ ] Run `python -m pytest audio_prototype/tests/test_web_engine_synth.py -v`.

### Task 4: Handoff and Regression

**Files:**
- Modify: `AGENTS.md`

- [ ] Update the living brief to mention synth-specific bath effects.
- [ ] Run `python -m pytest audio_prototype/tests/ --ignore=audio_prototype/tests/test_gui.py -v`.
