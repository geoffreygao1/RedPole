# RedPole Synth Control and Performance Design

**Date:** 2026-07-22
**Status:** Approved for implementation
**Scope:** Improve Synth mode controls, sound variation, scan-to-sound mapping,
and dense-voice browser performance.

## Goals

- Replace the Loop/Synth two-button mode control with a clearer pill switch.
- Make scan parameters audibly direct:
  - BPM controls voice loop length and space between tone events.
  - Hue controls tone family / harmonic role.
  - Saturation controls motion and complexity.
  - Value controls filter brightness and attack/presence.
- Add selectable synth tone families: scan-driven mix, Rhodes-like, pad-like,
  piano-like, and pure drone.
- Add selectable harmony modes for auditioning ambient pitch worlds: open
  ambient, Lydian add9, minor 9, and sus cluster.
- Keep dense synth patches playable by budgeting the expensive wet/effect path
  after roughly 10 voices while keeping the dry bed audible.

## Design

`synth_source.py` gets one explicit mapping point:
`voice_params_from_scan(hue, sat, val, bpm, tone_mode, harmony_mode)`. It returns
the voice family, brightness, motion, loop length, event duty, attack, and
release. `SynthVoiceBank` uses these values when rendering per-voice buffers.

Harmony mode changes pitch assignment through `drone_pitch_hz(order, mode)`.
`open` keeps the current non-chord palette. `lydian_add9`, `minor9`, and
`sus_cluster` use fixed ambient pitch sets that repeat across registers without
climbing into a chord-builder ladder.

`WebEngine` stores `tone_mode` and `harmony_mode`, exposes
`set_synth_options(...)`, and forwards options to `SynthVoiceBank`. In Synth
mode, it limits heavy wet processing to a rotating subset once the patch count
passes the voice budget. The dry bed still includes all voices, density-trimmed.

The web UI adds a pill Loop/Synth switch plus compact Tone and Harmony selects.
Changing Tone/Harmony sends `set_synth_options` to the Worker without clearing
sources.

## Testing

Python tests cover scan mapping, pitch modes, option switching, and wet budget
selection. Static web tests cover the switch/select UI and Worker messages.
