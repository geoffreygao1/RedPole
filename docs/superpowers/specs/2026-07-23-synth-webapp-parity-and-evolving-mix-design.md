# Synth Web-App Parity + Evolving Mix + Live Root Slider — Design

**Date:** 2026-07-23
**Status:** Approved design, ready for implementation plan.

## Goal

Three changes to the desktop app's **Synth** tab and the soundscape engine, driven by
user feedback while tuning by ear:

1. **Match the GitHub-Pages web app workflow.** The synth tab should use the web app's
   *Send → Sources list → assign a source onto a generator jack → cable that generator to
   a modifier* flow, with **single-use sources** (one scanned color = one voice, no
   reusing the same color for unlimited patches) and an explicit **Play/Pause** button.
2. **Make the soundscape ebb and flow** instead of a constant wall of sound. Voices should
   slowly fade in/out and swap foreground/background roles over time — *gentle and slow*
   (swells over tens of seconds). Especially important as voice count grows.
3. **Turn the harmonic root into a live slider** that re-pitches currently-sounding tonal
   voices in real time, **gliding smoothly** to the new pitch (no clearing patches).

## Background

The web app (`webapp/main.js` + `index.html`) models a finger scan as a first-class
**source**: pick color+BPM → **Send** creates a source (locked-in color+BPM) that appears
in a **Sources** list → the user assigns it to a slot in the left grid → drags a cable from
that slot's jack to an effect jack in the right grid. Each slot holds one source; a source
is used once. There is an explicit **Play/Pause** button.

The current desktop synth tab (`synth_tab.py`) skips that entire front half. Its two 5×5
grids are *generator-type presets* (left) and *transform presets* (right); the user drags a
generator jack straight to a transform jack, and the picker color is merely read at
connect-time — so the same color can seed unlimited voices, and there is no Send step, no
Sources list, and no Play/Pause button (playback is implicitly tied to tab focus).

On the engine side, `SoundscapeEngine.generate_block` (`soundscape_engine.py`) plays every
non-dormant voice continuously at a fixed `ROLE_GAIN`, with roles assigned statically from
connect order — hence the "wall of sound." `soundscape_density.event_probability()` already
exists but is never called. `HarmonicField.root_midi` is fixed at construction, and
`SynthAudioEngine.set_root_midi()` rebuilds the whole engine (clearing all patches), which
is why changing the root today is destructive.

Two facts that make the glide feasible: `AdditiveDroneSource` and `ResonantPulseSource`
both keep oscillator/resonator state across blocks and recompute frequency from
`assignment.midi` **each block**, so shifting `assignment.midi` block-to-block produces a
smooth glide. The pitch-independent sources (granular/noise/texture) ignore
`assignment.midi`, so they simply won't shift — musically correct.

## Scope

**In scope:**
- Rewrite the `SynthTab` widget interaction to the web-app workflow: Scan Input with a
  **Send** button, a **Sources** list panel, assignment of sources onto generator jacks,
  cabling a placed generator jack to a modifier jack, single-use sources, and a
  **Play/Pause** button.
- New `soundscape_conductor.py`: a `VoiceConductor` that produces slowly-evolving per-voice
  gains (fade + role rotation), integrated into `SoundscapeEngine.generate_block`.
- Live, gliding harmonic root in `SoundscapeEngine` + `SynthAudioEngine`, exposed as a
  slider in the synth tab (replacing the combobox + "Apply (clears patches)").
- `SoundscapeEngine.set_patch_transform()` so a placed voice's modifier can be set/cleared
  without recreating the patch.
- Small `gui.py` change so entering the Synth tab no longer force-resumes audio (the new
  Play/Pause button owns synth playback).
- Unit tests for all new pure logic (conductor, engine glide, `set_patch_transform`, and
  any extracted tab-state helpers).

**Out of scope / unchanged:**
- Loop tab audio and UI.
- Source/transform DSP engines themselves (no preset retuning here — that is the separate
  "tune by ear" task).
- The producer-thread audio lifecycle and Tk-canvas waveform (already landed).
- Hardware finger-scan input, TouchDesigner, web/Pyodide.
- The web app itself (it is already the reference; no changes).

## Component 1 — Web-app workflow in the synth tab (`synth_tab.py`)

### Model

Introduce a client-side **source** distinct from an engine **patch/voice**:

- A **source** is a captured scan: `{client_id, hue, sat, val, bpm, color_hex}`. Created by
  **Send**. Lives in the Sources list. No sound yet (not an engine patch).
- A **voice** is created when a source is *assigned* onto a generator jack. It holds
  `{pid, source_cell, transform_cell, color_hex, bpm, source_id, transform_id}` where `pid`
  is the `SoundscapeEngine` patch id. Assigning consumes the source (removed from the list).

