# RedPole Audio Prototype - GUI Cleanup & Wet-Bus Organization

## Purpose

This pass cleans up the prototype controls now that reverb is an assignable
engine, and adds density-aware wet-bus management so many inputs can evolve
the source instead of masking it with mud.

The priority is not to correct each person's layer into a stricter musical
system. Individual tape, spectral, granular, and reverb behaviors should
remain expressive. The new behavior should organize the combined result
after those layers meet on the wet bus.

This design amends the existing Round 3 design. Existing uncommitted spectral
pitch snapping work should be preserved.

## GUI Changes

The Scan Input panel should contain controls that define the next sent layer:

- load loop and playback controls
- finger color picker
- BPM
- engine selection
- Send

The Reverb slider is removed. Reverb amount and character now come from
layers assigned to the `reverb` engine, so a global slider is redundant and
confusing.

Wet/Dry remains a global A/B audition control on `AudioEngine.wet_dry`, but it
moves outside the Scan Input panel. It should appear after the send/layer
area, visually separated from per-layer scan controls.

The live-analysis toggle is also global runtime state, not per-layer scan
data. It should move with the audition controls near Wet/Dry if it remains in
the GUI.

## Adaptive Wet Bus

Add a shared wet-bus management stage in `AudioEngine.generate_block`, after
spectral/granular wet generation and before final wet/dry mixing.

Density is derived from active contributors:

- spectral layers count as wet voices
- granular layers count as wet voices
- reverb layers count toward room-density shaping, but add no direct signal
- tape layers are base/source contributors and do not count as wet voices

The wet-bus manager applies three coordinated controls:

1. Wet gain trim: as wet voice count rises, reduce additive wet level gently.
   All inputs still contribute, but 20+ inputs should not dominate the source.
2. Tone cleanup: apply lightweight low-frequency/low-mid attenuation to the
   wet bus, increasing with wet density. A simple first-order high-pass plus
   a gentle low-mid trim is enough; this targets mud without relying on the
   final limiter.
3. Reverb density control: as wet and reverb density rises, tighten reverb by
   reducing effective feedback and darkening the tail. Explicit reverb layers
   still shape the room, but the room should not accumulate into a long
   uncontrolled wash.

The existing RMS limiter remains as the final safety stage for sustained wet
energy. It should no longer be the primary tool for making dense input sets
sound organized.

The implementation should keep this logic in a small helper, such as
`wet_bus.py` or focused functions in `modulation.py`, so `audio_engine.py`
does not absorb a large block of tuning code.

## Signal Flow

The intended additive-mode flow becomes:

1. Split layers by engine.
2. Generate the base/source path from dry loop plus tape layers.
3. Generate spectral and granular wet signals.
4. Shape shared reverb character from reverb layers and density.
5. Run the wet signal through adaptive wet-bus management.
6. Apply wet-bus reverb using the managed room settings.
7. Apply the existing RMS limiter as final wet safety.
8. Blend with the base using `wet_dry`.
9. Soft-clip the final output.

Zero-layer output must remain exact dry playback. Reverb-only layers shape the
room but add no signal when no spectral or granular wet input exists.

## Testing

Tests stay device-free and deterministic.

- GUI code should no longer define or reference `reverb_var`.
- Wet/Dry still updates `engine.wet_dry` after being moved outside Scan Input.
- Zero-layer output remains exact dry in `mixed`, `spectral`, and `granular`.
- With many spectral/granular layers, wet-bus RMS stays bounded without
  depending only on hard clipping.
- Wet-bus cleanup measurably reduces low-frequency or low-mid wet energy as
  density rises.
- Reverb layer shaping still affects room character, while density prevents
  excessive tail accumulation.
- `wet_dry=0` still produces dry/base only.
- `wet_dry=1` still produces wet only.
- Existing spectral harmonic snapping tests remain valid.

## Out Of Scope

- Key detection or source-key quantization.
- Hard caps that silence later inputs.
- Rewriting the individual tape, spectral, granular, or reverb engines.
- Hardware integration or changes to TouchDesigner assets.
