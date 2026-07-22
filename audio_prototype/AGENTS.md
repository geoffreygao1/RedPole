# python — Agent notes

**Stack:** Python · Tkinter GUI · `sounddevice` real-time output

## Setup & commands (run from `audio_prototype/`)
- Env:  `rtk python -m venv .venv` → activate → `rtk pip install -r requirements.txt`
- Run:  `rtk python main.py`  (audio starts **paused** — press Play)
- Test: `rtk pytest`  (see `conftest.py`, `tests/`)

## What it does
Interactive audio prototype: routes color/BPM scan inputs into stacked effect
engines. Signal path:
`loaded loop → tape/base path → wet engines → wet bus → reverb → wet/dry → stereo out`

Key modules: `audio_engine.py`, `granular_processor.py`, `spectral_processor.py`,
`microcosm_processor.py`, `frequency_mod_processor.py`, `reverb.py`, `wet_bus.py`,
`modulation.py`, `gui.py`. `web_engine.py` is the bridge toward the browser port.

## Interface
Scan input = `color` (red→orange hue) + `BPM`. Engine names/order must match
`webapp/main.js` `PATCH_ROW_ENGINES`. Transport to web/TD: {{ENDPOINT}}.

## Gotchas
- Loop buffer is mono and capped to first 10 min; spectral analysis capped to 120 s.
- Wet bus + limiter keep 20+ stacked sources bounded — don't remove the limiter.
