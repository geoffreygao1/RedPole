# RedPole Synth Tuning and Performance Design

**Date:** 2026-07-22
**Status:** Approved for implementation
**Scope:** Retune synth mode so multiple voices form a calm ambient bed instead
of a bright constant chord stack, and add guardrails for many loaded voices.

## Problem

The current synth mode assigns slots to an octave/fifth overtone ladder:
`1, 1.5, 2, 3, 4, 6, 8, 12`. As more sources are patched, every voice reinforces
the same harmonic stack and stays audible on the dry bus. The result reads as
a chord builder with bagpipe-like constant tone rather than a soothing,
emergent wash. Browser performance also becomes fragile when many voices are
active because all voices are always rendered dry and the wet path is active
for the whole dense stack.

## Design

Retune synth mode around a deterministic voice palette rather than an upward
chord ladder. Voices should include near-unisons, slow beating neighbors,
occasional harmonic anchors, and a few soft neighboring ratios. The palette
stays mostly in a restrained low/mid register and does not monotonically climb
as slots fill.

Soften each seed voice at the source. Reduce upper-harmonic emphasis, apply a
small brightness-controlled low-pass during rendering, and add a slow amplitude
breath so the dry source is never a fixed reed-like tone.

Reduce dry dominance as the room fills. The dry mix remains audible for one
voice, but density trims it so the full-room sound is carried more by the wet
wash than by many exposed oscillators.

Add automated guardrails for the new behavior: pitch palette tests should prove
the first voices are not a monotonic chord ladder, source tests should prove the
rendered voice has slow amplitude motion, and engine tests should prove dense
synth output has lower dry RMS than a naive constant stack while staying bounded.

## Out of Scope

This does not add new UI controls, stereo output, shipped audio assets, or a
new synth architecture. Manual listening will still be needed after the code
change to choose final musical taste.
