# Synth Tab for the Desktop App (Phase 2, interactive) — Design

**Date:** 2026-07-23
**Status:** Approved design, ready for implementation plan.

## Goal

Add an interactive **Synth** tab to the desktop Tkinter app (`audio_prototype/main.py`)
that drives the Phase 1 `SoundscapeEngine` (`soundscape_engine.py`) live: the user
builds patches by choosing a source preset and an optional transform preset from two
5×5 grids, sets a finger-scan color and BPM, and hears the evolving soundscape through
`sounddevice`. This is the interactive front-end the Phase 1 plan called out as future
work ("wire `SoundscapeEngine` into a real 5×5 output-matrix / 5×5 input-matrix UI").

This is deliberately a **first interactive pass** meant for tuning by ear, not the full
spec Phase 2 (no hardware input, no collective-tempo composition engine, no reference-track
tuning — those remain later phases in `2026-07-22-evolving-soundscape-design.md`).

## Scope

**In scope:**
- A `ttk.Notebook` with two tabs: **Loop** (today's existing UI, behavior unchanged) and **Synth** (new).
- A new `SynthAudioEngine` wrapping `SoundscapeEngine` with its own `sounddevice` stream lifecycle.
- Synth tab UI: two 5×5 preset grids (sources, transforms), color picker + BPM, root-note control, Connect button, active-patch list with Remove, Load Sample button, waveform view.
- Only one audio stream open at a time, switched by the active tab.
- Tests mirroring the existing pure-logic + monkeypatched-stream split.

**Out of scope (explicitly):**
- Modifying the Phase 1 `soundscape_*.py` engine internals (additive-only, same as Phase 1).
- Hardware/serial input, TouchDesigner, browser/Pyodide port.
- Live root-note modulation without dropping patches (Phase 4 in the source spec).
- Any change to the Loop tab's audio behavior or the `LayerRegistry`/`AudioEngine` audio path.

## Architecture

Two independent vertical slices (engine + UI each), kept separate for the same reason
Phase 1 kept `SoundscapeEngine` out of `LayerRegistry`: the two engines have
incompatible shapes (Loop needs a loaded loop + `LayerRegistry` + reverb/wet-bus; Synth
needs none of that — `SoundscapeEngine.generate_block()` does its own mixing/limiting).

```
main.py
 ├── AudioEngine (Loop)         existing, unchanged
 ├── SynthAudioEngine (Synth)   new, wraps SoundscapeEngine
 └── RedPoleGUI(root, audio_engine, synth_engine, default_loop_path)
        └── ttk.Notebook
             ├── Loop tab   → existing layout (Scan Input / Audition / Scan Sources / Waveform / Patch Bay)
             └── Synth tab  → new layout (built by synth_tab.py)
```

**Files:**

| File | Change | Purpose |
|------|--------|---------|
| `audio_prototype/audio_io.py` | **create** | Shared `read_mono_audio` + `resample_linear` (moved out of `audio_engine.py`). |
| `audio_prototype/audio_engine.py` | **modify** (minimal) | Import `read_mono_audio`/`resample_linear` from `audio_io` and re-export them (keep `audio_engine.read_mono_audio` importable so existing tests/importers are untouched). No audio-path behavior change. |
| `audio_prototype/synth_audio_engine.py` | **create** | `SynthAudioEngine` — stream lifecycle + `SoundscapeEngine` + visual buffer + thread guard. |
| `audio_prototype/synth_tab.py` | **create** | Pure helpers + `SynthTab` widget builder for the Synth tab. |
| `audio_prototype/gui.py` | **modify** | Wrap existing layout in a Notebook Loop tab; add Synth tab via `synth_tab.SynthTab`; tab-change stream handoff. |
| `audio_prototype/main.py` | **modify** | Build both engines; pass both to `RedPoleGUI`; stop both on exit. |
| `audio_prototype/tests/test_synth_audio_engine.py` | **create** | Engine behavior + monkeypatched stream lifecycle. |
| `audio_prototype/tests/test_synth_tab.py` | **create** | Pure grid-geometry / selection-state helpers. |
| `audio_prototype/tests/test_audio_io.py` | **create** | Cover the lifted `read_mono_audio`/`resample_linear` helpers. |

## Components

### `SynthAudioEngine` (`synth_audio_engine.py`)

```
SynthAudioEngine(samplerate=44100, blocksize=1024, seed=None, root_midi=62)

  # patch control (thread-safe against the audio callback via an internal lock)
  .connect_patch(hue, sat, val, bpm, source_preset, transform_preset=None) -> int   # patch id
  .disconnect_patch(patch_id) -> None
  .active_patches() -> list[dict]      # snapshot: id, hue, sat, val, bpm, source_preset, transform_preset

  # sample + tuning
  .load_sample(path) -> None           # read_mono_audio + resample_linear -> SourceBank.texture.load_sample()
  .set_root_midi(root_midi) -> None    # rebuilds SoundscapeEngine fresh; DROPS all patches (documented)
  .root_midi -> int

  # stream lifecycle (mirrors AudioEngine)
  .start() / .stop() / .pause() / .resume()
  .paused -> bool

  # audio generation
  .generate_block(frames) -> np.ndarray    # float32 mono; delegates to SoundscapeEngine under the lock
  .generate_stereo_block(frames) -> np.ndarray  # duplicates mono to L/R
  .visual_buffer                            # RingBuffer(samplerate * VISUALIZER_BUFFER_SECONDS)
```

- Owns `self.engine = SoundscapeEngine(samplerate, seed, root_midi)`.
- An internal `threading.Lock` guards `connect_patch`/`disconnect_patch`/`set_root_midi`
  against `generate_block` — `SoundscapeEngine` mutates plain dicts/lists with no locking
  of its own, so concurrent connect during the callback's `list(self._patches.values())`
  could otherwise raise "dictionary changed size during iteration."
- Tracks its own `_paused` flag and `_stream` exactly like `AudioEngine`; `start()` opens
  the `sd.OutputStream` and only starts it if not paused.
- `_callback` writes the mono mix to `visual_buffer` and wraps `generate_block` so any
  per-block exception outputs a silent block rather than killing the stream.
- `set_root_midi` replaces `self.engine` with a fresh `SoundscapeEngine` at the new root
  (Phase 1's `HarmonicField`/`PitchAllocator` are fixed at construction). This clears all
  patches by design; the UI warns before doing it.

### Synth tab UI (`synth_tab.py`)

Pure module-level helpers (unit-testable without Tk, mirroring `gui.py`'s helper style):
- `SYNTH_SOURCE_ROWS = ("additive", "granular", "resonant", "noise", "texture")`
- `SYNTH_TRANSFORM_ROWS = ("delay", "spectral", "pitch", "grainfx", "spatial")`
- `source_preset_id(row, col) -> str` / `transform_preset_id(row, col) -> str` — map a grid
  cell to the preset id, derived from `SOURCE_PRESETS`/`TRANSFORM_PRESETS` (built by grouping
  those lists by `engine`, so the grids stay correct if presets are renamed/reordered).
- `ROOT_NOTE_CHOICES` — list of `(label, midi)` for the root-note Combobox (e.g. a couple of
  octaves of note names around the default 62 / D4).
- Selection-state is single-select per grid: helper returns the new selected cell / clears others.

`SynthTab` (a small class or builder function given a parent frame + `synth_engine` + shared
color helpers): builds two 5×5 grids (canvas or `ttk.Button` matrix), a reused color picker +
BPM entry (calling `gui`'s existing `_picker_coords_to_hsv` / random-scan helpers, not
duplicating them), a root-note `Combobox` + Apply, a **Connect** button (disabled until a
source cell is selected; transform optional), a scrollable active-patch list (swatch, BPM,
`source→transform` label, Remove), a **Load Sample...** button, and a waveform panel
(`Figure`/`FigureCanvasTkAgg`, same setup as Loop) fed from `synth_engine.visual_buffer`.

### `gui.py` changes

- `RedPoleGUI.__init__(root, engine, synth_engine, default_loop_path)` — new `synth_engine` param.
- Introduce a `ttk.Notebook`; move today's frame-building into a "Loop" tab frame (the existing
  `_build_*` methods parent into that frame instead of `self.root`). No change to Loop widgets/behavior.
- Add a "Synth" tab hosting `SynthTab`.
- `<<NotebookTabChanged>>` handler: pause the outgoing engine's stream, resume/start the incoming
  one, so exactly one `sd.OutputStream` is ever running. On Synth-stream open failure: `showerror`,
  revert selection to Loop, leave Loop running.
- The waveform refresh loop reads the active tab's engine's `visual_buffer`.

### `main.py` changes

- Construct `AudioEngine` (load default loop + `start()`, as today) and `SynthAudioEngine`
  (constructed; stream not started until the Synth tab is first shown).
- `RedPoleGUI(root, engine, synth_engine, DEFAULT_LOOP_PATH)`.
- On `mainloop()` exit, `engine.stop()` **and** `synth_engine.stop()`.

## Data Flow

1. **Startup** → both engines built; Loop tab active; Loop stream running; Synth stream idle.
2. **Tab switch** → `<<NotebookTabChanged>>` → outgoing `.pause()`, incoming `.resume()`/`.start()`.
3. **Connect patch** → click source cell (single-select) [+ optional transform cell] → set color + BPM
   → **Connect** → `synth_engine.connect_patch(...)` → patch id → add active-patch row.
   The audio thread's next `generate_block` picks it up (engine allocates pitch/role lazily).
4. **Remove patch** → `synth_engine.disconnect_patch(id)` → row destroyed → engine releases + GCs the voice.
5. **Root-note change** → warn → `synth_engine.set_root_midi(n)` → rebuild engine → clear active-patch list.
6. **Load sample** → file picker → `read_mono_audio` + `resample_linear` → `synth_engine.load_sample(samples)`
   → forwarded to `SourceBank.texture.load_sample()`; affects texture patches from their next block.
7. **Waveform** → `_schedule_refresh` reads the active engine's `visual_buffer`; `SynthAudioEngine._callback`
   writes its mono mix each block.

## Error Handling

- **BPM parse** — reuse Loop's `_read_bpm` (clamp + `messagebox` on non-numeric).
- **Connect with no source** — Connect disabled until a source cell is selected; guard `showinfo` as backstop.
- **Load sample failure** — try/except → `showerror`; audio thread untouched; previous/placeholder texture stays.
- **Synth stream open failure on tab switch** — `showerror`, revert to Loop tab, Loop stream keeps running.
- **Per-block render exception on the audio thread** — `SynthAudioEngine._callback` catches and outputs a
  silent block for that buffer rather than tearing down the stream.

## Testing

Mirror the existing convention: pure logic + monkeypatched streams; never open a real device or Tk window.

- `tests/test_synth_audio_engine.py`
  - `connect_patch` returns increasing ids; output is audible, bounded (`|x| ≤ 1+ε`), NaN-free over many blocks.
  - `disconnect_patch` returns to silence when the last patch is removed.
  - `load_sample` changes texture-patch output vs the placeholder.
  - `set_root_midi` rebuilds the engine and clears patches; `root_midi` reflects the new value.
  - Stream lifecycle via `monkeypatch.setattr("synth_audio_engine.sd.OutputStream", FakeStream)`
    (same `FakeStream` pattern as `test_audio_engine.py`); `start()` respects `paused`.
  - `_callback` writes to `visual_buffer`; a raising `generate_block` yields a silent block, not a crash.
  - Concurrency smoke: interleaving `connect_patch`/`disconnect_patch` with `generate_block` never raises.
- `tests/test_synth_tab.py` (pure helpers only)
  - `source_preset_id` over the 5×5 grid yields exactly the 25 source preset ids; likewise transforms.
  - Row order matches `SYNTH_SOURCE_ROWS` / `SYNTH_TRANSFORM_ROWS`; each maps to its engine's presets.
  - `ROOT_NOTE_CHOICES` includes the default 62 and is well-formed `(label, midi)`.
  - Single-select selection helper selects the new cell and clears the prior one.
- `tests/test_audio_io.py`
  - `read_mono_audio` + `resample_linear` behavior preserved (round-trip / resample length),
    proving the lift out of `audio_engine.py` is behavior-preserving.
- **Regression** — full suite (378 existing + Loop `test_gui.py`/`test_audio_engine.py`) still passes;
  `audio_engine.read_mono_audio` / `resample_linear` remain importable (re-exported).

## Non-goals / deferred

- Live harmonic-field evolution, collective tempo, chord transitions (source spec Phase 4).
- Drag-and-drop cable patch bay for Synth (dropdowns/grids chosen for the first pass).
- Persisting patches between sessions.
