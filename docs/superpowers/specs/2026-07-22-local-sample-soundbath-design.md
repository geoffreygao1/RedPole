# Local Sample Soundbath Design

## Goal
Restore synth mode as a local sample-bank sound source while keeping samples out of git, and make patch-bay effect rows direct enough to tune by ear.

## Source Behavior
Synth mode becomes sample-backed when the user loads local audio files in the browser. Files are decoded to mono in `webapp/main.js`, sent to the Pyodide worker, and stored by the Python engine. If no sample bank is loaded, the current generated source remains as a fallback.

Samples are assumed to be in C for this MVP. Source/output slots own sample identity and base playback. Input/effect cells must not repitch the source. BPM and color may shape playback envelope, sample choice, tone, stretch feel, and effect amount.

## Effect Rows
Synth-mode patch rows are:

- `stretch`: slower smeared playback and long envelopes
- `delay`: soft echo, ping-pong-like movement, and multitap wash
- `reverb`: large ambient space and damping
- `stereo`: pan drift and width-style motion, represented as mono-safe movement until the browser path supports true stereo blocks
- `shape`: filtering, soft saturation, transient smoothing, and tone shaping

Columns increase or vary intensity from subtle to washed. Effects should stay unison and bounded with dense patches.

## Local Assets
Licensed samples live under ignored local paths such as `webapp/assets/samples/`. The app loads them through a browser file picker instead of a committed manifest.

## Performance
The sample-backed path avoids rendering oscillator loops for every source. Each loaded sample is normalized once, then voices read from cached buffers with lightweight envelope and tone shaping.
