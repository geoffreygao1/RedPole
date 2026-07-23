# Synth Patch-Bay Redesign + CPU Headroom — Design

**Date:** 2026-07-23
**Status:** Approved design, ready for implementation plan.

## Goal

Two changes to the desktop app's **Synth** tab:

1. **Replace the button-grid UI with a drag-cable patch bay** matching the Loop tab / GitHub-Pages webapp interaction. Two 5×5 jack grids on one canvas — sources (left) and transforms (right) — with cables dragged from a source jack to a transform jack to create a voice.
2. **Fix clipping/glitching and give CPU headroom.** Move synth audio off the `sounddevice` callback (producer thread + blocking `write()` with a large buffer), replace the matplotlib waveform with a lightweight Tk-canvas polyline, and early-out the one heavy source engine (`resonant`) when it is silent.

## Background / root cause

Benchmarks (44.1 kHz / 1024 = 23.2 ms budget per block): `additive`/`granular`/`noise`/`texture` render in 0.06–0.24 ms; only `resonant` is heavy at 3.66 ms; 8 mixed patches = 10.4 ms — all under budget. Yet the user hears clicks with **even a single additive source**, which is trivially cheap. Therefore the glitch is **not** DSP cost — it is **GIL starvation of the audio callback**: `sd.OutputStream(callback=…)` runs the Python callback on a thread that needs the GIL, while the matplotlib waveform redraw (4096 points, ~20×/s) holds the GIL in long Agg-render bursts on the Tk main thread. When a redraw holds the GIL past the callback deadline, the stream underruns → click. The webapp never has this because its audio runs in a C/WASM worklet fed by a ring buffer; the desktop must emulate that decoupling.

## Scope

**In scope:**
- Rewrite `SynthTab` (widget) to a canvas drag-cable patch bay + a Tk-canvas waveform. Delete the button grids and the matplotlib figure from the synth tab.
- Rewrite `SynthAudioEngine`'s stream lifecycle to a producer thread + blocking `write()` at `latency="high"`.
- Add a silent early-out to `ResonantPulseSource.render` (exact-semantics optimization).
- New pure geometry helpers in `synth_tab.py` for the two-grid bay, unit-tested.

**Out of scope / unchanged:**
- Loop tab audio and UI (no reported issue; its waveform refresh is already gated to the active tab).
- `SoundscapeEngine` orchestration, other source/transform engines, harmony/density modules.
- The pure helpers already in `synth_tab.py` (`source_preset_id`, `transform_preset_id`, `ROOT_NOTE_CHOICES`, `parse_bpm`) — kept as-is.
- Hardware input, TouchDesigner, web/Pyodide.

## Component 1 — Drag-cable patch bay (`synth_tab.py` widget rewrite)

**Layout** (mirrors the Loop tab): left control column (Play/Pause, finger-color picker + BPM + swatch + Random, Load Sample, root-note selector), a **Canvas** patch bay as the centerpiece, an active-patch list with Remove, and a waveform strip.

**Bay geometry** (new pure helpers, reusing `gui._patch_cable_points`):
- Two 5×5 jack grids drawn on one canvas. Left = sources (rows `SYNTH_SOURCE_ROWS = additive/granular/resonant/noise/texture`, cols I–V). Right = transforms (rows `SYNTH_TRANSFORM_ROWS = delay/spectral/pitch/grainfx/spatial`, cols I–V).
- Helpers: `source_cell_center(row,col)`, `transform_cell_center(row,col)`, `source_cell_at(x,y)`, `transform_cell_at(x,y)` (return `(row,col)` or `None`), plus origin/cell-size/jack-radius constants. Cell↔preset mapping reuses the existing `source_preset_id`/`transform_preset_id`.

