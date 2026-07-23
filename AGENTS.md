# RED POLE — Agent Brief

> Single source of truth for this project. `CLAUDE.md` imports this file, so
> Claude and Codex both load it automatically. Keep it current.

## ⏱ Pick up here   ← LIVING; refresh at session end
- **Status:**       Prototype — the desktop app (audio_prototype/main.py) has Loop + Synth tabs. The Synth tab now mirrors the web-app workflow: Play/Pause, Send scanned color+BPM into a single-use Sources list, click a source then a generator jack to create a source-only voice, and cable a placed generator jack to a modifier jack (off-grid clears the modifier). SoundscapeEngine has an evolving-mix VoiceConductor for slow per-voice swells/foreground rotation, plus a live gliding harmonic-root slider that re-pitches active tonal voices without clearing patches. Synth audio still runs on a producer thread with blocking write() at latency="high" and a lightweight tk-canvas waveform. Loop tab untouched; web app + firmware/TD still WIP.
- **Last session:** 2026-07-23 — implemented synth web-app parity + evolving mix + live root slider per docs/superpowers/plans/2026-07-23-synth-webapp-parity-and-evolving-mix.md (spec: docs/superpowers/specs/2026-07-23-synth-webapp-parity-and-evolving-mix-design.md).
- **Next up:**
  - Tune by ear in the Synth tab: source/transform preset feel, evolving-mix depth/rate, color->timbre mapping, register/gain, root-note range.
  - Consider cable-click selection/removal, source-row drag-to-jack assignment, and persisting patches.
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
