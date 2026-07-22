# RedPole — Synth Mode Design Spec

**Date:** 2026-07-22
**Status:** Draft for review
**Scope:** Add a toggleable "synth" mode to the GitHub Pages web app, alongside
the existing "loop" mode, that turns each patch source into an evolving
tone-generator instead of an effect on one loaded loop.

---

## 1. Context — how loop mode works today

The web app (`webapp/`) is a fully static, three-thread pipeline:

```
main.js (UI)  →  worker.js (Pyodide + numpy)  →  worklet.js (audio thread)  →  speakers
```

- **One sound source:** `web_engine.WebEngine.loop_array` (a single loaded audio
  loop). `generate_block(frames)` reads it through `TapeModulator` to make the
  dry/base signal.
- **Patched sources are effects, not sound.** A "source" in `LayerRegistry` is a
  `{hue, sat, val, bpm}` tag. Connecting it to an effect-matrix cell creates a
  *layer* tagged with an `engine` (row) + `patch_row/col`. Every block,
  `generate_block` reads `registry.snapshot()` and routes the **same loop** into
  `microcosm` (microloop/granules/glitch/multidelay), `tape`, and `reverb`.
- Output = `dry_gain*base + wet_gain*wet`, bounded by `wet_bus` + `RmsLimiter`.
- **A crowd/density spine already exists:** `crowd.CrowdState.from_layers()` and
  `crowd.EntryGestureTracker` already drive count-dependent behavior, and
  `wet_bus`/`reverb` already scale with layer count.

## 2. Goal

A second mode where **each output jack generates its own tone**, the finger
scan **shapes that tone**, and the tone is **patched into an effect**. The
collective sound must **evolve as more people interact** — an ambient soundscape,
not a song with parts.

## 3. Aesthetic target

Reference feeling: **ASUNA — *Relief / 100 Keyboards*** (massed detuned tones,
beating/interference), **Carl Stone — *Shing Kee*** (looped fragment phasing),
**William Basinski — *dlp 1.1.1*** (slow suspension, degradation). Common thread:
**evolution is emergent, not authored** — voices accumulate and interfere.

**The arc:** empty room = one fragile, slowly-stretched tone; full room = a vast,
slow, shimmering wash that never quite repeats.

## 4. Core principle

The evolving quality is **not a per-jack feature** — it is an emergent property of
how voices interact, driven by crowd density. Synth mode hangs its evolution on
the **existing `crowd.density` spine**. The three chosen mechanisms:

1. **Beating / interference** — voices cluster near a shared tonal center,
   micro-detuned; density thickens the shimmer.
2. **Time suspension** — density deepens time-stretch (grains + a new spectral
   stretch): the room gets more cavernous as the crowd grows.
3. **Phase-drift lattice** — each voice loops at a slightly different length, so
   accumulating voices slide against each other and never repeat.

## 5. Mode toggle

- A **Loop ↔ Synth** switch in the UI (`main.js` + `index.html`).
- **Switching modes resets the patch bay**: disconnect + remove all sources,
  clear cables, flush the audio buffer. The two modes mean different things by a
  "source", so state is not carried over.
- `worker.js` gains a `set_mode` message; `WebEngine` gains a `mode` field
  (`"loop"` default | `"synth"`).

## 6. Sound model (substrate C — wavetable / seed-tone hybrid)

### 6.1 Seed bank
A small bank of spectrally-rich **seed tones**, synthesized **once at load** into
buffers (single-cycle wavetables and/or short generated textures). Generative and
tiny — no shipped audio assets. Rich enough that stretch/granular have material to
work on (unlike pure sine oscillators).

### 6.2 Per-voice rendering (each connected jack)
- Voice = **a seed + a pitch**, rendered as a short looping buffer.
- **Pitch:** drawn from a **fixed consonant drone pitch-set** (root + consonant
  partials/octaves in one mode), assigned by join-order / grid slot — *not* from
  color. Voices fill the drone in as they arrive (registral spread), always
  consonant. Each voice is **micro-detuned a few cents** → beating.
- **Loop length per voice** is slightly different → phase-drift lattice.
- **Color → timbre** (TUNABLE, see §10): hue selects the seed / wavetable
  position; sat + val set brightness (filter) + stereo spread.
- **BPM → slow motion**, not a beat: swell / drift / grain rate.

### 6.3 Effect stage (reused)
The voice is fed into the engine of its patched matrix cell
(`microloop/granules/glitch/multidelay/tape/reverb`) — the **existing processor
classes**, reused. Voices are summed after their effects, then the master bus
(`wet_bus` + limiter + master stretch/reverb) is applied.

## 7. Collective evolution (density spine)

As `crowd.density` rises:
- **Stretch deepens** — longer grains + longer spectral-stretch window → suspension.
- **Spectral bloom** — shared filter opens, reverb size + tail grow (extend the
  existing `wet_bus`/`reverb` count-scaling).
- **Detune spread + phase-drift** thicken naturally as voices accumulate.
- Each **arrival fires an `EntryGesture`** swell that settles into the bed
  (reuse `EntryGestureTracker`).

## 8. New DSP block

**One genuinely new processor:** a **PaulXStretch-style spectral stretch**
(FFT / phase-vocoder smear with randomized phase) usable per-voice and/or on the
master bus, its window/stretch factor driven by density. Everything else is
orchestration + reuse.

## 9. Implementation touchpoints

- **`web_engine.py`** — add `mode`; branch `generate_block`. The central refactor:
  **the effect stage must accept a per-voice source buffer** instead of always
  reading the single `self.loop_array`. Loop mode = all layers share `loop_array`
  (current behavior); synth mode = each layer processes its own rendered seed
  voice. **RISK / to confirm during planning:** `MicrocosmProcessor.process` and
  `TapeModulator.process` currently assume one shared array — audit how much they
  must change to take per-voice material.
- **New `synth_source.py`** (name TBD) — seed bank, wavetable synthesis, per-voice
  rendering, drone pitch-set, detune, per-voice loop length.
- **New `spectral_stretch.py`** — the PaulXStretch-style processor.
- **`layers.py`** — sources already carry hue/sat/val/bpm; add per-voice synth
  fields (seed id, pitch, loop length) populated on connect in synth mode.
- **`worker.js`** — add `set_mode`; on mode change, reset registry + flush.
- **`main.js` / `index.html`** — mode toggle UI; hide loop-only controls
  (Load Loop) in synth mode; reset patch bay on toggle.
- **`worker.js` `PYTHON_FILES`** — add the new modules so Pyodide fetches them.

## 10. Open / tunable after testing

- **Color → timbre** is the starting mapping; may move to touch pitch after the
  user hears it. Keep the color→parameter mapping in one small, swappable place.
- Drone pitch-set (root, mode, how partials are chosen) — pick a sensible default,
  expect to retune by ear.
- Whether spectral stretch runs per-voice, master-only, or both.

## 11. Out of scope (YAGNI)

- Explicit chord/progression generation (deliberately dropped — texture, not
  harmony).
- Multi-key / scene changes, presets, saving state.
- Any firmware / TouchDesigner changes — this spec is web-app only.
- Rhythmic/beat-synced material.

## 12. Testing

- Reuse the desktop `pytest` harness where the DSP is shared. New modules
  (`synth_source`, `spectral_stretch`) get unit tests: seed determinism, voice
  buffer shape/length, detune spread, stretch output length vs factor.
- Manual: `rtk npx serve .` from repo root, exercise the mode toggle, verify
  reset-on-switch, and listen for the arc (1 voice → many).
```