Extract the non-Tk state transitions into a pure, unit-testable helper class
`SynthPatchModel` (in `synth_tab.py`), holding the sources dict, the voices dict, and the
generator-jack occupancy map. The Tk widget calls into it and re-renders from its state.
This keeps the widget thin and the logic testable without a display.

### Layout (mirrors the web app's sections)

Left control column:
- **Transport:** a **Play/Pause** button.
- **Scan Input:** the finger-color picker + BPM entry + swatch + **Random** + **Send**.
- **Harmonic root:** a slider (Component 3).
- **Load Sample…** (unchanged).

Center: the patch-bay `Canvas` — left grid = **generator** jacks
(`SYNTH_SOURCE_ROWS`), right grid = **modifier** jacks (`SYNTH_TRANSFORM_ROWS`), same
geometry helpers as today.

Right/under: a **Sources** list (swatch + `"<bpm> BPM"` + Remove ×) and the waveform strip.

### Interaction

1. **Send** (`_on_send`): read current HSV + parsed BPM → create a source with a fresh
   `client_id` → add to the Sources list. Enforce a combined cap of `SYNTH_PATCH_LIMIT`
   over (unplaced sources + active voices); refuse with an info dialog when full.
2. **Assign a source to a generator jack:** two gestures, mirroring the web app —
   - click a source row to *select* it, then click a generator jack; or
   - drag a source row onto a generator jack.
   On assign:
   - If that generator jack is already occupied by a voice, **replace** it: disconnect the
     old voice (`engine.disconnect_patch(old_pid)`) and drop it.
   - `pid = engine.connect_patch(hue, sat, val, bpm, source_preset=<generator id>,
     transform_preset=None)` → a source-only voice that sounds immediately (if playing).
   - Record the voice; **remove the source from the Sources list** (single-use).
   - The generator jack now shows the source's color.
3. **Cable a placed generator jack → modifier jack** (same press/drag/release gesture as
   the Loop bay): on release over a modifier jack, `engine.set_patch_transform(pid,
   <transform id>)` and set `voice.transform_cell`. Releasing a placed jack's cable off the
   modifier grid clears the transform (`set_patch_transform(pid, None)`), returning the
   voice to source-only. Draw the cable in the voice's color.
4. **Remove a voice:** `engine.disconnect_patch(pid)`; free its generator jack. (Reuse the
   active-voice list rows' Remove button; a removed voice does **not** return to the
   Sources list — a new scan is required, per single-use.)
5. **Play/Pause** (`_on_toggle_play`): toggle `synth_engine.resume()` / `synth_engine.pause()`
   inside try/except (device-open errors → dialog). The button label reflects
   `synth_engine.paused`; the existing 50 ms refresh loop keeps the label in sync when the
   tab is re-shown.

### `gui.py` change

`_on_tab_changed` currently force-resumes the synth engine on entering the Synth tab.
Change it to: still pause the Loop engine on entry and pause the synth engine on exit, but
**do not auto-resume** the synth — the tab opens paused (silent) and the user presses Play.
This matches the web app (starts on Play) and prevents the button label from lying.

## Component 2 — Evolving mix conductor (`soundscape_conductor.py`, new)

A `VoiceConductor` replaces the static `assign_voice_roles(self._connect_order)` +
fixed-`ROLE_GAIN` logic in `generate_block`, producing a smooth, slowly-evolving per-voice
gain that both **fades voices in/out** and **rotates which voices are foreground**.

### Mechanism

- Track elapsed time in seconds (`self._t`), advanced by `frames / samplerate` per block.
- Each voice id gets a deterministic slow **activity LFO** derived from a seeded RNG keyed
  by id: `rate` such that the period is in **[20 s, 50 s]** (gentle & slow), plus a random
  `phase`. `activity(vid, t) = 0.5 + 0.5·sin(2π·(t·rate + phase))` ∈ [0, 1].
- Each block, **rank** active ids by current activity (descending) and feed the ranked list
  to the existing `assign_voice_roles` to get `{vid: role}` — so foreground membership
  rotates organically as activities cross, while respecting the existing budgets.
- Target per-voice gain = `ROLE_GAIN[role] · (SWELL_MIN + SWELL_DEPTH·activity)`, with
  `SWELL_MIN = 0.35`, `SWELL_DEPTH = 0.65` (voices ebb toward ~0.35× but rarely vanish —
  matches "gentle," "individual voices rarely fully disappear").
- **One-pole smooth** each voice's gain toward its target with a time constant ≈ **0.6 s**
  (coefficient derived from block size / samplerate) so role changes and swells never click
  (zipper-free). Smoothing state is kept per vid.
- GC per-voice state (LFO params + smoothed gain) for ids no longer active, via the same
  `sync_voices`/active-id pattern used elsewhere.

