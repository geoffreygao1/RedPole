# Tone.js Hybrid Synth (Browser) — Design

**Date:** 2026-07-23
**Status:** Approved design, ready for implementation plan.

## Goal

Rebuild the RED POLE **synth** as a browser app whose audio runs on **native
Web Audio via Tone.js**, driven by our **generative logic ported to JS**. This
fixes the class of glitches (clicks, clipping, roughness) that are inherent to
our block-based Python/numpy DSP — the same DSP runs in both the desktop
(sounddevice) and current web (Pyodide) builds — by moving the *audio* onto a
sample-accurate native graph while keeping the *musical brain* (harmonic field,
pitch allocation, evolving mix) that makes our sound distinct.

## Why (root cause of the current roughness)

Both current stacks are block-based Python DSP: per-2048/8192-sample blocks, no
per-note envelopes, per-block scalar gain steps, hot manual sums driven into a
soft-clipper, and a Schroeder reverb. Clickbath is clean because Tone.js/Web
Audio gives, natively: per-note attack/release envelopes (`Tone.Sampler`),
sample-accurate parameter ramps (`AudioParam`), convolution reverb, and an
audio-thread graph with no GIL/block boundaries. Our value-add — the generative
engine — is **control-rate** (it decides *which note, when, how loud*), so it
ports to JS cheaply and does not need to be sample-perfect; only the audio does,
and Tone.js owns that.

## Decisions (from brainstorming)

- **Deployment:** browser (kiosk/Electron acceptable). Bundle Tone.js locally
  (no CDN) so it runs offline.
- **Codebase:** evolve `webapp/`. Route **synth mode** to a new Tone.js engine;
  leave **loop mode** on the existing Pyodide worker, untouched.
- **Sources (final grid, 5 rows):** `pluck` / `pad` / `bloom` (sampled
  instruments) + `bells` (Tone.MetalSynth/FM bowls & chimes, rhythmic) +
  `drone` (Tone.FMSynth/DuoSynth evolving pad).
- **Modifiers (5 rows):** `stretch` / `spectral` / `pitch` / `grainfx` /
  `spatial`, mapped to Tone.js effects (spectral is the weakest approximation).
- **Phasing:** MVP = `pluck/pad/bloom` + wash + all 5 modifier rows +
  generative core + patch-bay workflow. Follow-up = `bells` + `drone` rows.
- Reuse the finalized workflow: Send → single-use Sources list → assign to a
  generator jack (silent until cabled) → cable to a modifier; drag-to-reassign;
  Play/Pause; live root, reverb, delay sliders.

## Architecture

```
index.html
 ├─ main.js            (UI: patch bay canvas, sources list, controls) — reused, synth path rewired
 ├─ worker.js          (loop mode: Pyodide) — untouched
 ├─ tone_engine.js     (NEW: Tone.js audio graph + voice lifecycle)
 ├─ generative/        (NEW: ported musical brain, pure JS, unit-tested)
 │    ├─ harmony.js       (HarmonicField: pentatonic + roles + weights)
 │    ├─ allocator.js     (PitchAllocator: register bands, occupancy, detune)
 │    └─ conductor.js     (VoiceConductor: slow evolving gains + role rotation)
 ├─ scheduler.js       (NEW: Tone.Transport loop -> triggers/ramps via the brain)
 └─ vendor/tone.js     (NEW: bundled Tone.js, offline)
```

`main.js` gains a thin seam: when `mode === "synth"`, patch-bay actions
(send/assign/cable/move/remove, play/pause, root/reverb/delay) call
`ToneEngine` methods instead of posting worker messages. Loop mode is unchanged.

## Audio graph (Tone.js, native)

- **Master wash:** `masterGain (headroom trim ~ -6 dB) → Tone.FeedbackDelay
  (delayTime ~ dotted-eighth or fixed 0.4 s, feedback ~0.5, wet = delay slider)
  → Tone.Reverb (decay ~8 s, wet = reverb slider) → Tone.Destination`. The
  reverb/delay wets ride on `Tone.Signal` ramps (no zipper). Reverb tail rings
  after voices stop — inherent to the node.
- **Per voice = its own chain** (created on cable-to-modifier, disposed on
  removal): `sourceNode → modifierNode → voiceVolume (Tone.Volume, ramped) →
  masterGain`. Per-voice chains are what allow per-voice modifiers while the
  wash stays global. ≤25 voices — well within Web Audio budget.
- **Buffers preloaded once** via `Tone.Buffers` from the clickbath WAV maps, so
  per-voice `Tone.Sampler`s reference cached buffers (fast create/dispose).

## Sources

Each source cell maps to a factory that builds the voice's `sourceNode` and a
trigger behavior. Pitch always comes from the generative brain (allocator +
live root); color/BPM shape timbre/attack/trigger density.

**Sampled instruments** (`Tone.Sampler`, per-instrument note maps from the
captured clickbath maps; envelopes give click-free starts):
- **pluck** — `triggerAttackRelease(note, dur)` on the BPM/probabilistic clock;
  natural sample decay rings into the reverb. Cells: piano, guitar, tapeguitar,
  tapebell, casio.
- **pad** — `triggerAttack` on placement, `triggerRelease` on removal; uses the
  naturally-sustaining instruments. Cells: strings, flute, clarinet, casio,
  piano. Long attack/release on the sampler envelope.
- **bloom** — like pad with a long (~1.5 s) attack for a slow swell. Cells:
  strings, flute, clarinet, guitar, tapebell.

**Synth sources (follow-up pass):**
- **bells** — `Tone.MetalSynth` (or `Tone.FMSynth` with high harmonicity),
  triggered on the BPM clock. Cells: bowl, chime, gong, glass, shimmer (vary
  harmonicity / modulationIndex / resonance / decay / octave).
