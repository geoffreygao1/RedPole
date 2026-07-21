# RedPole Audio Prototype — GitHub Pages Web Port (MVP)

## Purpose

Make the RedPole audio prototype playable online via GitHub Pages: a
fully interactive, real-time version in the browser, not a static demo.
The desktop app (`audio_prototype/`) is a Python/Tkinter/`sounddevice`
program; GitHub Pages serves static files only, with no server-side
Python. This spec covers a phased first version (MVP) that proves the
browser can run the real-time Python DSP live, with a deliberately
reduced feature set — later phases add the remaining engines and patch
bay rows without changing this architecture.

## Scope (MVP)

**In scope:**
- The always-on tape base path, including its per-column wow / flutter /
  tone / dropout controls.
- One legacy effect family: **granules** (from `microcosm_processor.py`).
- Reverb, routed the same way as the desktop app (tape row, column V).
- A 2-row patch bay (tape row + granules row, 10 slots) using the same
  drag-a-cable interaction model as the desktop app, so later phases are
  additive (more rows), not a UI rebuild.
- Loading a user-supplied audio file (WAV/MP3/etc.) as the loop, via the
  browser's native file picker and `decodeAudioData`.
- Play/Pause, matching the desktop app's paused-by-default behavior.

**Out of scope for MVP (explicit fast-follows):**
- microloop, glitch, multidelay families; the standalone `granular`/
  `spectral` engines; crowd/entry-gesture accents; the full 25-slot bay.
- Waveform visualization.
- Any UI polish beyond a functional patch bay and scan-input panel.

## Architecture

### Zero-duplication principle

The web app does not maintain a second copy of the DSP code. At runtime
(local dev) it fetches the actual files living in `audio_prototype/` —
`pyodide.pyfetch('../audio_prototype/tape_modulator.py')` etc., written
into Pyodide's virtual filesystem, then imported normally — so the exact
same `tape_modulator.py`, `microcosm_processor.py`, `reverb.py`,
`wet_bus.py`, `modulation.py`, and `layers.py` that the desktop app uses
and that pytest already covers are what runs in the browser. `microcosm_processor.py` itself is not modified: `MicrocosmProcessor`
already only acts on layers whose `engine` is in its `FAMILIES` tuple, so
restricting the *web patch bay*'s own routing config to offer just
`granules` (not microloop/glitch/multidelay) is enough to realize the
reduced MVP scope — no extraction or new subclassing needed. The only new
Python file is `web_engine.py` (added alongside the others in
`audio_prototype/`): it reuses those classes as-is but replaces the
desktop-only orchestration (`sounddevice.OutputStream`, device pause/
resume, `soundfile`-based loading, chunked-read/resample) with:
- `generate_block(frames) -> np.ndarray` — called repeatedly by the
  Worker's pacing loop.
