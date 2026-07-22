# firmware — Agent notes

**Stack:** ESP32-S3 Seeed XIAO · PlatformIO · esp32-camera, base64
**Board id:** `seeed_xiao_esp32s3` · **Serial port:** {{PORT}} · **Baud:** 115200
**Note:** the PlatformIO project is the **repo root** (`../platformio.ini`), not a
separate `firmware/` dir.

## Commands (run from repo root)
- Build:   `rtk pio run -e seeed_xiao_esp32s3`
- Flash:   `rtk pio run -e seeed_xiao_esp32s3 -t upload`
- Monitor: `rtk pio device monitor -b 115200`
- Clean:   `rtk pio run -t clean`

## Wiring / pin map
| Pin | Connected to | Notes |
|-----|--------------|-------|
| `T1` (GPIO1) | capacitive touch (the pole) | threshold min 46700 |
| GPIO6 | output | driven when touch active |
| `LED_BUILTIN` | status LED | |

## Behavior (`main.cpp`)
On touch-active rising edge: `delay(500)` → `capturePhotoToRAM()` →
`sendPhotoBase64()`. Handlers: `camera_handler.*`, `touch_handler.*`.

## Interface it exposes
Base64-encoded JPEG over USB serial @ 115200 on each touch trigger.
Framing/delimiter: **TBC — document the exact bytes here.**

## Gotchas
- Requires PSRAM flags: `-DBOARD_HAS_PSRAM -mfix-esp32-psram-cache-issue`.
- `while (!Serial);` in `setup()` blocks until a serial monitor attaches.