**Interaction** (same gesture as the Loop bay's `_on_patch_press/_drag/_release`):
- **Press** on a source jack → begin a dashed cable from that jack following the cursor.
- **Drag** → dashed cable tracks the pointer.
- **Release on a transform jack** → `connect_patch(current hue/sat/val/bpm, source_preset_id(sr,sc), transform_preset_id(tr,tc))`; draw a **solid cable colored by the scan color captured at release**; append to the active-patch list.
- **Release off the transform grid** (including a plain click on a source cell with no drag) → a **source-only** voice (`transform_preset=None`), drawn as a short colored stub on the source jack.
- Voices accumulate; cap at 25 (`SYNTH_PATCH_LIMIT`), matching the Loop bay. Each voice = an active-patch row (swatch, `BPM`, `source → transform`, Remove). Removing clears its cable.
- Patch state is a `dict[patch_id -> {hue,sat,val,bpm,source_cell,transform_cell,color}]` in the widget, redrawn each change (mirrors the Loop tab's `_redraw_patch_bay`).

**Waveform** (replaces matplotlib): a `tk.Canvas` polyline. Each refresh reads `visual_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)`, downsamples to ~`WAVEFORM_POINTS = 480` points (block-max over segments so transients still show), maps to canvas coords, and updates a single `create_line` item's coords. Refresh only while the Synth tab is the visible tab (guarded by a callable the GUI passes in, or `self.frame.winfo_viewable()`), at `REFRESH_MS = 50`.

## Component 2 — Audio pipeline (`SynthAudioEngine` lifecycle rewrite)

Replace callback mode with a **producer thread + blocking write**:
- `__init__(samplerate=44100, blocksize=2048, seed=None, root_midi=62)` — larger default block for fewer `write()` calls.
- `_open_stream()` → `sd.OutputStream(samplerate, blocksize, channels=2, latency="high")` (no `callback`). `latency="high"` gives PortAudio a large internal buffer; PortAudio pulls audio in its own C thread, so a UI GIL stall delays the producer's next `write()`, not playback — the buffer absorbs it.
- `resume()` → set `_paused=False`, open stream if needed, `stream.start()`, and start the producer thread if not already running. `pause()` → `_paused=True` (producer then writes silence to keep the stream fed without underrunning; content resumes on `_paused=False`). `stop()` → signal the producer to exit, join it, `stream.stop()`+`close()`.
- **Producer loop** (`_run_producer`): `while self._running: block = self.generate_stereo_block(self.blocksize) if not self._paused else zeros; self._stream.write(block)`. `write()` provides backpressure/timing. Exceptions are swallowed per iteration so one bad block can't kill playback.
- `generate_block`/`generate_stereo_block`/patch-control/sample/root methods are unchanged (still lock-guarded).

This is the desktop analogue of the webapp's render-ahead ring buffer, and directly removes the callback-needs-GIL failure mode.

## Component 3 — `ResonantPulseSource` silent early-out (exact-semantics)

`resonant` rings out to near-silence within tens of ms after each sparse pulse, then stays silent for hundreds of ms until the next pulse. Add an early-out that preserves exact output:
- Precompute whether any pulse fires within this block (from `next_pulse` and `pulse_interval`).
- If **no pulse fires this block** and `max(|y1|, |y2|) < 1e-6` (fully rung out), advance `next_pulse` by `frames` and return `zeros` — skipping the per-sample loop.
- Otherwise run the existing loop unchanged.

Result: the expensive loop runs only during the brief ring or on a pulse block; the vast majority of blocks return zeros cheaply. Output is numerically identical to the current implementation within `1e-6` (the skipped values are already below that threshold).

## Data flow

1. Startup: Loop tab active, loop stream running; synth stream idle.
2. Switch to Synth: Loop stream pauses, `synth_engine.resume()` opens the stream + starts the producer thread.
3. Draw a source→transform cable: `SynthTab` captures the current scan color/BPM, calls `synth_engine.connect_patch(...)`, stores patch state, redraws the bay with the colored cable, adds a list row. Producer's next block renders it.
4. Remove: `disconnect_patch(id)`, drop the cable + row.
5. Root change / Load sample / Random / picker: unchanged from current behavior.
6. Waveform: Tk-canvas polyline refresh while the Synth tab is visible, reading `visual_buffer`.

## Error handling

- Producer/stream exceptions swallowed per block (silent block, no crash), same defensive posture as today.
- Synth stream open failure on tab switch: `showerror`, revert to Loop, restore Loop playback (behavior already present in `gui._on_tab_changed`).
- Bad sample file: `showerror`; empty sample rejected by `load_sample_array` (already present).
- Drag that starts off any source jack: no-op (no cable begun).

## Testing

- **`test_synth_tab.py`** — keep existing pure-helper tests. Add pure geometry tests: `source_cell_at`/`transform_cell_at` round-trip with `source_cell_center`/`transform_cell_center`; out-of-grid returns `None`; the two grids don't overlap in x. Add Tk-guarded widget tests: a simulated source-jack press + transform-jack release calls `connect_patch` with the expected preset ids and adds one active patch; a press + off-grid release creates a source-only patch (`transform_preset is None`); Remove disconnects.
- **`test_synth_audio_engine.py`** — replace the callback-lifecycle tests with producer/`write()` tests using a fake stream recording `write()` calls: `resume()` opens a `latency="high"` stream, starts it, and the producer writes at least one stereo block; `pause()` keeps the stream open but the producer writes silence; `stop()` joins the producer and closes the stream. Keep all `generate_block`/sample/root tests. Ensure the producer thread is deterministically stopped in each test (via `stop()`), no leaked threads.
- **`test_soundscape_sources.py`** — add a resonant equivalence test: a fresh `ResonantPulseSource` with the early-out matches a reference run of the pre-change loop within `atol=1e-6` over many blocks (including at least one pulse), and a long silent stretch returns exact zeros.
- **Regression:** full suite (`py -3.11 -m pytest tests/ -v`) stays green with zero pre-existing-test changes.
- **Manual (human):** launch `py -3.11 main.py`; on the Synth tab, drag a cable and confirm audible voices with **no clicks/glitches** for a single source and for several stacked; confirm the waveform tracks without stutter. (Codex marks done-by-inspection; the user verifies by ear.)

## Non-goals / deferred

- Reworking Loop-tab audio to the producer model (revisit only if Loop also glitches).
- Selecting/removing a voice by clicking its cable (list Remove is the primary path; cable-click removal is a nice-to-have, not required).
- Full analytic vectorization of the resonant IIR (the silent early-out captures the real-world win at zero correctness risk).
