# RED POLE — Agent Brief

> Single source of truth for this project. `CLAUDE.md` imports this file, so
> Claude and Codex both load it automatically. Keep it current.

## ⏱ Pick up here   ← LIVING; refresh at session end
- **Status:**       Prototype — the desktop app (audio_prototype/main.py) has Loop + Synth tabs. The web app Synth mode is now a sample-only Tone.js soundbath: 25 source cells across pluck/pad/bloom/bell/drone rows, a 5x5 Tone-native macro grid (veil/shimmer/flutter/scatter/space), scan-derived fingerprints, conductor-driven ebb/flow, global transpose, and global reverb+delay wash. Loop mode still runs through the Pyodide worker path and `worker.js` remains the Loop backend.
- **Last session:** 2026-07-24 — fixed the "everything sounds melancholy/droney" problem per docs/superpowers/plans/2026-07-24-mood-voicing-and-macro-motion.md: `optimistic`/`happy` moods now use the full clickbath major scale (near-flat weights) instead of a narrow 4-note root-heavy subset; register allocation is mood-aware (wider octave spread for bright moods, sub/low registers anchor on root/fifth as a foundation); the `shadow` and `scatter` macro presets — previously silent no-ops (`new Tone.Gain(1)`) — now actually fire companion notes through the voice's own sampler (`ToneEngine.triggerAccent`); and held `pad`/`bloom`/`drone` voices slowly re-voice (45-150s cycle) instead of sustaining one frozen pitch forever. New pure-logic module `webapp/generative/voicing.js` plus a new `webapp/scheduler.test.js` (first behavioral tests for scheduler.js, using fake engine/Tone objects).
- **Next up:**
  - Run `node --test webapp/generative/ webapp/scheduler.test.js` to confirm the new/changed unit tests pass (not yet verified in this session — Node wasn't available in the dev sandbox).
  - Manual browser smoke/tuning: `cd webapp && python -m http.server`, open Synth mode. Check optimistic/happy sound more melodically varied and less droney; melancholy/mysterious sound unchanged; shadow-cabled voices produce an audible overtone; scatter-cabled voices produce occasional same-instrument echoes at varying pitches; a long-held drone/pad voice changes pitch at least once over 2-3 minutes.
  - Consider sample-set polish for bell/drone rows and longer ambient source material if the current clickbath samples feel too transient.
  - Consider cable-click selection/removal, source-row drag-to-jack assignment, and persisting patches.
  - Wire hardware finger-scan input into the Synth path.
  - Document the firmware serial message shape (base64 JPEG framing).
- **Blockers / open questions:** Is TD driven by the web app, the Python engine, or the device directly?

## What this is
An interactive "red pole" installation: a capacitive touch on the pole triggers
an onboard camera capture; a finger-scan color + BPM drives stacked audio effect
engines (desktop Python prototype + browser port), with TouchDesigner handling
visuals.

## Module map
| Module | Path | Stack | Build / Run | Notes |
|--------|------|-------|-------------|-------|
| firmware | `src/` + `platformio.ini` (repo root) | ESP32-S3 Seeed XIAO / PlatformIO | `rtk pio run -t upload` | `src/AGENTS.md` |
| web | `webapp/` | Vanilla JS + AudioWorklet | open `index.html` (needs a static server) | `webapp/AGENTS.md` |
| python | `audio_prototype/` | Python + Tkinter + sounddevice | `rtk python main.py` | `audio_prototype/AGENTS.md` |
| touchdesigner | `RED_POLE.toe` (repo root) | TouchDesigner | open in TD | driven by {{TD_SOURCE}} — TBC |

## Interfaces / data flow   ← most important section
- **touch → firmware:** capacitive touch on `T1` (GPIO1) crosses threshold 46700
  → firmware captures a camera frame and sends it.
- **firmware → host:** base64-encoded JPEG over **USB serial @ 115200**. Exact
  framing/delimiter: TBC (document in `src/AGENTS.md`).
- **scan (color + BPM) → audio:** finger-scan hue range (bright red→orange,
  hue 0.0–0.085) and BPM become a subtle source fingerprint in web Synth mode:
  harmonic bias, density, shimmer, register, macro drift, and level emphasis.
  Web Loop mode still mirrors the desktop patch bay with row engines
  `microloop, granules, glitch, multidelay, tape` sent as the `engine` field of
  a `connect_source` message.
- **audio ↔ TouchDesigner:** {{TRANSPORT}} — TBC.

## Agent roles (default — override per project)
- **Claude:** orchestration, TouchDesigner (MCP), ESP32/camera datasheet lookups,
  brainstorming & planning, keeps this brief current.
- **Codex:** heads-down module implementation (web patch-bay, Python engines,
  firmware logic) against a written spec.
- **Handoff:** specs live in `docs/superpowers/specs/`. Whoever finishes a chunk
  updates "Pick up here" before stopping.

## Conventions
- Prefix shell/build/git commands with `rtk`.
- Board / FQBN: `seeed_xiao_esp32s3` · Serial port: {{PORT}} · Baud: 115200
- PSRAM build flags required: `-DBOARD_HAS_PSRAM -mfix-esp32-psram-cache-issue`
- Secrets: none committed. Commit style: {{COMMIT_STYLE}}

## Environment / one-time setup
- Toolchain: PlatformIO (`platform = espressif32`), Arduino framework.
- Firmware libs: `espressif/esp32-camera@^2.0.4`, `densaugeo/base64@^1.4.0`.
- Flash: `rtk pio run -t upload` then `rtk pio device monitor -b 115200`.
- Python: create a venv in `audio_prototype/`, `pip install -r requirements.txt`.
- TouchDesigner version: {{TD_VERSION}}.
