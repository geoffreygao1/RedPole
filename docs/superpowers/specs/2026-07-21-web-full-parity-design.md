# Web app full-parity expansion — design

## Context

`webapp/` (deployed via GitHub Pages, see `.github/workflows/deploy-pages.yml`) is a deliberately scoped-down MVP port of the desktop Tkinter app in `audio_prototype/`, per `docs/superpowers/specs/2026-07-17-github-pages-web-port-design.md`. That spec explicitly deferred: the random-scan button, cable-drag preview, curved cable rendering, the full 5x5/25-jack patch bay, and several DSP engines (spectral, standalone granular, crowd/entry-gesture, reverb room-style variety).

This spec covers bringing `webapp/` to full functional parity with the desktop app, split into three sub-projects, each with its own implementation plan:

1. UI interactions (random button, cable-drag preview, curved cables, source list/remove)
2. Full 5x5 patch bay
3. Full DSP engine parity

Waveform/modulation-trace visualization is explicitly **out of scope** (dropped during brainstorming — desktop's matplotlib panel is not being ported).

## Sub-project 1: UI interactions

**Files touched:** `webapp/main.js`, `webapp/index.html`, `webapp/style.css`. No changes to `webapp/worker.js` or Python engine code — `remove_source` is already handled by the worker (confirmed in `worker.js`).

### Random button
- New button in the Scan Input section, next to Send.
- On click: pick a random `(x, y)` within the picker canvas bounds and a random BPM in `[45, 180]` (mirrors desktop `RANDOM_BPM_MIN`/`RANDOM_BPM_MAX` and `_random_scan_values`, `gui.py:39-40,75-80`).
- Updates the picker cursor position and the BPM input field's value, using the same code path as a manual picker click (`pickerCoordsToHsv` + redraw).
- Does **not** call Send — matches desktop behavior where Random only stages the color/BPM; the user still clicks Send.

### Cable rendering (shared by preview and committed connections)
- Port `_patch_cable_points(x1, y1, x2, y2)` (`gui.py:129-140`) to JS: a 12-step parabolic-sag polyline, `sag = clamp(|x2-x1| * 0.16, 24, 72)`, `y = lerp(y1,y2,t) + sag * 4 * t * (1-t)`.
- `drawPatchBay()` uses this curve function for every committed connection line (replacing the current straight-line draw), color-matched to the source as today.

### Cable-drag preview
- `onPatchDrag` (currently a documented no-op at `main.js:253-257`) is replaced: while dragging from a source dot, track the live cursor position, compute the sag curve from the source's fixed position to the cursor, and redraw the patch bay each move event with that curve drawn dashed (matches desktop's `dash=(4,3)`, `gui.py:576-599`).
- On release: preview is discarded; if released over a valid cell, commit the real connection (existing `connect_source`/`disconnect_source` worker messages, unchanged) and draw it as a solid curve.

### Source list with Remove
- New panel below (or beside) the patch bay listing every **confirmed** source: color swatch, BPM, and its connected cell label (or "unconnected").
- Each row has a Remove button. Click sends `remove_source` to the worker, removes the source from local state (`_pendingSources`/confirmed-sources array — needs an explicit canonical sources registry keyed by source id, since main.js currently only tracks pending + placed dots implicitly), redraws the patch bay, and frees a `PATCH_SOURCE_LIMIT` slot.
- Sources still pending (before the `source_added` reply arrives) do not appear in the list yet — avoids racing removal against an id that doesn't exist yet.
- Matches desktop semantics: Remove fully deletes the source (disconnects from any cell **and** removes it), not just a disconnect (`gui.py` `_on_remove`).

## Sub-project 2: Full 5x5 patch bay

**Files touched:** `webapp/main.js` only (grid is drawn on canvas; no Python/worker protocol change — engine name strings sent via existing `connect_source` message just gain new valid values).

- `PATCH_GRID_ROWS` grows from 2 to 5. Row order/engines: `["microloop", "granules", "glitch", "multidelay", "tape"]` (matches desktop `PATCH_ROW_ENGINES`, `gui.py:44`).
- Column labels: the `tape` row uses `["wow", "flutter", "tone", "dropout", "reverb"]`; the other four rows use `["I", "II", "III", "IV", "V"]` (variant columns, matches desktop `PATCH_COL_LABELS`/`PATCH_TAPE_COL_LABELS`, `gui.py:45-46`).
- Cell (row=`tape`, col=4) is always the dedicated `reverb` engine regardless of row, matching desktop's `_patch_cell_to_engine` override (`gui.py:83-88`: `if row == 4 and col == 4: return "reverb"`).
- `PATCH_SOURCE_LIMIT` raised from 8 to 25 (matches desktop `PATCH_SOURCE_LIMIT`, `gui.py:56`).
- Canvas sizing/layout constants adjusted so 25 jacks + 5 columns fit legibly (desktop uses `PATCH_CANVAS_W=960`, `PATCH_CANVAS_H=440`, `PATCH_CELL=58` as reference proportions).

