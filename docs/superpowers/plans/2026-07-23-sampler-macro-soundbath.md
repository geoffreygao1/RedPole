# Sampler Macro Soundbath Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary Synth-mode trigger grid with a sample-only 5x5 source grid cabled into a Tone-native 5x5 macro grid, with scan fingerprints, conductor-driven ebb/flow, global transpose, and one global clickbath-style delay/reverb wash.

**Architecture:** Pure JS modules define the stable musical data first: source/macro grid config and scan fingerprint derivation. `tone_engine.js` owns the Tone graph, sampler voices, per-voice macro chains, global transpose, global delay/reverb, and lifecycle. `scheduler.js` owns long-running musical variation: voice emphasis, source event timing, and macro modulation. `main.js` only maps patch-bay gestures to those APIs; loop mode and `worker.js` remain unchanged.

**Tech Stack:** Vanilla JS ES modules, Tone.js 14.7.77 vendored in `webapp/vendor/tone.js`, browser Web Audio, Python `pytest` static tests in `audio_prototype/tests/test_webapp_static.py`, optional Node syntax/unit tests when Node is available.

---

## Global Constraints

- Work in the existing workspace; do not touch the unrelated untracked `patch_prototype/.vscode/`.
- Prefix shell/build/git commands with `rtk` when available.
- Keep loop mode unchanged: no edits to `webapp/worker.js`, `webapp/worklet.js`, or Python DSP files.
- Keep clickbath samples gitignored under `webapp/audio/clickbath/`; do not commit samples.
- Synth mode must support up to 25 placed/cabled patches.
- Reverb and delay remain global only.
- Avoid per-voice `Tone.Reverb`, convolution, long feedback networks, and per-voice `Tone.PitchShift`.
- The first implementation uses no non-sample source cells.

## File Structure

- Create `webapp/soundbath_config.js`: 5x5 source grid, 5x5 macro grid, labels, lookup helpers. No Tone.js dependency.
- Create `webapp/generative/fingerprint.js`: deterministic scan fingerprint derivation. No Tone.js dependency.
- Modify `webapp/modifiers.js`: replace old `stretch/spectral/pitch/grainfx/spatial` presets with `veil/shimmer/flutter/scatter/space` macro presets and a light `createMacroNode(Tone, presetId)` factory.
- Modify `webapp/tone_engine.js`: add global transpose, per-voice macro lifecycle, sampler behavior envelopes for all five source rows, voice-level macro modulation hooks, and global limiter.
- Modify `webapp/scheduler.js`: replace trigger-grid sequencing with conductor-driven sampler behavior and fingerprint-shaped event variation.
- Modify `webapp/main.js`: use the new source/macro grid config, route Synth cables to macros instead of triggers, preserve macro when moving a source, and pass fingerprints to engine/scheduler.
- Modify `webapp/index.html`: add a global Transpose slider.
- Modify `audio_prototype/tests/test_webapp_static.py`: update static expectations for the new source/macro grid and transpose control.
- Modify `AGENTS.md` and `webapp/AGENTS.md`: update pickup notes and Synth-mode interface notes.

---

### Task 1: Pure Config For 5x5 Source And Macro Grids

**Files:**
- Create: `webapp/soundbath_config.js`
- Modify: `audio_prototype/tests/test_webapp_static.py`

**Purpose:** Lock the 25 sample source cells and 25 macro cells into one importable module so `main.js`, `modifiers.js`, and tests do not duplicate row/column strings.

- [ ] **Step 1: Add failing static expectations**

Modify `audio_prototype/tests/test_webapp_static.py` by replacing `test_synth_mode_patch_labels_show_sound_bath_effects` with a config-only test:

```python
def test_sampler_macro_soundbath_grid_config_is_5x5_and_sample_only():
    config_js = (ROOT / "webapp" / "soundbath_config.js").read_text()

    assert 'const SOURCE_ROWS = ["pluck", "pad", "bloom", "bell", "drone"];' in config_js
    assert 'const MACRO_ROWS = ["veil", "shimmer", "flutter", "scatter", "space"];' in config_js
    assert '"piano", "guitar", "tapeguitar", "tapebell", "casio"' in config_js
    assert '"strings", "flute", "clarinet", "casio", "piano"' in config_js
    assert '"strings", "flute", "clarinet", "tapebell", "guitar"' in config_js
    assert '"tapebell", "casio", "piano", "guitar", "flute"' in config_js
    assert '"strings", "casio", "flute", "clarinet", "tapeguitar"' in config_js
    assert "export function sourceForSlot" in config_js
    assert "export function macroPresetId" in config_js
```

- [ ] **Step 2: Run the targeted test and verify it fails**

Run:

```powershell
rtk python -m pytest audio_prototype/tests/test_webapp_static.py::test_sampler_macro_soundbath_grid_config_is_5x5_and_sample_only -q
```

Expected: FAIL because `webapp/soundbath_config.js` does not exist yet.

- [ ] **Step 3: Create `webapp/soundbath_config.js`**

Add the file:

```js
export const SOURCE_ROWS = ["pluck", "pad", "bloom", "bell", "drone"];
export const MACRO_ROWS = ["veil", "shimmer", "flutter", "scatter", "space"];
export const MACRO_COLS = ["I", "II", "III", "IV", "V"];

export const SOURCE_GRID = [
  ["piano", "guitar", "tapeguitar", "tapebell", "casio"],
  ["strings", "flute", "clarinet", "casio", "piano"],
  ["strings", "flute", "clarinet", "tapebell", "guitar"],
  ["tapebell", "casio", "piano", "guitar", "flute"],
  ["strings", "casio", "flute", "clarinet", "tapeguitar"],
];

export function sourceForSlot(slot, cols = 5) {
  const row = Math.floor(slot / cols);
  const col = slot % cols;
  return sourceForCell(row, col);
}

export function sourceForCell(row, col) {
  const behavior = SOURCE_ROWS[row];
  const instrument = SOURCE_GRID[row]?.[col];
  if (!behavior || !instrument) return null;
  return { behavior, instrument, row, col };
}

export function macroPresetId(row, col) {
  const macro = MACRO_ROWS[row];
  if (!macro || col < 0 || col >= MACRO_COLS.length) return null;
  return `${macro}_${col + 1}`;
}

export function macroLabel(row, col) {
  const macro = MACRO_ROWS[row];
  const variant = MACRO_COLS[col];
  return macro && variant ? `${macro} ${variant}` : "";
}
```

- [ ] **Step 4: Run the targeted test**

Run:

```powershell
rtk python -m pytest audio_prototype/tests/test_webapp_static.py::test_sampler_macro_soundbath_grid_config_is_5x5_and_sample_only -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
rtk git add webapp/soundbath_config.js audio_prototype/tests/test_webapp_static.py
rtk git commit -m "test(webapp): specify sampler macro soundbath grid"
```

---

### Task 2: Scan Fingerprint Derivation

**Files:**
- Create: `webapp/generative/fingerprint.js`
- Create: `webapp/generative/fingerprint.test.js`

**Purpose:** Convert hue/sat/val/BPM into a stable fingerprint object used by the source scheduler and macro modulation. This keeps color/BPM as a hidden identity rather than obvious direct knobs.

- [ ] **Step 1: Write failing tests**

Create `webapp/generative/fingerprint.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { deriveFingerprint } from "./fingerprint.js";

test("deriveFingerprint is deterministic for the same scan", () => {
  const a = deriveFingerprint({ hue: 0.03, sat: 0.68, val: 0.94, bpm: 70 });
  const b = deriveFingerprint({ hue: 0.03, sat: 0.68, val: 0.94, bpm: 70 });
  assert.deepEqual(a, b);
});

test("deriveFingerprint clamps ranges", () => {
  const fp = deriveFingerprint({ hue: -1, sat: 2, val: 9, bpm: 900 });
  assert.equal(fp.hue, 0);
  assert.equal(fp.sat, 1);
  assert.equal(fp.val, 1);
  assert.equal(fp.bpm, 300);
  assert.ok(fp.motionBias >= 0 && fp.motionBias <= 1);
  assert.ok(fp.densityBias >= 0 && fp.densityBias <= 1);
});

test("different BPM changes motion but not harmonic lane for same color", () => {
  const slow = deriveFingerprint({ hue: 0.04, sat: 0.7, val: 0.95, bpm: 45 });
  const fast = deriveFingerprint({ hue: 0.04, sat: 0.7, val: 0.95, bpm: 180 });
  assert.equal(slow.harmonicBias, fast.harmonicBias);
  assert.notEqual(slow.motionBias, fast.motionBias);
});
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
rtk node --test webapp/generative/fingerprint.test.js
```

Expected if Node is available: FAIL because `fingerprint.js` does not exist. If `rtk node` is unavailable in this shell, continue and rely on the pytest static gate; browser/manual validation will cover runtime.

- [ ] **Step 3: Implement `fingerprint.js`**

Create `webapp/generative/fingerprint.js`:

```js
function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

function hashFloat(value, scale) {
  return Math.round(value * scale) | 0;
}

export function deriveFingerprint({ hue, sat, val, bpm }) {
  const h = clamp(Number.isFinite(hue) ? hue : 0, 0, 1);
  const s = clamp(Number.isFinite(sat) ? sat : 0.68, 0, 1);
  const v = clamp(Number.isFinite(val) ? val : 0.94, 0, 1);
  const b = clamp(Number.isFinite(bpm) ? bpm : 70, 20, 300);
  const bpmNorm = (b - 20) / 280;
  const seed =
    (hashFloat(h, 1000000) * 73856093) ^
    (hashFloat(s, 1000000) * 19349663) ^
    (hashFloat(v, 1000000) * 83492791) ^
    (hashFloat(b, 1000) * 2654435761);
  return {
    hue: h,
    sat: s,
    val: v,
    bpm: b,
    seed: seed >>> 0,
    harmonicBias: Math.floor(h * 6),
    registerBias: clamp(0.25 + h * 0.65 + (v - 0.5) * 0.2, 0, 1),
    brightnessBias: clamp(0.2 + v * 0.55 + s * 0.25, 0, 1),
    motionBias: clamp(0.15 + bpmNorm * 0.75, 0, 1),
    densityBias: clamp(0.1 + bpmNorm * 0.55 + s * 0.2, 0, 1),
    softnessBias: clamp(1 - (s * 0.45 + v * 0.25), 0, 1),
    washBias: clamp(0.25 + v * 0.35 + (1 - s) * 0.25, 0, 1),
  };
}
```

- [ ] **Step 4: Run test and verify pass**

Run:

```powershell
rtk node --test webapp/generative/fingerprint.test.js
```

Expected: PASS if Node is available.

- [ ] **Step 5: Commit**

```powershell
rtk git add webapp/generative/fingerprint.js webapp/generative/fingerprint.test.js
rtk git commit -m "feat(webapp): derive scan fingerprints for soundbath voices"
```

---

### Task 3: Macro Preset Factory

**Files:**
- Modify: `webapp/modifiers.js`

**Purpose:** Replace the old aspirational effect labels with Tone-native macro rows: `veil`, `shimmer`, `flutter`, `scatter`, `space`. Keep all per-voice macros light. Do not add per-voice reverb or per-voice pitch shift.

- [ ] **Step 1: Replace `webapp/modifiers.js`**