Return `{vid: gain}`. `generate_block` uses it as
`mix += voice * conductor_gain[vid] * voice_gain`, keeping the existing density scaling
`voice_gain = 1/sqrt(n)` on top so total level stays bounded, followed by the existing
`RmsLimiter` + `soft_clip`.

The conductor is fully deterministic given `(seed, samplerate)` and its inputs, so it is
unit-testable by driving synthetic time.

### Notes

- `event_probability()` stays unused for now — the chosen approach is the "Evolving mix"
  option, not "Rhythmic events." Left in place for a future rhythmic mode.
- `_connect_order` is no longer needed for role assignment; keep the list (cheap) but the
  conductor is the source of roles.

## Component 3 — Live root slider with glide (`soundscape_engine.py`, `synth_audio_engine.py`, `synth_tab.py`)

### Engine

- `SoundscapeEngine` gains a continuous, glide-smoothed root:
  - `self._root_target` and `self._root_current` (floats, semitones), both initialized to
    `root_midi`.
  - `set_root(target_midi)` sets `_root_target` (clamped to the slider range).
  - In `generate_block`, **before** rendering: one-pole glide
    `_root_current += k·(_root_target − _root_current)` with `k` chosen for a ≈ 0.4 s glide
    at the current block size, then set `self.field.root_midi = _root_current`.
  - For each active voice, **re-derive** its pitch from the smoothed root while keeping the
    role/octave/detune the allocator chose:
    `assignment.midi = _root_current + ROLE_SEMITONES[role] + 12·octave + detune_cents/100`.
    (`assignment` already stores `harmonic_role`, `octave`, `detune_cents`.) This shifts all
    tonal voices in parallel; additive/resonant voices glide via their block-to-block
    frequency recompute; pitch-independent sources are unaffected.
- Keep `set_root_midi()` (engine rebuild) for compatibility, but the tab no longer calls it.

### `SynthAudioEngine`

- Add thread-safe `set_root(target_midi)` (locks, calls `engine.set_root`).
- `root_midi` property returns the current target (rounded for display).

### Tab

- Replace the "Harmonic root" combobox + "Apply (clears patches)" with a **slider**
  (`ttk.Scale`) over the full `ROOT_NOTE_CHOICES` MIDI range (48–84, C3–C6), showing the
  current note label. `command` callback calls `synth_engine.set_root(value)` live. No
  patch clearing. Optionally snap the displayed label to the nearest semitone while the
  underlying target stays continuous.

## Data flow (after changes)

```
picker+BPM ──Send──▶ Sources list (client-side sources, single-use)
   │
   └─assign onto generator jack─▶ engine.connect_patch(color,bpm,source,transform=None)  → voice (pid)
                                   │
     cable generator→modifier ────┴─▶ engine.set_patch_transform(pid, transform_id | None)

root slider ──▶ SynthAudioEngine.set_root ──▶ SoundscapeEngine._root_target
                                              (glides _root_current, re-pitches tonal voices/block)

generate_block: VoiceConductor.update(active_ids, dt) → per-voice evolving gains
                mix += voice · conductor_gain · (1/√n) → RmsLimiter → soft_clip
```

## Testing strategy

- **`VoiceConductor`** (pure): gains vary over time; foreground membership rotates as
  activities cross; gains stay within `[0, ROLE_GAIN_max]`; smoothing bounds per-block gain
  change (no jumps); state is GC'd for disappeared ids; deterministic under a fixed seed.
- **Engine glide:** after `set_root(target)`, running blocks moves `field.root_midi` toward
  target (one-pole, monotonic, converges); a tonal voice's `assignment.midi` shifts by the
  same delta while `harmonic_role`/`octave`/`detune_cents` are unchanged; changing root does
  not add/remove patches.
- **`set_patch_transform`:** sets and clears `transform_preset` on an existing patch without
  changing its id or source; unknown pid is a no-op.
- **`SynthPatchModel`** (extracted pure tab state): Send adds a source; assign consumes the
  source and creates a voice on the target generator jack; assigning onto an occupied jack
  replaces (old pid marked for disconnect); combined source+voice cap enforced;
  cable-to-modifier and cable-off map to the right `set_patch_transform` calls; remove frees
  the jack.
- Reuse existing pure geometry-helper tests unchanged.

## Risks / mitigations

- **Zipper noise on root glide** — block-granularity frequency stepping (≈46 ms/block).
  Mitigated by the ≈0.4 s one-pole glide (many small steps); additive/resonant track phase
  continuously. If audible, shrink block size is out of scope; accept for prototype.
- **Transform state reuse when retargeting** — `set_patch_transform` reuses the transform
  engine's per-vid state across a preset change, which may briefly glitch. Acceptable for a
  prototype; documented.
- **Play/Pause vs tab-switch handoff** — resolved by making the tab own synth playback and
  the tab-switch only pause (never resume) the synth engine.
