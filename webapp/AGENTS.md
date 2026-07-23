# web — Agent notes

**Stack:** Vanilla JS · AudioWorklet (`worklet.js`) + Worker (`worker.js`)

## Commands (run from `webapp/`)
- Dev: serve statically, e.g. `rtk npx serve .` (AudioWorklet needs http, not file://)
- No build step; plain `index.html` + `main.js` + `style.css`.

## What it is
Browser port of the desktop patch-bay plus a browser-native Tone.js Synth mode.
Loop mode remains 25 source jacks → 5×5 Python/Pyodide effects matrix.
Synth mode is sample-only: 25 pluck/pad/bloom/bell/drone source cells route to
a 5×5 Tone macro grid (veil/shimmer/flutter/scatter/space), then through global
transpose, delay, and reverb.

Keep Loop-mode constants in sync with the desktop app (referenced inline in `main.js`):
- `PATCH_ROW_ENGINES = [microloop, granules, glitch, multidelay, tape]` ↔ `audio_prototype/gui.py:44`
- Finger-scan gamut `FINGER_HUE/SAT/VAL_*` ↔ `modulation.py`
- `RANDOM_BPM_MIN/MAX` ↔ `gui.py:39-40`

## Interface
Loop mode sends a `connect_source` message with an `engine` field (one of the
row engines) when a patch cable connects. Destination/transport to the audio
backend: {{ENDPOINT}}.

Synth mode stays in the browser: source slots create Tone sampler voices and
patch cables call `scheduler.setVoiceMacro(sourceId, macroId)`.

## Gotchas
- AudioWorklet requires a user gesture to start and a real HTTP origin.
- Row order in `PATCH_ROW_ENGINES` is significant — it maps to desktop engines.
- Synth mode depends on `vendor/tone.js` and must be smoke-tested in a browser
  with a user gesture; Python static tests cannot verify audio quality.