Replace the file contents with:

```js
import { MACRO_COLS, MACRO_ROWS, macroPresetId } from "./soundbath_config.js";

export const MODIFIER_ROWS = MACRO_ROWS;
export const MODIFIER_COLS = MACRO_COLS;

const PRESET_DEFS = {
  veil: [
    { label: "soft", kind: "filter", frequency: 2600, type: "lowpass" },
    { label: "warm", kind: "eq", low: 1.5, mid: -1.5, high: -4 },
    { label: "blur", kind: "chorus", frequency: 0.08, delayTime: 3.5, depth: 0.25, feedback: 0.05, wet: 0.25 },
    { label: "far", kind: "series", nodes: [
      { kind: "filter", frequency: 900, type: "lowpass" },
      { kind: "gain", gain: 0.7 },
    ] },
    { label: "haze", kind: "chorus", frequency: 0.12, delayTime: 7, depth: 0.45, feedback: 0.12, wet: 0.4 },
  ],
  shimmer: [
    { label: "air", kind: "eq", low: -2, mid: -1, high: 2 },
    { label: "fifth shadow", kind: "shadow", interval: 7, gain: 0.18 },
    { label: "octave glint", kind: "shadow", interval: 12, gain: 0.16 },
    { label: "bright halo", kind: "series", nodes: [
      { kind: "filter", frequency: 1200, type: "highpass" },
      { kind: "chorus", frequency: 0.18, delayTime: 4, depth: 0.25, feedback: 0.05, wet: 0.22 },
    ] },
    { label: "rare stars", kind: "shadow", interval: 19, gain: 0.12 },
  ],
  flutter: [
    { label: "slow tremble", kind: "tremolo", frequency: 0.08, depth: 0.18, wet: 0.35 },
    { label: "tape drift", kind: "vibrato", frequency: 0.18, depth: 0.08, wet: 0.35 },
    { label: "filter sway", kind: "autoFilter", frequency: 0.06, depth: 0.35, baseFrequency: 500, octaves: 2.2, wet: 0.35 },
    { label: "choral wobble", kind: "chorus", frequency: 0.25, delayTime: 4, depth: 0.35, feedback: 0.08, wet: 0.32 },
    { label: "deep pulse", kind: "tremolo", frequency: 0.14, depth: 0.35, wet: 0.45 },
  ],
  scatter: [
    { label: "soft recall", kind: "delay", delayTime: 0.11, feedback: 0.12, wet: 0.16 },
    { label: "double", kind: "delay", delayTime: 0.19, feedback: 0.18, wet: 0.2 },
    { label: "fragments", kind: "scatter", density: 0.22, gain: 0.18 },
    { label: "trails", kind: "delay", delayTime: 0.28, feedback: 0.28, wet: 0.25 },
    { label: "constellation", kind: "scatter", density: 0.38, gain: 0.16 },
  ],
  space: [
    { label: "left drift", kind: "pan", pan: -0.35 },
    { label: "right drift", kind: "pan", pan: 0.35 },
    { label: "orbit", kind: "autoPanner", frequency: 0.08, depth: 0.55, wet: 0.55 },
    { label: "wide", kind: "widener", width: 0.6 },
    { label: "distant", kind: "series", nodes: [
      { kind: "filter", frequency: 650, type: "lowpass" },
      { kind: "gain", gain: 0.62 },
    ] },
  ],
};

export const MODIFIER_PRESETS = Object.fromEntries(
  MACRO_ROWS.flatMap((row, rowIndex) =>
    PRESET_DEFS[row].map((preset, col) => [
      macroPresetId(rowIndex, col),
      { id: macroPresetId(rowIndex, col), row, rowIndex, col, ...preset },
    ])
  )
);

function setWet(node, wet) {
  if (wet !== undefined && node.wet && "value" in node.wet) node.wet.value = wet;
  return node;
}

function startIfLfo(node) {
  if (typeof node.start === "function") {
    try { node.start(); } catch { /* Tone node does not expose a no-arg LFO starter. */ }
  }
  return node;
}

function buildNode(Tone, preset) {
  switch (preset.kind) {
    case "gain":
      return new Tone.Gain(preset.gain);
    case "filter":
      return new Tone.Filter({ frequency: preset.frequency, type: preset.type ?? "lowpass" });
    case "eq":
      return new Tone.EQ3({ low: preset.low, mid: preset.mid, high: preset.high });
    case "chorus":
      return startIfLfo(new Tone.Chorus({
        frequency: preset.frequency,
        delayTime: preset.delayTime,
        depth: preset.depth,
        feedback: preset.feedback,
        wet: preset.wet,
      }));
    case "tremolo":
      return startIfLfo(new Tone.Tremolo({ frequency: preset.frequency, depth: preset.depth, wet: preset.wet }));
    case "vibrato":
      return new Tone.Vibrato({ frequency: preset.frequency, depth: preset.depth, wet: preset.wet });
    case "autoFilter":
      return startIfLfo(new Tone.AutoFilter({
        frequency: preset.frequency,
        depth: preset.depth,
        baseFrequency: preset.baseFrequency,
        octaves: preset.octaves,
        wet: preset.wet,
      }));
    case "delay":
      return new Tone.FeedbackDelay({ delayTime: preset.delayTime, feedback: preset.feedback, wet: preset.wet });
    case "pan":
      return new Tone.PanVol({ pan: preset.pan, volume: 0 });
    case "autoPanner":
      return startIfLfo(new Tone.AutoPanner({ frequency: preset.frequency, depth: preset.depth, wet: preset.wet }));
    case "widener":
      return new Tone.StereoWidener(preset.width);
    case "shadow":
    case "scatter":
      return new Tone.Gain(1);
    default:
      throw new Error(`Unsupported macro kind: ${preset.kind}`);
  }
}

export function createMacroNode(Tone, presetId) {
  const preset = MODIFIER_PRESETS[presetId];
  if (!preset) throw new Error(`Unknown macro preset: ${presetId}`);
  if (preset.kind === "series") {
    const input = new Tone.Gain(1);
    const output = new Tone.Gain(1);
    const nodes = preset.nodes.map((nodePreset) => buildNode(Tone, nodePreset));
    let current = input;
    for (const node of nodes) {
      current.connect(node);
      current = node;
    }
    current.connect(output);
    return { input, output, nodes: [input, ...nodes, output], preset };
  }
  const node = setWet(buildNode(Tone, preset), preset.wet);
  return { input: node, output: node, nodes: [node], preset };
}
```

