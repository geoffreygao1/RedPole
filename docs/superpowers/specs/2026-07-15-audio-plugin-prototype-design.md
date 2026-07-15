# RedPole Audio Plugin Prototype — Design Spec

## Purpose

RedPole's hardware (ESP32-S3 + camera, see `src/camera_handler.cpp`) scans a
user's finger, producing a color reading (from light passing through the
finger) and a heart rate (BPM). The end goal is an audio plugin where each
user's scan modulates a shared, looping base audio track — as more users
interact, their modulations stack, and the loop progressively warps and
merges into something new.

This spec covers a **standalone Python prototype** to test that experience
flow before any hardware integration: a GUI stands in for the scanner
(color + BPM controls), a "Send" action stands in for a scan event, and a
real-time audio engine plus waveform visualizer let us hear and see the
effect immediately.

## Scope

In scope: local, real-time, single-machine prototype. Simulated scanner
input via GUI. Live audio modulation and visualization. Out of scope (fast
follow, not this prototype): ESP32/hardware integration, spectral
resynthesis (Rossum Panharmonium-style FFT reprocessing), persistence
across app restarts, networked/multi-device use.

## Architecture

Three modules:

### `audio_engine.py`
Loads the base loop (WAV, via `soundfile`) into a numpy array and streams
it continuously through a `sounddevice.OutputStream` callback. Every audio
block, it reads the current combined modulation state (see `layers.py`)
and applies two effects to the looping signal:

- **Warble (pitch character):** a phase-accumulator-driven pitch modulator
  built from three superimposed components — a slow "wow" drift (~0.2–2 Hz),
  a faster "flutter" wobble (~4–12 Hz), and smoothed random noise for
  jitter/imperfection — applied via resampling. This is deliberately organic
  and non-repeating rather than a single clean sine LFO, to get a
  tape-like character rather than an obvious chorus/vibrato effect.
- **Bloom (amplitude character):** a smoothed, noise-driven amplitude
  multiplier ("breathing") rather than a rhythmic tremolo gate — again
  favoring organic drift suited to ambient soundscapes over an obviously
  rhythmic effect.

Both modulators' **rate** is anchored to the combined BPM (Hz = BPM / 60,
averaged across active layers) and **depth** is driven by combined HSV
(hue → warble depth, saturation/value → bloom depth, summed across active
layers and clamped to a sane maximum). The output additionally passes
through a soft clipper/limiter so stacking layers can never hard-clip.

With zero active layers, the engine plays the dry, unmodulated loop.

### `layers.py`
A thread-safe registry of active "sends." Each layer is a plain dict:
`{id, hue, sat, val, bpm}`. Adding a layer (on "Send") appends to the list;
removing a layer (on GUI "Remove") deletes it by id. All access goes
through a lock, since the audio callback thread reads the registry every
block while the GUI thread mutates it on user action.

The engine recomputes combined warble/bloom parameters from the full
active-layer list on every audio block:
- depth = sum of each layer's per-parameter depth contribution, clamped to
  a max
- rate = average of each layer's BPM-derived Hz value

An empty registry means depth = 0 (dry playback).

### `gui.py`
Tkinter window containing:
- **Load Loop** — file picker (`soundfile`-readable WAV), defaults to a
  bundled sample if none is chosen on first launch
- **Color controls** — Hue slider (clamped to a red-ish range, mirroring
  what the real finger-scan sensor can actually return), Saturation
  slider, Value slider, plus a live color swatch preview reflecting the
  three sliders
- **BPM slider** — e.g. 40–180 range
- **Send button** — reads current slider values, appends a new layer to
  the registry, refreshes the layer list
- **Active layers list** — one row per layer (showing its color swatch +
  BPM), each with a **Remove** button that deletes that layer from the
  registry
- **Waveform visualizer** — a Matplotlib canvas embedded via
  `FigureCanvasTkAgg`, redrawn on a ~50ms Tkinter `after()` timer from a
  small ring buffer that the audio callback continuously writes into

## Data Flow

1. **Audio thread** (real-time, driven by `sounddevice`): every block
   (~10–20ms), takes a lock-protected snapshot of the layer registry,
   computes combined warble/bloom parameters, applies them to the next
   chunk of the looped base audio, writes the result to the output device,
   and pushes a copy into the ring buffer.
2. **GUI thread**: on its own timer, reads the latest ring buffer contents
   and redraws the waveform plot. Slider/button interactions only ever
   touch the layer registry — never the audio buffer directly — so the
   only shared state needing synchronization is the registry itself.
3. **Send**: GUI reads current slider values → appends a new layer dict to
   the registry → refreshes the layer listbox. Takes effect on the very
   next audio block.
4. **Remove**: GUI deletes the corresponding layer dict from the registry
   → refreshes the listbox. Takes effect on the very next audio block.

## Error Handling

- No audio output device available → caught at startup, shown as a
  Tkinter error dialog (with the device list if available), then exit
  cleanly.
- Loop file fails to load (bad format / missing file) → error dialog;
  keep whatever loop was already playing, or fall back to the bundled
  default sample on first launch.
- Empty layer list → dry, unmodulated playback (not an error, just the
  baseline state).
- Combined warble/bloom depth is clamped to a fixed maximum regardless of
  how many layers are active, and the final output passes through a soft
  clipper/limiter, so stacking many layers thickens/warps the sound
  without ever hard-clipping or damaging output hardware.

## Testing

This is an interactive audio/GUI prototype, so verification is primarily a
manual pass:
- Dry loop plays cleanly with zero layers.
- Adding one layer produces audible, organic (non-rhythmic-sounding)
  warble + bloom.
- Adding several layers increases the sense of stacking/warping without
  clipping.
- Removing a layer audibly reduces the effect and updates the layer list.
- Waveform visualizer updates live and reflects the modulated (not dry)
  signal.
- No hard clipping/distortion at a high layer count.

Pure DSP math functions that don't need an audio device — hue→depth
mapping, BPM→Hz conversion, depth summation/clamping — get small unit
tests, since they're straightforward to verify in isolation.

## Explicitly Deferred (not this prototype)

- Cumulative "tape wear" / degradation over time — considered and
  rejected; the goal is tape-like *coloration* of the modulation, not a
  progressively decaying state.
- Spectral resynthesis (Rossum Panharmonium-style FFT reprocessing) — a
  bigger build; may be explored as a fast-follow once the interaction
  flow and basic modulation feel are validated.
- Real ESP32 hardware integration — the GUI is a stand-in for the scanner
  for this prototype.
