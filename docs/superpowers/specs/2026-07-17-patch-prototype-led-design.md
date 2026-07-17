# Patch Prototype — TRS Cable LED Control

**Date:** 2026-07-17
**Target:** Seeed XIAO ESP32S3, PlatformIO (Arduino framework), project lives in `patch_prototype/` as its own PlatformIO project.

## Purpose

Demonstrate LED-illuminated patch cables. Each patch cable has a PL9823 (WS2811-family) RGB LED wired into each of its two 3.5mm TRS plugs. Panel-side switching TRS jacks detect insertion. Firmware assigns a color per cable and keeps both ends of a cable glowing the same color, tracking the cable across unplug/replug.

## Hardware

Per TRS plug (cable side):
- Tip = LED power (5V), Ring = LED DIN (serial color data), Sleeve = ground.
- LED: Akizuki PL9823-F5 (WS2811 protocol, 24-bit RGB, 4.5–6V supply).

Per panel jack (connector side), switching type:
- Pin 1 = sleeve/ground, Pin 2 = tip (power), Pin 3 = ring (LED DIN), Pin 4 = tip switch contact.
- Pin 4 feeds a 4.7k/4.7k voltage divider; the divider midpoint goes to a GPIO as presence detect.

Jack IDs are 1–4 in conversation; firmware uses 0-based indices 0–3.

Phase 1 wiring (only jack index 0 populated):
- LED DIN: D10 / GPIO9
- Presence detect: D9 / GPIO8 (external divider sets levels; GPIO configured as plain `INPUT`)

Presence polarity is not assumed: a single `PRESENT_LEVEL` define sets which digital level means "inserted." Firmware prints the raw pin state at boot and on every change so the polarity can be verified empirically and the define flipped if backwards.

## Core model

```
struct Jack {
  uint8_t ledPin;
  uint8_t sensePin;
  bool    present;      // debounced
  int8_t  pairedWith;   // partner jack index, or -1
  CRGB    color;        // cable color shown at this jack; persists across unplug
  bool    hasColor;     // false until a color has ever been assigned
};
```

- `NUM_JACKS = 4` (full data structures from day one).
- `ACTIVE_JACKS = 1` for phase 1; only the first `ACTIVE_JACKS` entries are scanned/driven. Bumping this constant and filling in the pin table is the only change needed to enable jacks 1–3.
- **Pending queue:** FIFO of jack indices that are present and unpaired.
- **Staged color:** one optional color value ("the color for the next new cable"), set by serial command, consumed by the next new-cable insertion.

## Behavior

**Serial color command** (`#RRGGBB` or `R,G,B`):
- Stages the color. Nothing lights immediately — **except** if a pending jack exists with no color yet (plugged before any color was staged): the staged color applies to that pending jack retroactively and it lights up. Plug-then-color and color-then-plug are both valid orders.

**On insert** (debounced absent→present at jack C):
- Pending queue non-empty → second end of an existing cable: pop oldest pending P, pair C↔P, copy P's color (and `hasColor`) to C, render C.
- Pending queue empty → first end of a new cable: C takes the staged color if one is staged (consuming it) and lights up; if no color is staged, C stays **dark** but still becomes pending. C is pushed onto the pending queue either way.

**On remove** (present→absent at jack C):
- C was paired with P → unpair both; P keeps glowing its color and joins the pending queue (it is now the loose end of its cable). Replugging anywhere pairs the new insertion with P and copies the color.
- C was pending → drop it from the queue.
- C's LED output is blanked (no cable in the jack means no LED to drive, but blanking keeps the data line quiet). C's `color`/`hasColor` are retained in memory.

**Known ambiguity (accepted):** if two different cables each have one end inserted before either second end, FIFO pairing will wrongly pair them. Physically unresolvable with this hardware; demo convention is to complete one cable before starting the next. Mitigation logic is deferred to a later phase.

## Serial protocol

115200 baud, newline-terminated commands:

| Command | Effect |
|---|---|
| `#RRGGBB` | Stage color (hex) |
| `R,G,B` | Stage color (decimal 0–255) |
| `status` | Dump every active jack: present, pairedWith, color, hasColor; plus staged color and pending queue |
| `off` | Clear the staged color |

Firmware logs, human-readable: boot banner with pin config and raw sense state, insert/remove events, pairing events, color staging/consumption, and unrecognized-command errors.

## Implementation notes

- LED driver: FastLED, chipset `PL9823`, one `CRGB` per jack, each jack's DIN on its own data pin.
- Presence detect: polled in `loop()` with ~30 ms debounce per jack.
- Structure: single `main.cpp` is acceptable at this scale, but pairing/queue logic goes in plain functions operating on the `Jack` array (no Arduino dependencies in the logic) so it stays testable and portable.
- `platformio.ini` in `patch_prototype/`: `seeed_xiao_esp32s3`, Arduino framework, `monitor_speed = 115200`, `lib_deps = fastled/FastLED`.

## Phases

1. **Now:** full pairing/staging logic built, one jack wired (`ACTIVE_JACKS = 1`). Verifies: presence detect polarity, PL9823 color rendering, stage→insert→glow, remove→remember.
2. **Later:** wire jacks 2–4, set `ACTIVE_JACKS = 4`, fill pin table. No logic changes expected.
3. **Future (out of scope):** mitigation for the two-simultaneous-new-cables ambiguity.

## Success criteria (phase 1)

- Staging `#FF00A0` then inserting the plug lights the LED magenta.
- Inserting with nothing staged leaves the LED dark; a subsequent color command lights it.
- Unplug/replug events log correctly with stable debounce (no chatter).
- `status` reflects reality at every step.
