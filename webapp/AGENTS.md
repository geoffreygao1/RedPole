# web — Agent notes

**Stack:** Vanilla JS · AudioWorklet (`worklet.js`) + Worker (`worker.js`)

## Commands (run from `webapp/`)
- Dev: serve statically, e.g. `rtk npx serve .` (AudioWorklet needs http, not file://)
- No build step; plain `index.html` + `main.js` + `style.css`.

## What it is
Browser port of the desktop patch-bay: 25 source jacks → 5×5 effects matrix.
Keep constants in sync with the desktop app (referenced inline in `main.js`):
- `PATCH_ROW_ENGINES = [microloop, granules, glitch, multidelay, tape]` ↔ `audio_prototype/gui.py:44`
- Finger-scan gamut `FINGER_HUE/SAT/VAL_*` ↔ `modulation.py`
- `RANDOM_BPM_MIN/MAX` ↔ `gui.py:39-40`

## Interface
Sends a `connect_source` message with an `engine` field (one of the row engines)
when a patch cable connects. Destination/transport to the audio backend: {{ENDPOINT}}.

## Gotchas
- AudioWorklet requires a user gesture to start and a real HTTP origin.
- Row order in `PATCH_ROW_ENGINES` is significant — it maps to desktop engines.
