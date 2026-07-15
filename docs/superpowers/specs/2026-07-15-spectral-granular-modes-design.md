# RedPole Audio Prototype — Spectral & Granular Engine Modes

## Purpose

The tape warble/bloom modulation validated the interaction flow but is too
subtle: each sent color barely changes the sound. This extension adds two
more pronounced processing modes — a Rossum Panharmonium-inspired spectral
resynthesis mode and a granular synthesis mode — selectable from the GUI,
so each can be A/B'd against the tape baseline on the same loop. In both
new modes each sent layer contributes its own audible voice, giving every
color/BPM a distinct sonic identity.

Builds on the existing prototype (see
`2026-07-15-audio-plugin-prototype-design.md`); all of that design still
holds except where amended here.

## Architecture

A new "engine mode" concept: `Tape` | `Spectral` | `Granular`, selected by
a GUI dropdown. `AudioEngine.generate_block` becomes a dispatcher that
snapshots the layer registry and calls the active processor's
`process(loop_array, frames, layers)`. All three processors stay alive
simultaneously; layers persist across mode switches; switching is instant
and non-destructive. All modes share the layer registry, ring buffers, and
the soft-clip output stage.

### `spectral_processor.py` — Panharmonium-style resynthesis

- On loop load, the loop is analyzed **once, offline** (never in the audio
  callback): an STFT over the whole loop extracts the top ~24 partials
  (frequency, amplitude) per analysis frame — a precomputed "spectral
  movie" of the loop.
- Each layer is an independent oscillator-bank voice scanning through
  those frames and resynthesizing them as a sum of sines:
  - **Hue → pitch shift** of all partials (~±7 semitones, red at center)
  - **BPM → scan speed** through analysis frames (slow = frozen/smeared,
    fast = livelier tracking)
  - **Saturation → spectral blur** (smoothing of partial freq/amp between
    frames) — secondary parameter, since real finger saturations cluster
  - **Value → voice level**
- The dry loop keeps playing underneath. 0 layers = exactly the dry loop.

### `granular_processor.py` — grain streams

- Each layer is an independent grain stream sampling slices of the loop:
  - **Hue → grain pitch shift** (transposition, ~±12 semitones)
  - **BPM → emission rate, clustered in heartbeat-like pulses** (grain
    bursts at the layer's heart rate — each person's pulse is audible)
  - **Saturation → grain size** (~60–250 ms, Hann-windowed)
  - **Value → stream volume**
- Grains are rendered at trigger time into an overlap-add buffer (short
  resampled slice), so per-block audio-callback cost is just mixing.
- Dry loop underneath, same as spectral. 0 layers = exactly the dry loop.

### Engine / GUI changes

- Mode dropdown in the Scan Input panel.
- `AudioEngine` gains a thread-safe `mode` property and a "wet-only" ring
  buffer (the added texture without the dry loop) written every block in
  all modes.
- Visualizer: output trace unchanged; the faint background trace shows the
  wet-only signal in Spectral/Granular modes (and the existing
  warble/bloom control traces in Tape mode), so what's being added is
  always visible.
- Spectral analysis runs on the GUI thread during `load_loop` (well under
  a second for a several-second loop), never in the audio callback.

## Parameter-mapping priorities

Hue and BPM are the primary identity carriers (real finger scans differ
mainly in hue and pulse); saturation and value are secondary trim. Exact
ranges above are starting points to be tuned by ear during manual testing.

## Error handling

- 0 layers in any mode → bit-exact dry loop; mode switch with 0 layers is
  inaudible.
- Added-voice energy normalized by layer count so stacking thickens rather
  than clips; existing soft clipper stays as the final stage.
- If spectral analysis is missing or failed for the current loop, Spectral
  mode falls back to dry playback instead of crashing the audio callback.

## Testing

Unit tests in the existing style (pure/device-free):
- Spectral analysis returns expected shapes and locates a known test
  tone's partial frequency.
- An oscillator-bank voice reproduces a pure tone's pitch shift within
  tolerance.
- Grain scheduling produces bursts at the expected pulse rate.
- Each mode's `process()` returns the requested block length and persists
  state across calls.
- 0-layer passthrough is exact in all modes.

Manual pass: A/B the three modes on the same loop; verify each added layer
is individually audible in Spectral and Granular modes; verify layers
persist across mode switches; verify no clipping with many layers.

## Out of scope

- Live-input spectral analysis (the Panharmonium analyzes live audio; we
  analyze the stored loop — deliberate simplification).
- Combining modes simultaneously (rejected in design discussion in favor
  of A/B-able mode selector).
- Hardware integration, persistence, networking (unchanged from the base
  spec).
