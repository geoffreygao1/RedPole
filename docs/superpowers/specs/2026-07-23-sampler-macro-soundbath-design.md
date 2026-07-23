# Sampler Macro Soundbath (Web) - Design

**Date:** 2026-07-23
**Status:** Approved design, ready for implementation plan.

## Goal

Rework the webapp Synth mode into a sample-first ambient soundbath instrument
for the physical 5x5 patch-cable interface. The sound should lean into what
made clickbath appealing: multisampled instrument tones, simple musical note
selection, and one coherent global reverb/delay wash. RED POLE adds a richer
interaction model: up to 25 simultaneous patches, scan-derived fingerprints,
macro processing, and a conductor that makes a fixed patch ebb and flow over
time.

The design replaces the current Synth-mode trigger grid with a right-side macro
modifier grid. The right grid is not a sequencer in this pass.

## Current Findings

- The current webapp already uses Tone.js for Synth mode and vendored
  `webapp/vendor/tone.js` locally.
- `main.js` currently uses a 2x5 source grid (`pluck`, `pad`) and a 5x5 trigger
  grid (`pulse`, `half-time`, `bar`, `long`, `glacial`).
- `modifiers.js` still contains an earlier 5x5 modifier concept, but the
  current app no longer wires Synth-mode cables to those modifiers.
- clickbath's core sound is sample-first: it uses `Tone.Sampler` maps for real
  instruments, chooses musical note names, and sends both pads into big
  reverb/delay. Its pitch character comes mostly from sampler note triggering,
  not from pitch-shifting a single sample.

## Core Decisions

- **All 25 source cells are sample-based.** No Tone synth source cells in this
  pass.
- **Pitch is source-level sampler behavior.** Normal musical pitch comes from
  `Tone.Sampler` note triggering and multisample maps.
- **The right 5x5 grid is macro processing.** Each cell is a curated ambient
  macro using Tone-native strengths, not an attempt to recreate heavy Python DSP
  literally.
- **Delay and reverb are global.** One clickbath-style wash serves all voices.
- **A single optional global pitch shifter is allowed.** It sits before the
  global wash and defaults to zero semitones.
- **Color/BPM are a fingerprint.** They seed stable personality and variation
  for each voice instead of acting as obvious direct knobs.
- **The bath must evolve while cables are unchanged.** A conductor emphasizes,
  backgrounds, and revives voices over long cycles.

## Interaction Model

1. The visitor creates a source by sending a scan/color/BPM.
2. The source appears in the Sources list with a stable fingerprint.
3. Assigning the source to the left 5x5 grid chooses sample behavior and
   material.
4. Dragging a cable from that placed source to the right 5x5 grid chooses a
   macro modifier.
5. A source becomes audible after it is cabled to a macro.
6. Moving the cable changes the macro while preserving the source fingerprint.
7. Moving the placed source changes sample behavior/material while preserving
   the fingerprint; if the source already has a macro cable, rebuild the source
   voice and reconnect it to the same macro cell.
8. Removing a source releases the voice; the global wash tail continues to ring.

This keeps the physical meaning direct:

```
left grid cell = what sound is this?
right grid cell = how is this sound transformed?
scan fingerprint = who is this voice?
conductor = how does the ensemble breathe?
```

## Source Grid

The left array is a 5x5 sample voice palette. Rows define playback behavior.
Columns define material choices. All cells use `Tone.Sampler` and the
clickbath-derived/local sample bank.

| Row | Behavior | Column intent |
| --- | --- | --- |
| `pluck` | Sparse triggered tones with clean attacks and natural releases. | piano, guitar, tape guitar, tape bell, casio |
| `pad` | Held sampler notes with gentle attack/release and subtle breathing. | strings, flute, clarinet, casio, piano |
| `bloom` | Slow-attack sampler swells that appear and recede. | strings, flute, clarinet, tape bell, guitar |
| `bell` | Bright struck sampler tones, high-register bias, rare punctuation. | tape bell, casio, piano high, guitar harmonic-like, flute/clarinet bright |
| `drone` | Long-held or looped sampler tones with low/mid-register bias. | strings, casio, flute, clarinet, tape guitar |