- [ ] **Step 2: Run static syntax check**

Run:

```powershell
rtk node --check webapp/modifiers.js
```

Expected if Node is available: no syntax errors.

- [ ] **Step 3: Commit**

```powershell
rtk git add webapp/modifiers.js
rtk git commit -m "feat(webapp): define Tone-native soundbath macro presets"
```

---

### Task 4: Tone Engine Macro Lifecycle And Global Transpose

**Files:**
- Modify: `webapp/tone_engine.js`

**Purpose:** Add the actual graph needed by the new design: sampler voices, light macro chains, one global `PitchShift` before the shared delay/reverb, limiter, and helpers for conductor/macro modulation.

- [ ] **Step 1: Modify imports and constants**

At the top of `webapp/tone_engine.js`, add:

```js
import { createMacroNode } from "./modifiers.js";
```

Replace `BEHAVIOR_ENVELOPES` and `HELD_BEHAVIORS` with:

```js
const BEHAVIOR_ENVELOPES = {
  pluck: { attack: 0.005, release: 1.5 },
  pad: { attack: 0.4, release: 2.0 },
  bloom: { attack: 1.5, release: 3.5 },
  bell: { attack: 0.002, release: 2.2 },
  drone: { attack: 2.5, release: 5.0 },
};

const HELD_BEHAVIORS = new Set(["pad", "bloom", "drone"]);
```

- [ ] **Step 2: Add global transpose nodes in `init()`**

In `constructor`, add:

```js
this.transpose = null;
this.limiter = null;
```

In `init()`, replace:

```js
this.master.chain(this.delay, this.reverb, this.Tone.Destination);
```

with:

```js
this.transpose = new this.Tone.PitchShift({ pitch: 0, windowSize: 0.08, delayTime: 0.03, feedback: 0, wet: 1 });
this.limiter = new this.Tone.Limiter(-1);
this.master.chain(this.transpose, this.delay, this.reverb, this.limiter, this.Tone.Destination);
```

Add the method:

```js
setTranspose(semitones) {
  if (!this.transpose) return;
  rampParam(this.transpose.pitch, clamp(semitones, -12, 12), 0.18);
}
```

- [ ] **Step 3: Store fingerprint and macro state in `createVoice()`**

Change `createVoice` signature to:

```js
createVoice(voiceId, { instrument, behavior, fingerprint = null }) {
```

and store:

```js
fingerprint,
macro: null,
macroId: null,
connected: false,
```

inside the voice object.

- [ ] **Step 4: Replace `_buildNodes()` chain**

Keep sampler creation, but change the chain so sampler connects to a dry input and macro insertion can be rebuilt:

```js
const sampler = new this.Tone.Sampler({ urls, attack: env.attack, release: env.release });
const input = new this.Tone.Gain(1);
const volume = new this.Tone.Volume(NEGATIVE_INFINITY_DB);
sampler.connect(input);
input.connect(volume);
voice.nodes = { sampler, input, volume };
```

- [ ] **Step 5: Add macro lifecycle methods**

Add these methods to `ToneEngine`:

```js
_disposeMacro(voice) {
  if (!voice.macro) return;
  for (const node of voice.macro.nodes ?? []) {
    try { node.disconnect(); } catch { /* already disconnected */ }
    if (typeof node.dispose === "function") node.dispose();
  }
  voice.macro = null;
  voice.macroId = null;
}

_connectVoiceChain(voice) {
  const { input, volume } = voice.nodes;
  try { input.disconnect(); } catch { /* reconnecting */ }
  if (voice.macro) {
    input.connect(voice.macro.input);
    voice.macro.output.connect(volume);
  } else {
    input.connect(volume);
  }
  try { volume.disconnect(); } catch { /* reconnecting */ }
  if (voice.connected) volume.connect(this.master);
}

setVoiceMacro(voiceId, macroId) {
  const voice = this.voices.get(voiceId);
  if (!voice) return;
  if (macroId && !voice.nodes) this._buildNodes(voice);
  if (!macroId) {
    voice.connected = false;
    if (voice.nodes) {
      this._disposeMacro(voice);
      try { voice.nodes.volume.disconnect(); } catch { /* already disconnected */ }
      this.releaseVoice(voiceId);
    }
    return;
  }
  this._disposeMacro(voice);
  voice.macro = createMacroNode(this.Tone, macroId);
  voice.macroId = macroId;
  voice.connected = true;
  this._connectVoiceChain(voice);
}

setVoiceConnected(voiceId, connected) {
  if (connected) return;
  this.setVoiceMacro(voiceId, null);
}
```

This preserves backward compatibility for any remaining `setVoiceConnected(id, false)` calls while making macros the audible connection path.

- [ ] **Step 6: Update teardown/dispose**

In `_teardownNodes(voice)`, call `this._disposeMacro(voice);` before disconnecting sampler/volume, and disconnect `input` if present:

```js
const { sampler, input, volume } = voice.nodes;
this._disposeMacro(voice);
disconnect(sampler);
disconnect(input);
disconnect(volume);
sampler.dispose();
input.dispose();
volume.dispose();
```

- [ ] **Step 7: Add helpers for scheduler/manual validation**

Add:

```js
isVoiceHeld(voiceId) {
  return Boolean(this.voices.get(voiceId)?.held);
}

voiceMacroPreset(voiceId) {
  return this.voices.get(voiceId)?.macro?.preset ?? null;
}
```

- [ ] **Step 8: Run syntax check**

Run:

```powershell
rtk node --check webapp/tone_engine.js
```

Expected if Node is available: no syntax errors.

- [ ] **Step 9: Commit**

```powershell
rtk git add webapp/tone_engine.js
rtk git commit -m "feat(webapp): add sampler macro graph and global transpose"
```

---

### Task 5: Scheduler Conductor And Source Events

**Files:**
- Modify: `webapp/scheduler.js`

**Purpose:** Replace trigger-grid timing with long-form variation. The scheduler should continuously set voice gains from `VoiceConductor` and trigger sample behavior based on source row plus fingerprint.

- [ ] **Step 1: Replace imports and constants**

Replace `webapp/scheduler.js` imports with:

```js
import { VoiceConductor } from "./generative/conductor.js";
import { HarmonicField, ROLE_SEMITONES } from "./generative/harmony.js";
import { PitchAllocator } from "./generative/allocator.js";
import { mulberry32 } from "./generative/rng.js";
```

Use constants:

```js
const ROOT_MIN = 36;
const ROOT_MAX = 60;
const TICK_SUBDIVISION = "16n";
const TICKS_PER_BEAT = 4;
const BEHAVIOR_PERIODS = {
  pluck: [2, 8],
  bell: [4, 16],
  pad: [16, 48],
  bloom: [12, 40],
  drone: [32, 96],
};
```

- [ ] **Step 2: Replace constructor state**

Use:

```js
constructor(engine, { Tone: tone = engine.Tone ?? globalThis.Tone, seed = 2130 } = {}) {
  this.engine = engine;
  this.Tone = tone;
  this.seed = seed;
  this.rootMidi = 48;
  this.field = new HarmonicField(this.rootMidi);
  this.allocator = new PitchAllocator(this.field);
  this.conductor = new VoiceConductor({ seed, minPeriod: 20, maxPeriod: 90, smoothTau: 1.2 });
  this.voices = new Map();
  this.tick = 0;
  this.event = null;
}
```

- [ ] **Step 3: Replace `addVoice()`**

Use:

```js
addVoice(voiceId, { behavior, fingerprint = null }) {
  const density = Math.min(1, (this.voices.size + 1) / 20);
  const rng = mulberry32((fingerprint?.seed ?? voiceId) ^ this.seed ^ voiceId);
  const assignment = this.allocator.allocate(voiceId, rng, density, behavior === "drone" ? "background" : "foreground");
  const [minBeats, maxBeats] = BEHAVIOR_PERIODS[behavior] ?? BEHAVIOR_PERIODS.pluck;
  const motion = fingerprint?.motionBias ?? 0.35;
  const periodBeats = maxBeats - (maxBeats - minBeats) * motion;
  this.voices.set(voiceId, {
    behavior,
    fingerprint,
    assignment,
    rng,
    periodTicks: Math.max(1, Math.round(periodBeats * TICKS_PER_BEAT)),
    tickOffset: voiceId % TICKS_PER_BEAT,
    lastTriggerTick: -Infinity,
  });
}
```

- [ ] **Step 4: Replace trigger methods with macro-aware methods**

Use:

```js
removeVoice(voiceId) {
  this.engine.setVoiceMacro(voiceId, null);
  this.allocator.release(voiceId);
  this.voices.delete(voiceId);
}

setVoiceMacro(voiceId, macroId) {
  const voice = this.voices.get(voiceId);
  if (!voice) return;
  voice.macroId = macroId ?? null;
  this.engine.setVoiceMacro(voiceId, macroId);
  if (!macroId) this.engine.releaseVoice(voiceId);
}
```

- [ ] **Step 5: Keep root behavior but recompute from assignment**

Use:

```js
setRoot(midi) {
  this.rootMidi = clamp(midi, ROOT_MIN, ROOT_MAX);
  this.field.rootMidi = this.rootMidi;
}

midiForVoice(voice) {
  const { role, octave, detuneCents } = voice.assignment;
  return this.rootMidi + ROLE_SEMITONES[role] + 12 * octave + detuneCents / 100.0;
}
```

- [ ] **Step 6: Replace `_tick()`**

Use:

```js
_tick() {
  const currentTick = this.tick++;
  const activeIds = [...this.voices.keys()].filter((id) => this.voices.get(id).macroId);
  const dt = this.Tone.Time(TICK_SUBDIVISION).toSeconds();
  const gains = this.conductor.update(activeIds, dt);
  for (const id of activeIds) {
    this.engine.setVoiceGain(id, gains.get(id) ?? 0, 0.18);
  }
  for (const id of activeIds) {
    const voice = this.voices.get(id);
    if (!voice) continue;
    if (["pad", "bloom", "drone"].includes(voice.behavior)) {
      if (!this.engine.isVoiceHeld(id)) this.engine.triggerVoice(id, this.midiForVoice(voice), null);
      continue;
    }
    if ((currentTick + voice.tickOffset) % voice.periodTicks !== 0) continue;
    const density = voice.fingerprint?.densityBias ?? 0.35;
    const probability = voice.behavior === "bell" ? 0.18 + density * 0.32 : 0.3 + density * 0.45;
    if (voice.rng() > probability) continue;
    const dur = voice.behavior === "bell" ? 1.8 : 2.4;
    voice.lastTriggerTick = currentTick;
    this.engine.triggerVoice(id, this.midiForVoice(voice), dur);
  }
}
```

