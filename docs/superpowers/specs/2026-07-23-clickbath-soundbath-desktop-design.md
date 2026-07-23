# Clickbath-Style Soundbath in the Desktop Synth — Design

**Date:** 2026-07-23
**Status:** Approved design, ready for implementation plan.

## Goal

Bring the pleasing "soundbath" character of the *clickbath* project
(https://github.com/hamishlang/clickbath) into our desktop Synth tab
(`SoundscapeEngine`). Clickbath's charm is **multisampled real instruments**
(piano, guitar, casio, strings, flute, clarinet, tape bell/guitar) whose gentle
notes ring out into a **big long-tail reverb + feedback delay**. We add that to
our synth while keeping our richer harmonic brain (`HarmonicField`), the
evolving-mix conductor, the live root slider, and the web-app workflow.

## Decisions (from brainstorming)

- **Note behavior: hybrid.** Instruments can be *plucked/triggered* (sparse
  notes with long release) or *sustained* (pads / slow blooms).
- **Samples: clickbath's own assets** (kept out of git), multisampled properly
  (all register files per instrument, nearest picked and lightly resampled — no
  single-file stretch artifacts).
- **Grid: stays 5×5.** Instruments live in the **columns**; **rows carry the
  behavior**. `noise` and `additive` are dropped from the grid to make room;
  `granular` and `resonant` stay (they are "slightly rhythmic"). **`resonant`
  is slowed** (sparser pulses).
- **Controls: global Reverb + Delay sliders** driving one master wash on the
  synth output.
- **No nature/ambient beds** in this pass.

## Environment findings (de-risked)

- `soundfile` here is **libsndfile 1.2.2, which decodes MP3**, so clickbath's
  mp3s load directly; no ffmpeg is present. We convert them to 44.1 kHz mono
  **WAV once at download** for fast, robust startup.
- Clickbath uses **C4 = MIDI 60** (Tone.js default), the same convention as our
  `_midi_label`. Verbatim note→file maps (baseUrl `assets/`):
  - **piano** — C6 `piano 1`, C5 `piano 2`, C4 `piano 3`, C3 `piano 4`
  - **guitar** — C5 `guitar3`, C4 `guitar2`, C3 `guitar1`
  - **tapeguitar** — C4 `tapeguitar3`, C3 `tapeguitar2`, C2 `tapeguitar1`
  - **tapebell** — C6 `tapebell4`, C5 `tapebell3`, C4 `tapebell2`, C3 `tapebell1`
  - **casio** (clickbath `casioStrings`) — C6 `casio2 1`, C5 `casio2 2`, C4 `casio2 3`, C3 `casio2 4`
  - **strings** (clickbath `strings2`) — C6 `strings2-4`, C5 `strings2-3`, C4 `strings2-2`, C3 `strings2-1`
  - **flute** — C6 `flute 1`, C5 `flute 2`, C4 `flute 3`
  - **clarinet** — C6 `clarinet3`, C5 `clarinet2`, C4 `clarinet1`
  - (`casio3`, `casio1`, `casio4` exist but are unused.)
  - MIDI: C2=36, C3=48, C4=60, C5=72, C6=84.

## Resolved source grid (5 rows × 5 columns)

| Row | Behavior | col I | col II | col III | col IV | col V |
|----|----------|-------|--------|---------|--------|-------|
| 1 | `granular` (kept) | 5 existing granular variants ||||| 
| 2 | `resonant` (kept, **slower**) | 5 existing resonant variants, sparser pulses ||||| 
| 3 | `pluck` (triggered) | piano | guitar | tapeguitar | tapebell | casio |
| 4 | `pad` (sustained) | strings | flute | clarinet | casio | piano |
| 5 | `bloom` (slow swell) | strings | flute | clarinet | guitar | tapebell |

All 8 instruments appear; several appear under more than one behavior (distinct
presets, one shared sample bank). Connecting voices across rows layers them into
"a mixture of many tones."

## Scope

**In scope:**
- Download + convert clickbath instrument assets into gitignored
  `audio_prototype/assets/clickbath/`.
- New `soundscape_instruments.py`: an `InstrumentBank` + `InstrumentSource`
  (multisample playback, three behaviors: `pluck`, `pad`, `bloom`).
- Restructure the synth **source** grid rows/presets to
  `(granular, resonant, pluck, pad, bloom)` with instruments in columns; wire
  `InstrumentSource` into `SourceBank`.
- Slow the `resonant` source (sparser pulses).
- New `soundscape_wash.py`: a global `SoundscapeWash` (reverb + feedback delay),
  integrated into `SoundscapeEngine.generate_block`; thread-safe
  `set_reverb`/`set_delay` on `SynthAudioEngine`.
- **Reverb** and **Delay** sliders in the synth tab; instrument names shown as
  the column labels of the instrument rows.
- Unit tests for all new pure logic.

**Out of scope / unchanged:**
- The modifier (transform) grid, evolving-mix conductor, live root slider,
  Play/Pause, Send/Sources workflow.
- The web app / `web_engine.py` path (it already has its own sample soundbath).
- `additive`/`noise`/`texture` source *classes* stay in the file (untouched, to
  avoid breaking their tests) but are removed from the synth grid. The **Load
  Sample** button is removed from the synth tab (own-sample support deferred).
- Nature/ambient beds; hardware; TouchDesigner.
- Redistributing the samples (they stay gitignored).

## Component 1 — Assets (`assets/clickbath/`, gitignored)

A one-time preparation step (run before implementation, not a runtime path):
download the 8 instruments' register files from clickbath `main`
(`raw.githubusercontent.com/hamishlang/clickbath/main/static/<file>.mp3` — note
the space-containing names are URL-encoded), decode with `soundfile`, downmix to
mono, resample to 44.1 kHz, and write `assets/clickbath/<instrument>_<midi>.wav`
(e.g. `piano_84.wav`). Add `audio_prototype/assets/clickbath/` to `.gitignore`.

The note→file maps above are **baked into `soundscape_instruments.py`** as a
constant keyed by instrument → `{midi: filename}`; `InstrumentBank` loads
whatever WAVs are present at construction. **If the folder or a file is missing,
that instrument loads empty and renders silence** — so tests and a fresh clone
run without the assets.

## Component 2 — `soundscape_instruments.py` (multisample instruments)

**`InstrumentBank(samplerate, assets_dir=None, seed=None)`**
- On init, for each instrument in the baked map, load each present WAV into a
  cache `{instrument: {midi: np.ndarray}}` (mono float64, normalized once).
- `nearest(instrument, midi) -> (sample, source_midi) | None`: the loaded
  sample whose mapped MIDI is closest to `midi` (None if instrument empty).

**`InstrumentSource(bank, samplerate, seed=None)`** — one of the `SourceBank`
engines. `render(vid, preset, assignment, bpm, frames)` where `preset` carries
`instrument` and `behavior`:
- Pitch: pick `nearest(instrument, round(assignment.midi))`; playback rate =
  `midi_to_hz(assignment.midi) / midi_to_hz(source_midi)` (linear resample,
  reuse the interpolation style already in the codebase). Per-voice read
  position persists across blocks.
- **`pluck`** (triggered): a BPM-derived, probabilistic sparse trigger (reuse
  the `resonant`/`event_probability` idea — one onset every few beats, jittered)
  starts a one-shot playthrough of the sample with a fast attack and a **long
  exponential release**; silent between notes (the wash fills the gaps).
- **`pad`** (sustained): the sample loops continuously with a slow amplitude
  breathing envelope; smooth loop wrap (short crossfade) to avoid clicks.
- **`bloom`** (slow swell): like `pad` but with a very slow attack and a long
  release when re-triggered on a slow clock; the "appearing/receding" swell.
- Color (`assignment`/timbre via `calibrate_color`) may lightly shape gain and a
  one-pole tone tilt; keep subtle.
- Output is a bounded mono block; per-voice state GC'd via `sync(active_ids)`.

## Component 3 — Source grid restructure (`soundscape_sources.py`, `synth_tab.py`)

- Add an `instrument` engine to `SOURCE_PRESETS`, producing 15 presets grouped
  into rows `pluck`/`pad`/`bloom` (5 each) per the grid table, each with fields
  `{"id", "engine": "instrument", "row": <behavior>, "instrument", "behavior"}`.
- Give `granular`/`resonant` presets a `"row"` equal to their engine name.
- `SYNTH_SOURCE_ROWS = ("granular", "resonant", "pluck", "pad", "bloom")`.
  Group presets into the 5×5 grid **by the `"row"` field** (not `"engine"`), so
  `source_preset_id(row, col)` returns the right preset id. Keep the 25-cell
  invariant (5 granular + 5 resonant + 15 instrument = 25).
- `SourceBank`: instantiate `InstrumentBank` + `InstrumentSource` alongside the
  existing engines; dispatch `engine == "instrument"` to `InstrumentSource`.
  `additive/noise/texture` instances remain but are unreferenced by the grid.
- `synth_tab.py`: instrument rows show the **instrument name** per column
  instead of the generic `I–V` variant label; `granular`/`resonant` keep `I–V`.

## Component 4 — Slow the resonant source (`soundscape_sources.py`)

Reduce `ResonantPulseSource` pulse density so it reads as gentle, sparse
punctuation: lengthen the pulse interval (e.g. multiply the BPM-derived
`pulse_interval` by a factor ~2–3, or divide effective BPM) and/or raise the
minimum interval floor. Keep the existing silent early-out. Tunable by ear.

## Component 5 — Global wash bus (`soundscape_wash.py`, `soundscape_engine.py`, `synth_audio_engine.py`)

**`SoundscapeWash(samplerate)`** applied to the mono mix:
- A `SchroederReverb` set to `space="wash"` with long feedback (long decay), and
  a global feedback delay (a `~1.5–3 s` delay line with high feedback, built in
  the style of `soundscape_transforms.DelayTransform`).
- `set_reverb(amount)` / `set_delay(amount)` set wet levels in `[0, 1]`.
- `process(mono) -> mono`: `dry + reverb_amount·reverb_wet + delay_amount·delay_wet`,
  kept bounded; **runs every block including when there are no voices**, so the
  tail rings out after voices are removed (input is zeros then).

**`SoundscapeEngine`**: own a `SoundscapeWash`; in `generate_block`, feed the
mono `mix` through it *before* the existing `RmsLimiter`/`soft_clip`, and when
there are no patches, still run the wash on a zero block (returning its ringing
tail instead of hard zeros). Add `set_reverb`/`set_delay` passthroughs.

**`SynthAudioEngine`**: thread-safe `set_reverb(amount)` / `set_delay(amount)`
wrappers (lock, delegate to `engine`).

Defaults: a musically pleasant starting point (e.g. reverb ≈ 0.35, delay ≈ 0.2).

## Component 6 — Tab controls (`synth_tab.py`)

- A "Space" (or "Wash") `LabelFrame` in the left column with two
  `ttk.Scale`s: **Reverb** (0–1) and **Delay** (0–1), each `command` calling
  `engine.set_reverb`/`engine.set_delay`. Initialize to the engine defaults.
- Remove the **Load Sample** button.

## Data flow (additions)

```
voice (instrument preset) ─▶ InstrumentSource.render(assignment.midi, bpm, behavior)
                              nearest multisample + resample + behavior envelope
   all voices ─▶ mix (SoundscapeEngine) ─▶ SoundscapeWash(reverb_amt, delay_amt) ─▶ limiter ─▶ soft_clip
Reverb slider ─▶ SynthAudioEngine.set_reverb ─▶ engine.wash.set_reverb
Delay  slider ─▶ SynthAudioEngine.set_delay  ─▶ engine.wash.set_delay
```

## Testing strategy

- **`InstrumentBank`**: `nearest()` picks the closest mapped MIDI; missing
  instrument/folder yields empty bank → `nearest` returns None; loaded samples
  are mono/normalized. Use tiny synthetic WAVs written to a temp dir (no real
  assets needed).
- **`InstrumentSource`**: with an injected in-memory bank — `pad` produces
  continuous non-silent bounded output; `pluck`/`bloom` are mostly silent with
  bounded note bursts; playback rate scales with `assignment.midi`; empty bank →
  silence; state GC'd on `sync`.
- **Grid**: `source_preset_id(row,col)` covers all 25 cells; rows are
  `(granular, resonant, pluck, pad, bloom)`; instrument rows map to the correct
  instrument/behavior; the 3 instrument rows contain the expected instruments.
- **`resonant` slowdown**: pulses are sparser — fewer onsets than before over a
  fixed window at a fixed BPM (assert onset count dropped / interval grew).
- **`SoundscapeWash`**: dry passes through at zero amounts; increasing reverb/
  delay adds energy; output bounded; a tail persists on zero input after signal
  (non-zero output for several blocks after input stops).
- **Engine integration**: `set_reverb`/`set_delay` reach the wash; a voice
  removed still yields a decaying (non-zero then →0) tail; overall output stays
  ≤ 1.0 and NaN-free.
- **`SynthAudioEngine`**: `set_reverb`/`set_delay` are thread-safe passthroughs.

## Risks / mitigations

- **Assets absent (fresh clone / CI):** `InstrumentBank` loads empty → instrument
  voices are silent; granular/resonant still work; tests inject synthetic
  samples. Documented; not a failure.
- **mp3 decode variance:** converting to WAV at download removes runtime mp3
  dependence.
- **Pluck/pad CPU with many voices:** multisample playback is cheap (index +
  interpolate); the wash is one reverb+delay on the master, not per-voice.
- **Loop-wrap clicks (pad):** short crossfade at the wrap.
- **Licensing:** samples are clickbath's; kept gitignored and local-only, never
  committed or redistributed.