- **drone** — `Tone.FMSynth` / `Tone.DuoSynth` held pad with slow filter/detune
  movement. Cells: warm, glass, hollow, wide-detune, filter-sweep.

## Modifiers (per-voice insert `modifierNode`)

Row → Tone.js realization (5 variants per row via parameter sweeps):
- **spatial** — `Tone.Reverb` (size/decay) and/or a send level; distance =
  lowpass + gain. Variants: room→wash + distance.
- **pitch** — `Tone.PitchShift` (semitones, feedback, wet). Variants: -12, +12,
  +7, fine drift, wide.
- **grainfx** — texture FX: `Tone.Chorus`, `Tone.BitCrusher`, `Tone.Distortion`,
  `Tone.Chebyshev`, `Tone.AutoFilter`. Variants pick one each.
- **stretch** — `Tone.GrainPlayer`-style sustain via a short capture + slow grain
  playback, or a freeze; variants = stretch amount (subtle → freeze/drone).
  (Realized with Tone's grain/looping primitives on the voice's output tap.)
- **spectral** — approximation only (Tone has no phase vocoder): a
  freeze/blur via grain + heavy chorus/feedback. Flagged as the weakest row;
  acceptable per decision.

Cabling a placement to a modifier builds the `modifierNode` and starts the
voice (silent-until-cabled, as in the finalized workflow). Retargeting rebuilds
the node; the note envelope masks the swap. Off-grid clears it (voice released).

## Generative logic (ported to JS, control-rate)

Direct ports of the Python modules as pure JS (no Tone.js deps), each unit-
tested with `node --test`:
- **harmony.js** — `PENTATONIC`, `ROLE_SEMITONES`, `ROLE_WEIGHTS`,
  `midiToHz`, weighted role choice (seeded RNG), `midiForRole(role, octave)`.
- **allocator.js** — register bands + limits, occupancy, `allocate(vid, rng,
  density, detuneClass)` → `{role, octave, detuneCents, midi}`; `release(vid)`.
- **conductor.js** — per-voice slow activity LFO (20–50 s), rank→roles→gain with
  smoothing; `update(activeIds, dtSeconds) → {vid: gain}` (deterministic, seeded).

**scheduler.js** — a `Tone.Loop` at a musical subdivision. Each tick: advances
the conductor, and for each active voice decides trigger/hold and pitch (from
allocator + smoothed live root) and sets the voice's `Tone.Volume` via a short
ramp to `conductorGain`. Pluck/bells → probabilistic triggers scaled by BPM and
role; pad/bloom/drone → hold, retrigger only if faded. A seeded RNG keeps it
reproducible. The live **root** is a `Tone.Signal`-smoothed value the scheduler
reads when computing each note's pitch, so held/next notes glide.

## Workflow / UI (reuse)

The existing `main.js` patch-bay canvas, sources list, and controls are reused.
Synth-mode source grid rows become `pluck/pad/bloom` (+ `bells/drone` after the
follow-up); modifier grid rows become `stretch/spectral/pitch/grainfx/spatial`.
Controls: Play/Pause (`Tone.start()` + transport), root slider (C2–C4), reverb
and delay sliders (0–1.5 / 0–1). Single-use sources, silent-until-cabled,
drag-to-reassign — all as finalized on the desktop.

## Assets & offline

- Instrument samples: the clickbath WAVs already downloaded to gitignored
  `audio_prototype/assets/clickbath/`; copy/serve them under gitignored
  `webapp/audio/clickbath/` (a small `fetch-clickbath` step, already scripted).
  `Tone.Buffers` loads them by the captured note→file maps.
- `webapp/vendor/tone.js`: vendored Tone.js (pinned version), committed so the
  app runs offline with no CDN.

## Phasing (each independently testable)

1. **MVP:** vendor Tone.js; `ToneEngine` master wash; preload buffers;
   `pluck/pad/bloom` instrument voices with envelopes; ported
   harmony/allocator/conductor + scheduler; wire synth-mode UI (send/assign/
   cable/move/remove, play/pause, root/reverb/delay); the 5 modifier rows.
   Deliverable: a clickbath-clean sampled soundbath playable in the browser.
2. **Synth sources:** add `bells` and `drone` rows.
3. **Polish:** tune modifier variants, stretch/spectral quality, levels.

## Testing strategy

- **Pure generative JS** (`harmony/allocator/conductor`): `node --test` unit
  tests — role weighting is seed-deterministic, allocation respects register
  limits, conductor gains are bounded/evolving/GC'd. Mirrors the Python tests.
- **Engine/UI:** Tone.js audio can't be unit-tested headlessly here; verify by
  ear in the browser, plus a static check (extend `tests/test_webapp_static.py`
  / add `node --check` over the new JS so syntax/exports are validated in CI).
- Keep the Python tests green (untouched modules).

## Risks / mitigations

- **spectral** has no faithful native equivalent → flagged weakest; approximate,
  tune later, or drop if unconvincing.
- **stretch** on a live per-voice tap is non-trivial in Tone.js → start with a
  freeze/grain approximation; refine by ear.
- **pad/bloom sustain** depends on samples that actually sustain (strings/flute/
  clarinet); decaying instruments (piano/guitar) in the pad row will still decay
  — acceptable, the reverb fills.
- **Sample licensing:** clickbath assets stay gitignored/local; not redistributed.
- **Per-voice node churn** on rapid assign/move → dispose promptly; cap at
  `SYNTH_PATCH_LIMIT` (25).
- **Tone.js version drift:** pin and vendor a specific version.
