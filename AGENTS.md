# RED POLE — Agent Brief

> Single source of truth for this project. `CLAUDE.md` imports this file, so
> Claude and Codex both load it automatically. Keep it current.

## ⏱ Pick up here   ← LIVING; refresh at session end
- **Status:**       Prototype — web app now has Loop + Synth modes; synth mode is local sample-bank backed when the user loads files through the browser, with generated tones only as a fallback. Output slots own sample/source identity, input cells only effect the signal, synth effect rows are Stretch/Delay/Reverb/Stereo/Shape, playback stays unison/no detune, sample-backed mode uses a 1-voice rotating wet/effect budget plus lightweight vectorized row effects and skips global spectral smear/reverb for Pyodide headroom, while generated fallback keeps its 5-voice wet budget. `webapp/assets/samples/` is gitignored for licensed local packs. Firmware/TD integration still WIP.
- **Last session:** 2026-07-22 — moved synth mode back toward sample-backed sources for the MVP and then reduced dense sample-mode CPU cost: added browser multi-file sample loading, Pyodide `load_synth_sample`, `SynthVoiceBank.load_sample`, sample-backed source selection by output slot, precomputed BPM-shaped sample envelopes, Stretch/Delay/Reverb/Stereo/Shape synth effect labels/roles, mode-aware loop-only reverb shortcut routing, sample-backed 1-voice wet budgeting, spectral-smear/reverb bypass for loaded samples, low-CPU sample row effects without Python per-sample delay/filter loops, larger worker blocks/prebuffer, and tests/spec/plan docs for the local sample soundbath direction.
- **Next up:**
  - Tune by ear with the actual local samples: slot-to-sample ordering, BPM envelope curves, color-to-effect mapping, Stretch/Delay/Reverb/Stereo/Shape row intensity, and wet budget size.
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
