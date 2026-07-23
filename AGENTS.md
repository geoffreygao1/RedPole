# RED POLE — Agent Brief

> Single source of truth for this project. `CLAUDE.md` imports this file, so
> Claude and Codex both load it automatically. Keep it current.

## ⏱ Pick up here   ← LIVING; refresh at session end
- **Status:**       Prototype — the desktop app (audio_prototype/main.py) has Loop + Synth tabs. The Synth tab now uses a Loop/webapp-style drag-cable patch bay (synth_tab.py): two 5x5 jack grids (sources additive/granular/resonant/noise/texture, transforms delay/spectral/pitch/grainfx/spatial), cable a source jack to a transform jack to create a SoundscapeEngine voice (release off-grid = source-only), each colored by the captured scan color. Synth audio runs on a producer thread with blocking write() at latency="high" (SynthAudioEngine) and a lightweight tk-canvas waveform, fixing the callback/GIL glitching; resonant sources skip their per-sample loop when rung out. Loop tab untouched; web app + firmware/TD still WIP.
- **Last session:** 2026-07-23 — redesigned the Synth tab to the drag-cable patch bay and fixed synth clipping/CPU headroom per docs/superpowers/plans/2026-07-23-synth-patchbay-and-headroom.md (spec: docs/superpowers/specs/2026-07-23-synth-patchbay-and-headroom-design.md).
- **Next up:**
  - Tune by ear in the Synth tab: source/transform preset feel, color->timbre mapping, register/gain, root-note range.
  - Consider cable-click selection/removal and persisting patches.
  - Wire hardware finger-scan input into the Synth tab (spec Phase 3).
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
  hue 0.0–0.085) and a BPM select a patch source. The web app mirrors the
  desktop patch bay — row engines `microloop, granules, glitch, multidelay, tape`
  sent as the `engine` field of a `connect_source` message.
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