- [ ] **Step 7: Run syntax check**

Run:

```powershell
rtk node --check webapp/scheduler.js
```

Expected if Node is available: no syntax errors.

- [ ] **Step 8: Commit**

```powershell
rtk git add webapp/scheduler.js
rtk git commit -m "feat(webapp): drive sampler soundbath with conductor variation"
```

---

### Task 6: Wire Synth Patch Bay To Macros

**Files:**
- Modify: `webapp/main.js`

**Purpose:** Make the two 5x5 arrays mean source-to-macro again. Remove `triggers.js` from Synth mode. Preserve loop-mode `connect_source` behavior.

- [ ] **Step 1: Replace imports and constants**

Change the top imports from:

```js
import { TRIGGER_COLS, TRIGGER_ROWS, triggerPresetId } from "./triggers.js";
```

to:

```js
import { MACRO_COLS, MACRO_ROWS, SOURCE_GRID, SOURCE_ROWS, macroPresetId, sourceForSlot } from "./soundbath_config.js";
import { deriveFingerprint } from "./generative/fingerprint.js";
```

Replace:

```js
const SYNTH_ROW_LABELS = TRIGGER_ROWS;
const SYNTH_SOURCE_ROWS = ["pluck", "pad"];
const SYNTH_SOURCE_INSTRUMENTS = [
  ["piano", "guitar", "tapeguitar", "tapebell", "casio"],
  ["strings", "flute", "clarinet", "casio", "piano"],
];
```

with:

```js
const SYNTH_ROW_LABELS = MACRO_ROWS;
const SYNTH_SOURCE_ROWS = SOURCE_ROWS;
const SYNTH_SOURCE_INSTRUMENTS = SOURCE_GRID;
```

- [ ] **Step 2: Add transpose slider property**

In the constructor after `this.delaySlider = ...`, add:

```js
this.transposeSlider = document.getElementById("transpose-slider");
```

In `applyModeControls()`, after delay:

```js
toggleLabel(this.transposeSlider, !synth);
```

In `ensureSynthEngine()`, after delay:

```js
if (this.transposeSlider) this.synthEngine.setTranspose(parseFloat(this.transposeSlider.value));
```

In `bindControls()`, add:

```js
if (this.transposeSlider) {
  this.transposeSlider.addEventListener("input", (e) => {
    this.synthEngine?.setTranspose(parseFloat(e.target.value));
  });
}
```

- [ ] **Step 3: Store fingerprints when sources are created**

In `finishPendingSource`, add `fingerprint` to the source object:

```js
fingerprint: deriveFingerprint({
  hue: pending.hue,
  sat: pending.sat,
  val: pending.val,
  bpm: pending.bpm,
}),
macroId: null,
```

- [ ] **Step 4: Use shared source config**

Replace `synthSourceForSlot(slot)` body with:

```js
return sourceForSlot(slot, PATCH_GRID_COLS);
```

- [ ] **Step 5: Replace off-grid Synth uncable behavior**

In `onPatchRelease`, replace:

```js
this.scheduler?.setVoiceTrigger(this.dragSourceId, null);
source.row = null;
source.col = null;
```

with:

```js
this.scheduler?.setVoiceMacro(this.dragSourceId, null);
source.row = null;
source.col = null;
source.macroId = null;
```

- [ ] **Step 6: Preserve macro when moving a source**

In `assignSourceToOutput`, replace the `previousTrigger` calculation with:

```js
const previousMacroId =
  this.mode === "synth" && source.row !== null && source.col !== null
    ? macroPresetId(source.row, source.col)
    : source.macroId;
```

When creating the voice, pass fingerprint:

```js
this.synthEngine?.createVoice(sourceId, {
  instrument: config.instrument,
  behavior: config.behavior,
  fingerprint: source.fingerprint,
});
this.scheduler?.addVoice(sourceId, {
  behavior: config.behavior,
  fingerprint: source.fingerprint,
});
if (previousMacroId) {
  this.scheduler?.setVoiceMacro(sourceId, previousMacroId);
  const [, macroRow, macroCol] = previousMacroId.match(/^(.+)_(\d+)$/) ?? [];
  if (macroRow) {
    source.row = MACRO_ROWS.indexOf(macroRow);
    source.col = Number(macroCol) - 1;
    source.macroId = previousMacroId;
  }
}
```

Remove `semitoneOffset` and `centsOffset` from the `scheduler.addVoice` call.

- [ ] **Step 7: Rename and replace routing method**

Rename `routeSourceToTrigger(sourceId, cell)` to `routeSourceToMacro(sourceId, cell)` and use:

```js
routeSourceToMacro(sourceId, cell) {
  const source = this.sources.get(sourceId);
  if (!source || source.slot === null) return;
  const row = cell.row;
  const col = cell.col;
  if (this.mode === "synth") {
    const macroId = macroPresetId(row, col);
    this.scheduler?.setVoiceMacro(sourceId, macroId);
    source.row = row;
    source.col = col;
    source.macroId = macroId;
    return;
  }
  const engine =
    this.mode === "loop" && row === TAPE_ROW_INDEX && col === 4
      ? "reverb"
      : PATCH_ROW_ENGINES[row];
  this.worker.postMessage({
    type: "connect_source",
    sourceId,
    engine,
    row,
    col,
    outputSlot: source.slot,
  });
  source.row = row;
  source.col = col;
}
```

Replace call sites of `this.routeSourceToTrigger(...)` with `this.routeSourceToMacro(...)`.

- [ ] **Step 8: Update labels**

Replace:

```js
return this.mode === "synth" ? TRIGGER_COLS[col] : VARIANT_COL_LABELS[col];
```

with:

```js
return this.mode === "synth" ? MACRO_COLS[col] : VARIANT_COL_LABELS[col];
```

Update `sourceShortLabel(source)` final label to use macro names:

```js
return `${bpm} - ${output} -> ${this.rowLabels()[source.row]} ${this.inputColLabel(source.col)}`;
```

This line already has the correct shape; keep it after the row label change.

- [ ] **Step 9: Add macro-routing static expectations**

Add this test to `audio_prototype/tests/test_webapp_static.py` after `test_sampler_macro_soundbath_grid_config_is_5x5_and_sample_only`:

```python
def test_synth_mode_routes_patch_cables_to_macro_grid():
    main_js = (ROOT / "webapp" / "main.js").read_text()

    assert 'routeSourceToMacro(sourceId, cell)' in main_js
    assert 'routeSourceToTrigger' not in main_js
    assert 'TRIGGER_ROWS' not in main_js
    assert 'TRIGGER_COLS' not in main_js
    assert 'triggerPresetId' not in main_js
    assert 'const SYNTH_ROW_LABELS = MACRO_ROWS;' in main_js
    assert 'const SYNTH_SOURCE_ROWS = SOURCE_ROWS;' in main_js
    assert 'const SYNTH_SOURCE_INSTRUMENTS = SOURCE_GRID;' in main_js
    assert 'this.scheduler?.setVoiceMacro(sourceId, macroId);' in main_js
```

- [ ] **Step 10: Run targeted static test**

Run:

```powershell
rtk python -m pytest audio_prototype/tests/test_webapp_static.py::test_synth_mode_routes_patch_cables_to_macro_grid -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```powershell
rtk git add webapp/main.js audio_prototype/tests/test_webapp_static.py
rtk git commit -m "feat(webapp): route synth patch cables to macro grid"
```

---

### Task 7: Add Global Transpose UI

**Files:**
- Modify: `webapp/index.html`

**Purpose:** Add the single global pitch shift control requested by the user. It should be a global effect before the wash, not normal sampler pitch selection.

- [ ] **Step 1: Add slider markup**

In `webapp/index.html`, in the Patch Bay `.section-header`, after Delay, add:

```html
<label class="patch-control">Transpose <input id="transpose-slider" type="range" min="-12" max="12" step="0.01" value="0" /></label>
```

- [ ] **Step 2: Add transpose static expectation**

Add this test to `audio_prototype/tests/test_webapp_static.py` after the macro-routing test:

```python
def test_synth_mode_has_global_transpose_control():
    index_html = (ROOT / "webapp" / "index.html").read_text()
    main_js = (ROOT / "webapp" / "main.js").read_text()

    assert 'id="transpose-slider"' in index_html
    assert 'this.transposeSlider = document.getElementById("transpose-slider");' in main_js
    assert 'this.synthEngine.setTranspose(parseFloat(this.transposeSlider.value))' in main_js
    assert 'this.synthEngine?.setTranspose(parseFloat(e.target.value));' in main_js
```

- [ ] **Step 3: Run targeted static test**

Run:

```powershell
rtk python -m pytest audio_prototype/tests/test_webapp_static.py::test_synth_mode_has_global_transpose_control -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
rtk git add webapp/index.html audio_prototype/tests/test_webapp_static.py
rtk git commit -m "feat(webapp): add global transpose control"
```

---

### Task 8: Static Test Cleanup For Old Trigger Expectations

**Files:**
- Modify: `audio_prototype/tests/test_webapp_static.py`

**Purpose:** Existing static tests still refer to old method names like `routeSourceToEffect` and older 3-row Synth assumptions. Update them to the new macro-grid names without weakening loop-mode coverage.

- [ ] **Step 1: Update `test_sources_are_left_of_patch_bay_and_drag_routed_explicitly`**

In that test, replace:

```python
assert "routeSourceToEffect" in main_js
```

with:

```python
assert "routeSourceToMacro" in main_js
```

Replace:

```python
assign_body = main_js[
    main_js.index("assignSourceToOutput(sourceId, slot)") :
    main_js.index("routeSourceToEffect(sourceId, cell)")
]
```

with:

```python
assign_body = main_js[
    main_js.index("assignSourceToOutput(sourceId, slot)") :
    main_js.index("routeSourceToMacro(sourceId, cell)")
]
```

- [ ] **Step 2: Run all webapp static tests**

Run:

```powershell
rtk python -m pytest audio_prototype/tests/test_webapp_static.py -q
```

Expected: PASS, with Node-related tests skipped if Node is not installed.

- [ ] **Step 3: Commit**

```powershell
rtk git add audio_prototype/tests/test_webapp_static.py
rtk git commit -m "test(webapp): update static checks for macro patch routing"
```

---

### Task 9: Browser Smoke And Tuning Pass

**Files:**
- Modify: `webapp/modifiers.js`
- Modify: `webapp/tone_engine.js`
- Modify: `webapp/scheduler.js`

**Purpose:** The macro values are necessarily musical. Do a short browser pass to avoid landing a technically correct but harsh/flat bath.

- [ ] **Step 1: Start a local server**

Run:

```powershell
cd webapp
rtk python -m http.server 8000
```

Expected: server listens at `http://localhost:8000/`.

- [ ] **Step 2: Manual smoke matrix**

In the browser:

1. Open `http://localhost:8000/`.
2. Confirm Synth mode loads without Pyodide status delay.
3. Send five scans with different BPM values.
4. Place sources in `pluck/piano`, `pad/strings`, `bloom/flute`, `bell/tapebell`, `drone/casio`.
5. Cable those sources to `veil I`, `shimmer III`, `flutter II`, `scatter V`, `space IV`.
6. Press Play.
7. Confirm every source is sample-based and no cell is silent because it references a missing instrument name.
8. Raise/lower Reverb and Delay; confirm they affect the whole bath.
9. Sweep Transpose from `0` to `+12`, then `-12`, then `0`; confirm it changes the whole bath and ramps without an obvious click.
10. Leave it running for at least 3 minutes; confirm some voices ebb into foreground/background.
11. Move one source to another source cell; confirm its macro cable is preserved.
12. Drag one macro cable off-grid; confirm that voice releases and the global wash tail continues.

- [ ] **Step 3: Tune only bounded constants**

If harshness/clipping occurs, tune these exact values first:

- In `webapp/tone_engine.js`, lower master gain from `-6 dB` to `-9 dB`.
- In `webapp/modifiers.js`, reduce `scatter` delay `wet` values by `0.05`.
- In `webapp/modifiers.js`, reduce `shimmer` shadow `gain` values by `0.04`.
- In `webapp/scheduler.js`, lower pluck/bell probability constants by `0.08`.

Do not add new architecture during this tuning task.

- [ ] **Step 4: Run static tests**

Run:

```powershell
rtk python -m pytest audio_prototype/tests/test_webapp_static.py -q
```

Expected: PASS, with Node-related tests skipped if Node is not installed.

- [ ] **Step 5: Commit**

```powershell
rtk git add webapp/modifiers.js webapp/tone_engine.js webapp/scheduler.js
rtk git commit -m "fix(webapp): tune sampler macro soundbath defaults"
```

If no tuning edits were needed, skip this commit and record that in the final implementation notes.

---

### Task 10: Documentation Handoff

**Files:**
- Modify: `AGENTS.md`
- Modify: `webapp/AGENTS.md`

**Purpose:** Keep the living handoff current after the implementation lands.

- [ ] **Step 1: Update root `AGENTS.md` pickup note**

Update the top section to say:

```markdown
- **Status:**       Prototype — the desktop app (audio_prototype/main.py) has Loop + Synth tabs. The web app Synth mode now uses a sample-only 5x5 source grid cabled to a Tone-native 5x5 macro grid (`veil/shimmer/flutter/scatter/space`), with scan fingerprints, conductor-driven ebb/flow, global transpose, and one global clickbath-style reverb+delay wash. Loop mode still runs through the Pyodide worker path and `worker.js` is untouched.
- **Last session:** 2026-07-23 — implemented the sampler macro soundbath web design per docs/superpowers/plans/2026-07-23-sampler-macro-soundbath.md (spec: docs/superpowers/specs/2026-07-23-sampler-macro-soundbath-design.md).
- **Next up:**
  - Manual browser tuning over several minutes with dense 25-patch scenes.
  - Improve sampler loop/crossfade behavior for drone cells if any source exposes loop seams.
  - Consider source-row drag-to-jack assignment, cable-click selection/removal, and persisting patches.
  - Wire hardware finger-scan input into the Synth path.
  - Document the firmware serial message shape (base64 JPEG framing).
```

- [ ] **Step 2: Update `webapp/AGENTS.md` Synth notes**

Replace the web app description with:

```markdown
## What it is
Browser port of the desktop patch-bay with two modes:
- Loop mode: 25 source jacks -> 5x5 effects matrix through `worker.js`/Pyodide.
- Synth mode: 5x5 sample source grid (`pluck/pad/bloom/bell/drone`) -> 5x5 Tone-native macro grid (`veil/shimmer/flutter/scatter/space`) through `tone_engine.js`.

Keep constants in sync with the web modules:
- Synth source/macro rows live in `webapp/soundbath_config.js`.
- Clickbath sample maps live in `webapp/generative/instrument-maps.js`.
- Finger-scan gamut `FINGER_HUE/SAT/VAL_*` lives in `main.js` and feeds `generative/fingerprint.js`.
```

- [ ] **Step 3: Run final static tests**

Run:

```powershell
rtk python -m pytest audio_prototype/tests/test_webapp_static.py -q
```

Expected: PASS, with Node-related tests skipped if Node is not installed.

- [ ] **Step 4: Commit**

```powershell
rtk git add AGENTS.md webapp/AGENTS.md
rtk git commit -m "docs: update sampler macro soundbath handoff"
```

---

## Self-Review

**Spec coverage:** Task 1 implements the 25-cell source/macro invariants. Task 2 implements scan fingerprint mapping. Task 3 implements Tone-native macro presets with honest labels and no per-voice reverb/pitch shift. Task 4 implements sampler macro graph, global transpose before wash, global delay/reverb, limiter, and voice lifecycle. Task 5 implements conductor-driven ebb/flow and source behavior variation. Task 6 restores the two-array patch-cable interaction and removes the trigger grid from Synth mode. Task 7 adds the global Transpose UI. Task 8 updates static tests for the new behavior. Task 9 covers browser/manual tuning and CPU/headroom checks. Task 10 updates handoff docs.

**Placeholder scan:** No TBD/TODO placeholders. Tuning ranges and exact fallback edits are specified. Browser-only audio validation is explicitly manual because Tone.js audio cannot be meaningfully verified by the existing Python tests.

**Type consistency:** The plan uses `deriveFingerprint`, `SOURCE_ROWS`, `SOURCE_GRID`, `MACRO_ROWS`, `MACRO_COLS`, `macroPresetId`, `sourceForSlot`, `createMacroNode`, `setVoiceMacro`, `setTranspose`, and `isVoiceHeld` consistently across modules. `main.js` calls `scheduler.setVoiceMacro`, and the scheduler delegates to `engine.setVoiceMacro`. The source object stores `fingerprint` and `macroId` consistently.