Implementation starts with the column mappings shown in the table. Manual tuning
may reorder materials within a row if the mix balance is clearly better, but the
invariant is fixed: 5 rows x 5 columns, all sample-based, no synth-only cells.

## Modifier Grid

The right array is a 5x5 Tone-native macro palette. Row labels should describe
the perceptual result rather than low-level DSP algorithms.

| Row | Meaning | Tone.js building blocks |
| --- | --- | --- |
| `veil` | Soften, darken, blur, tuck behind the wash. | `Filter`, `EQ3`, `Chorus`, gentle gain trim |
| `shimmer` | Add quiet octave/fifth shadows and bright halos. | secondary sampler triggers, highpass/EQ, no per-voice `PitchShift` in the first implementation |
| `flutter` | Tape-like movement, tremble, slow animated tone. | `Tremolo`, `Vibrato`, `AutoFilter`, `Chorus` |
| `scatter` | Occasional fragments, recalls, and delayed sample echoes. | scheduled secondary sampler triggers, short `FeedbackDelay`, probability gates |
| `space` | Near/far/wide movement before the shared wash. | `Panner`, `AutoPanner`, `StereoWidener`, distance lowpass, wash send amount |

Columns increase or vary character, but they should be curated presets rather
than simple "more amount" ramps. For example, `shimmer III` can be a fifth
shadow while `shimmer V` can be a rare octave glint. `scatter I` can be almost
imperceptible, while `scatter V` can produce obvious but still sparse recalls.

The old row labels (`stretch`, `spectral`, `pitch`, `grainfx`, `spatial`) are
not used in the UI for this pass because they imply DSP that Tone.js only partly
supports. The new labels are honest about Tone.js strengths.

## Audio Graph

The intended graph is:

```
Sampler voice
  -> per-voice macro chain
  -> voice gain / pan / optional send shaping
  -> global transposition bus (optional PitchShift, default 0)
  -> global FeedbackDelay
  -> global Reverb
  -> Limiter
  -> Destination
```

The global transposition bus is a single `Tone.PitchShift`, not one per patch.
It is controlled by a global Transpose parameter, defaults to `0`, and should
ramp slowly when changed. Placing it before the delay/reverb lets the shifted
signal bloom naturally into the wash instead of pitch-shifting the entire reverb
tail after the fact.

The global delay and reverb keep the clickbath character:

- `Tone.FeedbackDelay` with high but bounded feedback.
- `Tone.Reverb` with long decay.
- Existing Reverb and Delay sliders remain global controls.
- Per-voice macros may set level, filtering, pan, or wash invitation, but they
  do not create per-voice reverb networks.

## Fingerprint Mapping

Each scan creates a stable fingerprint object:

```
{
  hue,
  sat,
  val,
  bpm,
  seed,
  harmonicBias,
  registerBias,
  brightnessBias,
  motionBias,
  densityBias
}
```

The fingerprint is subtle. It should make related scans feel related without
making the controls read like literal knobs.

- `hue`: harmonic lane, role weighting, register preference, brightness family.
- `sat`: presence, contrast, macro depth ceiling.
- `val`: openness, softness, wash invitation, perceived distance.
- `bpm`: motion personality, envelope times, swell periods, scatter likelihood,
  modulation rate ranges.
- `seed`: deterministic small variations, so the same scan produces a
  recognizable voice family.

Source and macro cells define the main audible identity. The fingerprint bends
that identity inside musically bounded ranges.

## Continuous Variation

The soundbath must not become a static stack of 25 loops. A conductor layer runs
even when the patch bay is unchanged.

### VoiceConductor

