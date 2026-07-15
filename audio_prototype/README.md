# RedPole Audio Prototype

Interactive audio-processing prototype for routing color/BPM scan inputs into
stacked effect engines. The prototype is built as a local Python/Tkinter app
with a real-time `sounddevice` output stream.

## System Overview

The app loads an audio loop, plays it back, and lets each scan input create a
patchable source. Each source has two primary parameters:

- `color`: a bright red-to-orange finger-scan color.
- `BPM`: a pulse rate used as a timing and motion control.

The GUI has three main regions:

- `Scan Input`: choose or randomize color and BPM, then send the scan into the
  patch bay.
- `Patch Bay`: 25 preallocated output jacks on the left, a 5x5 effects matrix
  on the right, and curved patch cables between them.
- `Waveform`: a compact live display of output plus modulation traces.

Audio starts paused by default. Use the `Play` button after the app launches.

## Signal Flow

The prototype signal path is:

```text
loaded loop -> tape/base path -> wet engines -> wet bus -> reverb -> wet/dry -> stereo output
```

The engine keeps one mono loop buffer in memory. Long files are loaded in chunks
and capped to the first 10 minutes to avoid decoding large MP3s into multi-GB
buffers. Spectral analysis is capped separately to the first 120 seconds.

The wet bus and limiter keep many stacked sources bounded so 20+ routed inputs
can add motion without immediately overloading the output.

## Parameters

### Color

The GUI picker emits a narrow, bright range designed for finger illumination:

- Hue: `0.0` to `0.085` (red to orange)
- Saturation: `0.64` to `0.72`
- Value: `0.90` to `0.98`

Internally this window is normalized so the full visible picker range maps to
the full effect-control range. Red and orange are therefore meaningful extremes
even though the visual color range is intentionally narrow.

### BPM

BPM is clamped to `20..300` for processing. The Random button generates
test values between `45..180`.

### Patch Matrix

Rows select effect families:

1. `microloop`
2. `granules`
3. `glitch`
4. `multidelay`
5. `reverb`

Columns `I..V` select variants or intensity/style positions inside each row.
Dragging a cable outside the matrix disconnects that source.

## Effect Engines

### Tape

Tape is the base amplitude-modulation path. It uses:

- color to choose amplitude focus
- saturation to sharpen the contour
- value to scale depth
- BPM to set contour smoothing and modulation motion

### Granules

Granules are source-derived grains, not a synthetic oscillator. They use:

- color to choose source-band focus and octave-based pitch behavior
- saturation to control grain length and focus width
- value to control density/spacing and level
- BPM to move the source-search smear

Pitch movement is octave-oriented to avoid semitone dissonance.

### Frequency Mod

The former spectral slot is now a sparse source-derived frequency modulation
engine. It reads around the current source position with tiny displacement and
returns only the difference signal. It uses:

- color for tone bias
- saturation for noise/randomness mix
- value for modulation depth and event spacing
- BPM for modulation rate

Events are intentionally sparse so many layers can stack.

### Microcosm-Style Engines

The patch bay exposes four Microcosm-inspired families:

- `microloop`: longer looped fragments, mosaic/sequence/jump variants
- `granules`: haze/tunnel/strum-like grain clouds
- `glitch`: blocks/interrupt/arp-like interruptions
- `multidelay`: pattern/warp-like delay gestures

These engines emit source-derived events into the wet path. Pitch choices are
octave-biased, with lower octaves weighted more strongly where appropriate.

### Reverb

Reverb acts as a shared spatial blur. Reverb-routed sources do not create a new
dry voice; they send the source and wet bus into a room/wash tail.

Color selects the room style across the current red-to-orange window. Column V
selects the long `wash` style. BPM and value influence tail length and tone.

## Installation

From the repo root:

```powershell
cd audio_prototype
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

If `sounddevice` cannot open an output device, check that your audio interface
is available to Windows and not locked by another app.

## Running

From `audio_prototype`:

```powershell
.\.venv\Scripts\Activate.ps1
py main.py
```

To regenerate the bundled sample loop:

```powershell
py generate_sample_loop.py
```

## Testing

From the repo root:

```powershell
py -m pytest audio_prototype\tests -q
```

## Notes

- The prototype is intentionally local-file based.
- Long audio files are currently windowed to the first 10 minutes.
- The patch bay can generate up to 25 scan output jacks.
- `Wet/Dry` is an audition control; at full wet, reverb tails and wet engines
  should be hearable without the dry source dominating.