- `load_loop(samples)` — takes already-decoded, already-resampled mono
  float32 samples (the browser's `decodeAudioData` did that work), so no
  `soundfile`/manual-resample logic is needed here at all.
- No pause state of its own — pausing is purely "the Worker stops calling
  `generate_block` and the `AudioContext` is suspended."

### New files (`webapp/`, kept separate from `docs/superpowers/`)

- `index.html`, `style.css` — page shell, scan-input panel (color picker,
  BPM, Send), 2-row patch bay canvas, Load Loop / Play-Pause controls.
- `main.js` — creates a suspended `AudioContext` (resumed on Play), spins
  up the Worker and the AudioWorklet node, wires UI events to Worker
  messages, handles file selection + `decodeAudioData`.
- `worker.js` — loads its own Pyodide instance, `pyfetch`s the needed
  `.py` files, imports them, instantiates `web_engine`, owns the
  block-generation pacing loop and the live `LayerRegistry` state.
- `worklet.js` — a small pure-JS `AudioWorkletProcessor` (no Pyodide —
  the audio-rendering thread can't host it). Buffers blocks handed to it
  by the Worker and copies them into each render quantum.
- `.github/workflows/deploy-pages.yml` — see Deployment below.

### Runtime data flow

1. **Startup:** main thread creates the suspended `AudioContext` using
   its actual `sampleRate` (not a hardcoded 44100 — `web_engine` already
   takes `samplerate` as a constructor argument, so whatever the browser
   reports gets threaded straight through). It creates the Worker, which
   loads Pyodide, fetches and imports the `.py` files, and instantiates
   `web_engine`. In parallel, `main.js` registers the AudioWorkletProcessor
   and connects it to the destination.
2. **UI -> Worker:** every user action (Send, connect/disconnect a cable,
   move the wet/dry slider, Play/Pause, load a file) posts a small JSON
   message to the Worker (e.g. `{type: "add_source", hue, sat, val, bpm}`,
   `{type: "connect_source", sourceId, engine, row, col}`,
   `{type: "load_loop", samples}` as a transferable `Float32Array`). The
   Worker applies these directly to its live registry/engine state —
   single-threaded, no real race condition to guard against.
3. **Worker -> Worklet:** the Worker tracks how much audio it has handed
   off but not yet confirmed played. Whenever that "buffered ahead"
   amount drops below a low-watermark (~150ms), it calls
   `web_engine.generate_block(4096)` (~93ms/call — large enough to keep
   per-call Pyodide/numpy overhead low, small enough to keep latency
   reasonable), converts the result to a `Float32Array`, and transfers it
   (zero-copy, `postMessage(buf, [buf.buffer])`) to the worklet. It stops
   generating once buffered-ahead hits a high-watermark (~300ms), keeping
   memory bounded.
4. **Inside the worklet:** a FIFO of incoming blocks; each 128-sample
   `process()` call pulls from the head. An empty queue (Worker fell
   behind) outputs silence for that quantum and increments an underrun
   counter, reported back to the main thread periodically for an on-page
   debug readout.
5. **Loading a file:** `main.js` reads the selected file as bytes,
   `audioContext.decodeAudioData()`s it (decodes format *and* resamples
   to the context's rate in one step), downmixes to mono by averaging
   channels, truncates to a length cap (parity with the desktop app's
   10-minute guard), and transfers the resulting samples to the Worker as
   a `{type: "load_loop", samples}` message.

Net intentional latency: roughly 150-300ms of buffering. Irrelevant for
this ambient, color-and-BPM-driven tool — it is not a low-latency
instrument.

## Error Handling

- Pyodide fails to load, or `AudioWorklet` is unsupported: replace the
  loading indicator with a specific, plain-language error rather than a
  silent hang.
- A Python exception during `generate_block`: caught in the Worker's
  loop, logged, surfaced as an on-page error state.
- Worklet queue underrun: outputs silence for that quantum, counts it;
  never garbles or crashes.
- A fetched `.py` file 404s: a clear error naming the missing file.
- An oversized loaded file: truncated client-side to the length cap
  rather than rejected outright.

## Testing

- The existing pytest suite is unmodified and keeps validating
  `tape_modulator.py`, the `granules` family in `microcosm_processor.py`,
  `reverb.py`, `wet_bus.py`, and `modulation.py` exactly as today.
- New `test_web_engine.py` (plain CPython/pytest, no browser needed):
  dry passthrough with no sources; a tape-column source changes output;
  a granules source changes output; `load_loop` accepts pre-decoded
  samples directly; correct block length from `generate_block`.
- The JS glue (Worker pacing, worklet queue) is manually verified for
  this MVP rather than automated — thin relative to the Python DSP it
  wraps; worth revisiting if it grows.
- Manual checklist: loading indicator shows -> Play starts the bundled
  loop audibly -> Load Loop replaces it with a user file -> a tape-column
  source (e.g. flutter) is audible -> a granules source produces grain
  events -> disconnecting a cable stops that source's contribution ->
  pause/resume is clean -> debug readout shows low/zero underruns during
  normal use -> console free of errors. Primary target Chrome/Edge; quick
  Firefox smoke-check; Safari flagged higher-risk, not MVP-blocking.

## Deployment

Locally, `webapp/index.html` can fetch `../audio_prototype/*.py` directly
with zero duplication as long as something serves the whole repo root
(e.g. `python -m http.server` from the repo root) — edit a desktop engine
file, refresh, see it live in the browser too.

GitHub Pages' Actions-based deploy publishes one designated folder as the
entire site root, so `audio_prototype/` won't exist alongside `webapp/`
in the published output unless placed there. `.github/workflows/
deploy-pages.yml` assembles a staging folder on every push — copies
`webapp/*` plus just the needed `audio_prototype/*.py` files into a
`python/` subfolder — and publishes that. Still exactly one edited
source (`audio_prototype/*.py`); the copy is regenerated fresh by CI on
every deploy, so it cannot go stale. Requires a one-time manual repo
setting: **Settings -> Pages -> Source: GitHub Actions**.

Work happens on the `github-pages` branch, kept separate from the
desktop app's `audio` branch.

## Out of scope (explicit fast-follows)

microloop / glitch / multidelay families, standalone granular/spectral
engines, crowd/entry-gesture accents, full 25-slot patch bay, waveform
visualization, cross-browser hardening beyond the MVP checklist.