The conductor assigns slow-changing emphasis roles:

- `foreground`: present, clear, more likely to trigger or bloom.
- `midground`: audible but tucked.
- `background`: mostly texture and wash.
- `dormant`: nearly silent, eligible to return later.

Voice gains move over long cycles, roughly 20-90 seconds, with scan-seeded
variation. This keeps dense patches from becoming a flat wall.

### Source Event Variation

Each behavior has slow internal variation:

- `pluck`: sparse note events with changing probability.
- `pad`: held tones breathe in gain/filter and occasionally rearticulate.
- `bloom`: long attack/release cycles with scan-shaped timing.
- `bell`: rare high-register punctuation.
- `drone`: sustained foundation with slow loop crossfades or register changes.

### Macro Modulation

Each macro can drift within safe parameter ranges:

- `veil`: filter and chorus depth breathe.
- `shimmer`: shadow layer appears and recedes.
- `flutter`: rate/depth drift slowly.
- `scatter`: fragment probability changes over time.
- `space`: pan, width, distance, and wash invitation move gently.

## CPU Budget

The design is intended to support up to 25 simultaneous patches.

Allowed per voice:

- `Tone.Sampler`
- `Tone.Volume` / `Tone.Gain`
- `Tone.Filter` / `Tone.EQ3`
- `Tone.Panner` / `Tone.PanVol`
- light modulation nodes such as `Tremolo`, `Vibrato`, `AutoFilter`,
  `AutoPanner`, `Chorus`
- short feedback or fragment behavior only in selected macros

Avoid per voice:

- `Tone.Reverb`
- convolution
- long feedback networks
- heavy `PitchShift` on every voice
- live FFT/spectral processors

Use shared/global:

- delay
- reverb
- limiter
- optional pitch shift

## UI Controls

Keep existing controls and add one global pitch control:

- Play/Pause
- Root
- Reverb
- Delay
- Transpose, range `-12` to `+12` semitones, default `0`

The root control affects musical note selection and held-note behavior. The
Transpose control is a post-ensemble global effect and should be treated as a
performance gesture, not the normal source pitch path.

## Testing and Validation

Headless tests should cover deterministic logic:

- fingerprint derivation from hue/sat/val/BPM
- 25-cell source grid invariant and sample mappings
- 25-cell macro grid invariant and macro definitions
- conductor bounds, role assignment, and long-cycle gain changes
- source event probability ranges per behavior
- macro parameter ranges stay bounded

Browser/manual validation should cover audio behavior:

- 25 patches can be created and removed without obvious audio collapse.
- All source cells are sample-based and produce recognizable material.
- Cabled macros audibly differ without becoming harsh.
- Reverb and delay act globally.
- Global Transpose changes the whole bath and ramps smoothly.
- A fixed patch evolves over several minutes through emphasis, event, and macro
  variation.

## Risks and Mitigations

- **Tone.js does not provide true high-quality live spectral/stretch processors.**
  Mitigation: use honest macro labels (`veil`, `scatter`, `flutter`) and
  sampler-driven behavior instead of promising literal spectral DSP.
- **25 dense voices can still become a wall.** Mitigation: conductor roles,
  dormant states, bounded macro depths, and shared wash headroom.
- **Global PitchShift can color the entire mix.** Mitigation: default to `0`,
  ramp slowly, place before wash, and keep it optional.
- **Drone cells may expose short sample loops.** Mitigation: use long attack,
  crossfade/retrigger strategies, low levels, and the global wash to hide loop
  boundaries.
- **clickbath samples are not redistributed.** Mitigation: continue using local
  gitignored sample assets and document the preparation step separately.

## Out of Scope

- New non-sample Tone synth source cells.
- Reintroducing the Synth-mode trigger grid.
- True phase-vocoder spectral freeze.
- Per-voice reverb or per-voice long delay networks.
- Hardware finger-scan integration changes.
- TouchDesigner transport changes.