## Sub-project 3: DSP engine parity (true desktop-GUI parity)

**Files touched:** `audio_prototype/web_engine.py` (Python, shared/loaded by Pyodide — no duplication, fetched at runtime), `webapp/worker.js` (`PYTHON_FILES` fetch list), `.github/workflows/deploy-pages.yml` (publish the new `.py` file(s) to `site/audio_prototype`).

**Scope correction from initial brainstorm:** `gui.py` never calls `AudioEngine.set_mode()` (default mode is `"mixed"` and stays there for the life of the app) and never calls `SchroederReverb.set_space()`. So the standalone `"spectral"`/`"granular"` single-engine modes and reverb room-style variety are reachable only from `audio_engine.py`'s own tests, never from the running desktop GUI. "Same engines as the python project" means matching what the GUI actually does, not the full surface of `audio_prototype/`'s test-only code paths. Concretely, that means:

- **In scope:** all 4 microcosm families (`microloop`/`granules`/`glitch`/`multidelay`), crowd/entry-gesture gain modulation — both always active in the real desktop app's mixed mode.
- **Out of scope:** standalone `spectral`/`granular` engine modes, reverb room-style picking (`set_space`) — neither is exposed by the desktop GUI today, so porting them would be new functionality beyond parity, not parity itself.

`WebEngine.generate_block` (`web_engine.py:70-142`) currently only mixes `tape`, `granules` (via `MicrocosmProcessor`, filtered to the single `"granules"` engine name), and `reverb` layers. `MicrocosmProcessor.process` (`microcosm_processor.py:127-141`) already dispatches generically by `layer["engine"]` against `FAMILIES = ("microloop", "granules", "glitch", "multidelay")` — so extending to all 4 families needs no new DSP code, just a wider engine filter in `web_engine.py` (`gran_layers = [l for l in layers if l["engine"] in MICRO_FAMILIES]` instead of the current `== "granules"` check).

Plan:
- Widen `web_engine.py`'s layer filter from `l["engine"] == "granules"` to `l["engine"] in ("microloop", "granules", "glitch", "multidelay")`, passed to the existing `MicrocosmProcessor` instance unchanged.
- Import and instantiate `CrowdState`/`EntryGestureTracker` (`crowd.py`) in `WebEngine.__init__`, mirroring `AudioEngine.__init__`, and apply `entry.engine_gain(...)` modulation to the microcosm wet signal the same way desktop's mixed mode does (`audio_engine.py:346` pattern, adapted — desktop applies gain to `spectral_wet`/`granular_wet`, which don't exist here; apply the equivalent gain to `wet_raw` from `MicrocosmProcessor` and to the tape base's bloom depth, matching whichever engines desktop actually gain-modulates in mixed mode for `tape`/microcosm-family layers).
- New Python file added to `webapp/worker.js`'s `PYTHON_FILES` fetch list and `deploy-pages.yml`'s publish step: `crowd.py`. (`frequency_mod_processor.py`/`granular_processor.py`/`spectral_processor.py` are **not** added — out of scope per above.)
- No new engine name strings for `main.js` to send beyond the 4 microcosm families already covered by Sub-project 2's row expansion (`microloop`/`granules`/`glitch`/`multidelay`/`tape`/`reverb`) — no additional patch-bay UI affordance needed.

## Error handling

- Pyodide fetch failures for new `.py` files: existing `worker.js` error path (posts `error` message, surfaced in the status banner) covers this without changes.
- Removing a pending source: Remove button hidden/disabled until `source_added` confirms, avoiding an id race.
- No reverb-layer edge case: unchanged from today, falls back to existing defaults (`REVERB_DEFAULT_FEEDBACK`/`REVERB_DEFAULT_CUTOFF`).

## Testing

- No JS unit test harness currently exists for `webapp/`; verification is manual in-browser (matches how the MVP itself was verified per the web-port design doc).
- Python engine changes in `web_engine.py` can reuse/extend existing Pytest coverage patterns from `audio_prototype/tests/` (e.g. `test_audio_engine.py`'s mixed-mode fixtures) to unit-test the ported mixing logic without a browser.
- Manual browser pass after each sub-project: verify Random fills fields without sending, cable preview follows cursor and commits correctly, full 25-slot bay connects/disconnects across all 5 rows including the tape/reverb override cell, and each new microcosm family (microloop/glitch/multidelay, alongside existing granules) produces audibly distinct output when patched.
