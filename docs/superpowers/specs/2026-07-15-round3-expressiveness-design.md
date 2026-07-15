# RedPole Audio Prototype — Round 3: Expressiveness & Control

## Purpose

Feedback from testing the three engine modes: the color input UI is
clumsy and unrealistically wide; spectral mode is barely audible with
realistic finger-reds; granular is choppy without reverb; there's no way
to route different people to different engines simultaneously; and no
pause/play. This round addresses all five, plus adds live-output spectral
analysis (true Panharmonium behavior).

Amends the two earlier specs; everything not mentioned here is unchanged.

## Features

### 1. Finger-red gradient color picker

The HSV sliders, system color dialog, and Pick Color button are replaced
by a click/drag 2D gradient canvas:

- Horizontal axis: the realistic finger-scan gamut — deep crimson through
  red to orange-pink. Internally hue spans `[-GAMUT, +GAMUT] mod 1.0`
  around red, `FINGER_GAMUT_HALF_WIDTH = 0.06`.
- Vertical axis: brightness (value), bright at top. Saturation is derived
  (darker = more saturated), mirroring real transillumination images.
- A marker shows the current pick; the swatch preview stays.

A new `modulation.hue_to_bipolar(hue) -> [-1, +1]` rescales the narrow
gamut to the full modulation range: crimson = max down, red (hue 0) =
center/zero, orange-pink = max up. All three engines' hue mappings switch
to it (spectral ±7 st, granular ±12 st, tape warble depth by |bipolar|).
Hues outside the gamut clamp to ±1.

### 2. Live-output spectral analysis (feedback resynthesis)

A "Live analysis" checkbox (default off). When on, the engine keeps a
rolling FFT_SIZE window of its own output; each block it extracts partials
from that window (one FFT, cheap) and spectral voices smooth toward this
live frame instead of scanning the precomputed movie. BPM sets voice
tracking speed (slow pulse = laggy smear, fast = tight); saturation still
adds blur. Live partial amps are scaled by a feedback gain < 1, and the
final soft clipper remains, so feedback blooms but cannot run away.
Precomputed mode stays the default; the checkbox only affects
spectral-processing voices (in both `spectral` and `mixed` modes).

### 3. Reverb on the wet bus

New `reverb.py`: classic Schroeder reverb (4 parallel feedback combs + 2
series allpasses), numpy-vectorized in delay-sized chunks, no new
dependencies. Applied to the spectral+granular wet signal only:
`wet_out = wet + reverb_mix * reverb(wet)`. A "Reverb" slider (0–1,
default ~0.35) sets the mix. The dry loop / tape path is never reverbed.

### 4. Mixed mode — per-person engine routing

`AudioEngine.MODES` gains `"mixed"`. Each layer now carries an `engine`
field (`tape` | `spectral` | `granular`), chosen by a dropdown next to
Send and shown in the layer row. In `mixed` mode: tape-assigned layers
drive the tape modulator on the base loop (zero-depth passthrough when
none), spectral-assigned and granular-assigned layers add their voices on
top, all simultaneously. The three single modes route ALL layers to that
engine, ignoring assignments (unchanged A/B behavior).

### 5. Playback control

Pause/Play toggle button; pauses and restarts the output stream without
losing layers, loop position, or voice state.

### 6. Spectral presence

Spectral voice level roughly doubled, and the base loop is gently ducked
as wet-voice layers stack (floor −6 dB) so added voices sit on top of the
loop rather than underneath it. Combined with the gamut rescale in (1),
realistic finger colors now produce unmistakable spectral movement.

## Error handling

- 0 layers, mode switches, and pause/resume never click or crash; 0-layer
  output remains bit-exact dry (duck factor is 1.0 with no layers, reverb
  of silence is silence from clean state).
- Live analysis with a silent output window degrades to silent partials
  (no NaNs).
- Reverb state persists across blocks; mix 0 still ticks the reverb so
  turning it up mid-tail sounds natural.

## Testing

- `hue_to_bipolar`: center/edges/wrap/clamp.
- Reverb: impulse produces a decaying tail across blocks; silence in from
  clean state = silence out; block-length correctness for frames larger
  and smaller than the shortest delay.
- Spectral live mode: `analyze_frame` finds a test tone; `process` with a
  `live_frame` tracks it (output dominant freq approaches the live tone).
- Layer `engine` field stored and returned in snapshots.
- Mixed mode: tape-assigned layer modulates base, spectral/granular
  assigned layers write wet; layers route to the right processor.
- Pause/resume state transitions (no device needed: state flags).
- Existing 0-layer dry-passthrough tests keep passing in all modes.

## Out of scope

- Damped/parametric reverb tuning (basic Schroeder is enough to fix chop).
- Live analysis in tape/granular-only modes (spectral voices are the only
  consumer).
- Hardware integration, persistence, networking (unchanged).
