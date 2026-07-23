# Tone.js Hybrid Synth — MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A browser synth whose audio runs on native Web Audio via Tone.js — sampled instruments (pluck/pad/bloom) through per-voice modifier chains into a global reverb+delay wash — driven by our generative brain (harmony/allocator/conductor) ported to JS. Clickbath-clean, offline-capable, reusing the existing `webapp/` patch bay.

**Architecture:** `webapp/generative/{harmony,allocator,conductor}.js` are pure, seed-deterministic ports (unit-tested with `node --test`). `webapp/tone_engine.js` owns the Tone.js graph and per-voice lifecycle; `webapp/scheduler.js` drives triggers/gains from the brain via `Tone.Transport`. `webapp/main.js` routes **synth-mode** patch-bay actions to the engine (loop mode stays on the Pyodide worker, untouched). Tone.js 14.7.77 is vendored in `webapp/vendor/`.

**Tech Stack:** Vanilla JS (ES modules), Tone.js 14.7.77, Web Audio, `node --test` for pure-logic tests. Spec: `docs/superpowers/specs/2026-07-23-tonejs-hybrid-synth-design.md`.

## Global Constraints

- Work in `webapp/`. Tests run from repo root: `node --test webapp/generative/`.
- Node's built-in test runner only (`node:test`, `node:assert`) — **no npm deps**.
- ES modules (`import`/`export`) throughout the new JS. `.test.js` files beside sources.
- **Pure-logic modules (`generative/*`) must NOT import Tone.js** — they are audio-agnostic and headless-testable.
- Determinism: use the provided `mulberry32(seed)` PRNG (below) wherever the Python used `np.random.default_rng` — same seeding recipe → reproducible.
- Tone.js is vendored and loaded locally (no CDN). Pin **14.7.77**.
- Clickbath samples stay gitignored (`webapp/audio/clickbath/`); never committed.
- MIDI convention C4 = 60. Root range C2–C4 (36–60). Reverb slider 0–1.5, delay 0–1.
- Prefix shell/git with `rtk`. Conventional Commits; end messages with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Do NOT touch loop mode, `worker.js`, or the Python engine.

## Shared PRNG (used by Tasks 2–4)

Every generative module imports this from `webapp/generative/rng.js`:

```js
// Deterministic PRNG (mulberry32). Mirrors the role of np.random.default_rng.
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export const uniform = (rng, lo, hi) => lo + (hi - lo) * rng();
```

---

### Task 1: Vendor Tone.js, stage samples, note-maps module

**Files:**
- Create: `webapp/vendor/tone.js` (downloaded Tone.js 14.7.77 UMD build)
- Create: `webapp/generative/instrument-maps.js`
- Create/modify: `.gitignore` (add `webapp/audio/clickbath/`)
- Create: `webapp/audio/clickbath/*.wav` (staged from the existing gitignored assets — NOT committed)
- Test: manual (files present; `node --check`)

**Interfaces:**
- Produces: `webapp/vendor/tone.js` loadable via `<script>` (exposes global `Tone`); `INSTRUMENT_NOTE_URLS` mapping instrument → `{noteName: filename}` for `Tone.Sampler`.

- [ ] **Step 1: Vendor Tone.js**

```bash
mkdir -p webapp/vendor
curl -L -o webapp/vendor/tone.js https://unpkg.com/tone@14.7.77/build/Tone.js
```
Verify it downloaded (non-empty, contains `Tone`): `grep -c "Tone" webapp/vendor/tone.js` > 0.

- [ ] **Step 2: Stage the samples (gitignored)**

```bash
mkdir -p webapp/audio/clickbath
cp audio_prototype/assets/clickbath/*.wav webapp/audio/clickbath/
```
Add to `.gitignore` (repo root), after the existing `audio_prototype/assets/clickbath/` line:
```
webapp/audio/clickbath/
```
Confirm ignored: `rtk git status --short | grep -i "webapp/audio/clickbath" || echo ok-ignored`.

- [ ] **Step 3: Write the note-maps module**

`webapp/generative/instrument-maps.js` — the captured clickbath maps as Tone note names (C4=60). `Tone.Sampler` takes `{ "C4": "piano_60.wav", ... }` with `baseUrl`.

```js
// Clickbath multisample note maps (MIDI note -> local wav under audio/clickbath/).
// Tone.Sampler wants note-name keys; we expose both the MIDI list and the
// note-name->file map it needs.
export const INSTRUMENT_MIDIS = {
  piano: [48, 60, 72, 84],
  guitar: [48, 60, 72],
  tapeguitar: [36, 48, 60],
  tapebell: [48, 60, 72, 84],
  casio: [48, 60, 72, 84],
  strings: [48, 60, 72, 84],
  flute: [60, 72, 84],
  clarinet: [60, 72, 84],
};

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export function midiToNoteName(midi) {
  return `${NOTE_NAMES[midi % 12]}${Math.floor(midi / 12) - 1}`;
}

// instrument -> { "C4": "piano_60.wav", ... } for Tone.Sampler({ urls, baseUrl }).
export const INSTRUMENT_NOTE_URLS = Object.fromEntries(
  Object.entries(INSTRUMENT_MIDIS).map(([inst, midis]) => [
    inst,
    Object.fromEntries(midis.map((m) => [midiToNoteName(m), `${inst}_${m}.wav`])),
  ])
);
export const CLICKBATH_BASE_URL = "audio/clickbath/";
```

- [ ] **Step 4: Verify**

Run: `node --check webapp/generative/instrument-maps.js && node -e "import('./webapp/generative/instrument-maps.js').then(m=>console.log(m.INSTRUMENT_NOTE_URLS.piano))"`
Expected: prints `{ C3: 'piano_48.wav', C4: 'piano_60.wav', C5: 'piano_72.wav', C6: 'piano_84.wav' }` (no error).

- [ ] **Step 5: Commit** (samples excluded by gitignore)

```bash
rtk git add webapp/vendor/tone.js webapp/generative/instrument-maps.js .gitignore
rtk git commit -m "feat(webapp): vendor Tone.js 14.7.77 + clickbath note maps"
```

---

### Task 2: `harmony.js` — HarmonicField port

**Files:**
- Create: `webapp/generative/harmony.js`
- Test: `webapp/generative/harmony.test.js`

**Interfaces:**
- Consumes: `rng.js`.
- Produces: `midiToHz(midi)`, `ROLE_SEMITONES`, `ROLE_WEIGHTS`, `PENTATONIC`, and `class HarmonicField(rootMidi=48, tensionEnabled=true)` with `roles()`, `weightedRole(rng)`, `semitoneForRole(role)`, `midiForRole(role, octaveOffset=0)`, and a settable `rootMidi`.

- [ ] **Step 1: Write the failing tests**

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { mulberry32 } from "./rng.js";
import { HarmonicField, ROLE_SEMITONES, midiToHz } from "./harmony.js";

test("midiForRole adds root + role semitone + octaves", () => {
  const f = new HarmonicField(62);
  assert.equal(f.midiForRole("root"), 62);
  assert.equal(f.midiForRole("fifth"), 69);
  assert.equal(f.midiForRole("fifth", 1), 81);
});

test("midiToHz matches A440", () => {
  assert.ok(Math.abs(midiToHz(69) - 440.0) < 1e-6);
});

test("weightedRole is seed-deterministic and returns a valid role", () => {
  const f = new HarmonicField(48);
  const a = mulberry32(7), b = mulberry32(7);
  for (let i = 0; i < 20; i++) {
    const r = f.weightedRole(a);
    assert.equal(r, f.weightedRole(b));
    assert.ok(Object.prototype.hasOwnProperty.call(ROLE_SEMITONES, r));
  }
});

test("tensionEnabled=false drops the tension role", () => {
  const f = new HarmonicField(48, false);
  assert.ok(!f.roles().includes("tension"));
});
```

- [ ] **Step 2: Run — expect fail**

Run: `node --test webapp/generative/harmony.test.js`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `harmony.js`**

```js
// Port of soundscape_harmony.py's HarmonicField (spec 6/17).
export const PENTATONIC = [0, 2, 5, 7, 10];
export const ROLE_SEMITONES = { root: 0, fifth: 7, fourth: 5, ninth: 2, seventh: 10, tension: 1 };
export const ROLE_WEIGHTS = { root: 0.32, fifth: 0.24, fourth: 0.16, ninth: 0.14, seventh: 0.1, tension: 0.04 };

export function midiToHz(midi) {
  return 440.0 * Math.pow(2.0, (midi - 69.0) / 12.0);
}

export class HarmonicField {
  constructor(rootMidi = 48, tensionEnabled = true) {
    this.rootMidi = rootMidi;
    this.tensionEnabled = tensionEnabled;
  }
  roles() {
    const all = Object.keys(ROLE_WEIGHTS);
    return this.tensionEnabled ? all : all.filter((r) => r !== "tension");
  }
  weightedRole(rng) {
    const roles = this.roles();
    const weights = roles.map((r) => ROLE_WEIGHTS[r]);
    const total = weights.reduce((a, b) => a + b, 0);
    let x = rng() * total;
    for (let i = 0; i < roles.length; i++) {
      x -= weights[i];
      if (x <= 0) return roles[i];
    }
    return roles[roles.length - 1];
  }
  semitoneForRole(role) {
    return ROLE_SEMITONES[role];
  }
  midiForRole(role, octaveOffset = 0) {
    return this.rootMidi + this.semitoneForRole(role) + 12 * octaveOffset;
  }
}
```

- [ ] **Step 4: Run — expect pass**

Run: `node --test webapp/generative/harmony.test.js`  → PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add webapp/generative/rng.js webapp/generative/harmony.js webapp/generative/harmony.test.js
rtk git commit -m "feat(webapp): port HarmonicField + seeded RNG to JS"
```

---

### Task 3: `allocator.js` — PitchAllocator port

**Files:**
- Create: `webapp/generative/allocator.js`
- Test: `webapp/generative/allocator.test.js`

**Interfaces:**
- Consumes: `harmony.js`, `rng.js`.
- Produces: `bandForHz(hz)`, `REGISTER_LIMITS`, `DETUNE_CENTS_RANGE`, and `class PitchAllocator(field)` with `allocate(vid, rng, density, detuneClass="foreground") -> {role, octave, detuneCents, midi, band}` and `release(vid)`.

- [ ] **Step 1: Write the failing tests**

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { mulberry32 } from "./rng.js";
import { HarmonicField, ROLE_SEMITONES } from "./harmony.js";
import { PitchAllocator, bandForHz } from "./allocator.js";

test("bandForHz classifies", () => {
  assert.equal(bandForHz(60), "sub");
  assert.equal(bandForHz(300), "low");
  assert.equal(bandForHz(1000), "mid");
});

test("allocate returns a coherent assignment", () => {
  const alloc = new PitchAllocator(new HarmonicField(48));
  const a = alloc.allocate(1, mulberry32(1), 0.1, "foreground");
  assert.ok(Object.prototype.hasOwnProperty.call(ROLE_SEMITONES, a.role));
  assert.ok(a.octave >= 0);
  assert.ok(Math.abs(a.detuneCents) <= 4.0 + 1e-9); // foreground detune limit
  const expected = 48 + ROLE_SEMITONES[a.role] + 12 * a.octave + a.detuneCents / 100.0;
  assert.ok(Math.abs(a.midi - expected) < 1e-9);
});

test("allocate is seed-deterministic", () => {
  const f1 = new HarmonicField(48), f2 = new HarmonicField(48);
  const a = new PitchAllocator(f1).allocate(3, mulberry32(9), 0.5);
  const b = new PitchAllocator(f2).allocate(3, mulberry32(9), 0.5);
  assert.deepEqual(a, b);
});
```

- [ ] **Step 2: Run — expect fail.** `node --test webapp/generative/allocator.test.js`

- [ ] **Step 3: Implement `allocator.js`**

```js
// Port of soundscape_harmony.py's register logic + PitchAllocator.
import { midiToHz } from "./harmony.js";
import { uniform } from "./rng.js";

const REGISTER_BANDS = [
  ["sub", 40.0, 120.0], ["low", 120.0, 500.0], ["mid", 500.0, 2000.0],
  ["high", 2000.0, 6000.0], ["air", 6000.0, 14000.0],
];
export const REGISTER_LIMITS = { sub: 2, low: 3, mid: 5, high: 7, air: 8 };
export const DETUNE_CENTS_RANGE = { foreground: 4.0, background: 8.0, granular: 15.0, texture: 30.0 };

export function bandForHz(hz) {
  for (const [name, lo, hi] of REGISTER_BANDS) if (hz >= lo && hz < hi) return name;
  return hz >= REGISTER_BANDS[REGISTER_BANDS.length - 1][2] ? "air" : "sub";
}

export class PitchAllocator {
  constructor(field) {
    this.field = field;
    this._counts = Object.fromEntries(REGISTER_BANDS.map(([n]) => [n, 0]));
    this._byVoice = new Map();
  }
  _isCrowded(band) { return this._counts[band] >= REGISTER_LIMITS[band]; }
  _register(vid, band) { this.release(vid); this._counts[band] += 1; this._byVoice.set(vid, band); }
  release(vid) {
    const band = this._byVoice.get(vid);
    if (band !== undefined) { this._counts[band] -= 1; this._byVoice.delete(vid); }
  }
  allocate(vid, rng, density, detuneClass = "foreground") {
    const role = this.field.weightedRole(rng);
    let octave = 0, midi, band;
    let placed = false;
    for (let i = 0; i < 4; i++) {
      midi = this.field.midiForRole(role, octave);
      band = bandForHz(midiToHz(midi));
      if (!this._isCrowded(band)) { placed = true; break; }
      octave += 1;
    }
    if (!placed) {
      octave = 1 + Math.floor(rng() * 2); // rng.integers(1,3)
      midi = this.field.midiForRole(role, octave);
      band = bandForHz(midiToHz(midi));
    }
    if (density > 0.6 && (band === "sub" || band === "low")) {
      octave += 1;
      midi = this.field.midiForRole(role, octave);
      band = bandForHz(midiToHz(midi));
    }
    const limit = DETUNE_CENTS_RANGE[detuneClass] ?? DETUNE_CENTS_RANGE.foreground;
    const detuneCents = uniform(rng, -limit, limit);
    this._register(vid, band);
    return { role, octave, detuneCents, band, midi: midi + detuneCents / 100.0 };
  }
}
```

- [ ] **Step 4: Run — expect pass.** `node --test webapp/generative/allocator.test.js`

- [ ] **Step 5: Commit**

```bash
rtk git add webapp/generative/allocator.js webapp/generative/allocator.test.js
rtk git commit -m "feat(webapp): port PitchAllocator to JS"
```

---

### Task 4: `conductor.js` — VoiceConductor port

**Files:**
- Create: `webapp/generative/conductor.js`
- Test: `webapp/generative/conductor.test.js`

**Interfaces:**
- Consumes: `rng.js`.
- Produces: `ROLE_GAIN`, `assignVoiceRoles(orderIds)`, and `class VoiceConductor({seed, minPeriod, maxPeriod, swellMin, swellDepth, smoothTau})` with `update(activeIds, dtSeconds) -> Map(vid -> gain)`. (This version is time-based: pass `dtSeconds` per call rather than frames+samplerate — cleaner for a Tone.Transport loop.)

- [ ] **Step 1: Write the failing tests**

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { VoiceConductor, ROLE_GAIN, assignVoiceRoles } from "./conductor.js";

test("assignVoiceRoles respects budgets (foreground first)", () => {
  const roles = assignVoiceRoles([1, 2, 3, 4, 5, 6, 7]);
  assert.equal(roles.get(1), "foreground");
  assert.ok(["foreground", "midground", "background", "dormant"].includes(roles.get(7)));
});

test("gains are bounded and present for active ids", () => {
  const c = new VoiceConductor({ seed: 1 });
  const g = c.update([1, 2, 3], 0.05);
  assert.deepEqual([...g.keys()].sort(), [1, 2, 3]);
  const hi = Math.max(...Object.values(ROLE_GAIN));
  for (const v of g.values()) assert.ok(v >= 0 && v <= hi + 1e-9);
});

test("state is GC'd for absent ids", () => {
  const c = new VoiceConductor({ seed: 1 });
  c.update([1, 2], 0.05);
  c.update([2], 0.05);
  assert.ok(!c._gain.has(1));
});

test("gains evolve over ~40 s", () => {
  const c = new VoiceConductor({ seed: 1 });
  const ids = [1, 2, 3, 4, 5, 6, 7, 8];
  const first = c.update(ids, 0.05).get(1);
  let last = first;
  for (let i = 0; i < 900; i++) last = c.update(ids, 0.05).get(1);
  assert.ok(Math.abs(last - first) > 0.05);
});

test("deterministic under seed", () => {
  const a = new VoiceConductor({ seed: 7 }), b = new VoiceConductor({ seed: 7 });
  for (let i = 0; i < 30; i++) {
    assert.deepEqual([...a.update([1, 2, 3], 0.05)], [...b.update([1, 2, 3], 0.05)]);
  }
});
```

- [ ] **Step 2: Run — expect fail.** `node --test webapp/generative/conductor.test.js`

- [ ] **Step 3: Implement `conductor.js`**

```js
// Port of soundscape_conductor.py + soundscape_density.py role budgets.
import { mulberry32, uniform } from "./rng.js";

export const ROLE_GAIN = { foreground: 1.0, midground: 0.55, background: 0.28, dormant: 0.0 };
const FG = 5, MG = 8, BG = 8; // spec-9 upper budgets

export function assignVoiceRoles(orderIds) {
  const roles = new Map();
  const n = orderIds.length;
  const fgN = Math.min(n, FG);
  const mgN = Math.min(Math.max(0, n - fgN), MG);
  const bgN = Math.min(Math.max(0, n - fgN - mgN), BG);
  orderIds.forEach((vid, i) => {
    if (i < fgN) roles.set(vid, "foreground");
    else if (i < fgN + mgN) roles.set(vid, "midground");
    else if (i < fgN + mgN + bgN) roles.set(vid, "background");
    else roles.set(vid, "dormant");
  });
  return roles;
}

export class VoiceConductor {
  constructor({ seed = 0, minPeriod = 20, maxPeriod = 50, swellMin = 0.35, swellDepth = 0.65, smoothTau = 0.6 } = {}) {
    Object.assign(this, { seed, minPeriod, maxPeriod, swellMin, swellDepth, smoothTau });
    this._t = 0;
    this._params = new Map(); // vid -> {rate, phase}
    this._gain = new Map();   // vid -> smoothed gain
  }
  _paramsFor(vid) {
    let p = this._params.get(vid);
    if (!p) {
      const rng = mulberry32(this.seed * 1000003 + vid);
      const period = uniform(rng, this.minPeriod, this.maxPeriod);
      p = { rate: 1 / period, phase: uniform(rng, 0, 1) };
      this._params.set(vid, p);
    }
    return p;
  }
  _activity(vid) {
    const { rate, phase } = this._paramsFor(vid);
    return 0.5 + 0.5 * Math.sin(2 * Math.PI * (this._t * rate + phase));
  }
  update(activeIds, dt) {
    const keep = new Set(activeIds);
    for (const k of [...this._params.keys()]) if (!keep.has(k)) this._params.delete(k);
    for (const k of [...this._gain.keys()]) if (!keep.has(k)) this._gain.delete(k);
    const out = new Map();
    if (activeIds.length === 0) { this._t += dt; return out; }
    const activity = new Map(activeIds.map((v) => [v, this._activity(v)]));
    const ranked = [...activeIds].sort((a, b) => activity.get(b) - activity.get(a));
    const roles = assignVoiceRoles(ranked);
    const alpha = 1 - Math.exp(-dt / this.smoothTau);
    for (const vid of activeIds) {
      const target = ROLE_GAIN[roles.get(vid)] * (this.swellMin + this.swellDepth * activity.get(vid));
      let current = this._gain.has(vid) ? this._gain.get(vid) : target;
      current += alpha * (target - current);
      this._gain.set(vid, current);
      out.set(vid, current);
    }
    this._t += dt;
    return out;
  }
}
```

- [ ] **Step 4: Run — expect pass.** `node --test webapp/generative/conductor.test.js`

- [ ] **Step 5: Commit**

```bash
rtk git add webapp/generative/conductor.js webapp/generative/conductor.test.js
rtk git commit -m "feat(webapp): port VoiceConductor to JS"
```

---

### Task 5: `tone_engine.js` — audio graph + voice lifecycle

**Files:**
- Create: `webapp/tone_engine.js`
- Test: manual (browser) + `node --check webapp/tone_engine.js`

**Interfaces:**
- Consumes: global `Tone`; `instrument-maps.js`; `harmony.js`.
- Produces: `class ToneEngine` with:
  - `async init()` — create master chain, preload `Tone.Buffers` for all instruments.
  - `setReverb(amount 0..1.5)`, `setDelay(amount 0..1)`, `setRoot(midiFloat)` (ramped), `resume()`, `pause()`, `get paused()`.
  - `createVoice(voiceId, {instrument, behavior, hue, sat, val})` — builds the per-voice source chain, silent until a modifier is set.
  - `setVoiceModifier(voiceId, modifierId|null)` — build/replace/clear the per-voice modifier insert; connect the voice to master when it first gets a modifier (silent-until-cabled).
  - `setVoiceGain(voiceId, gain, rampSeconds)` — ramp the voice `Tone.Volume`.
  - `triggerVoice(voiceId, midi, durationSeconds|null)` — trigger/hold a note (used by the scheduler).
  - `releaseVoice(voiceId)` (note-off for held voices), `disposeVoice(voiceId)`.
  - exposes `voices` (Map) for the scheduler.

**Design notes (implement per spec §Audio graph):**
- Master chain (built in `init`):
  ```js
  this.master = new Tone.Gain(Tone.dbToGain(-6));           // headroom trim
  this.delay = new Tone.FeedbackDelay({ delayTime: 0.4, feedback: 0.5, wet: 0 });
  this.reverb = new Tone.Reverb({ decay: 8, wet: 0 });
  this.master.chain(this.delay, this.reverb, Tone.Destination);
  ```
  `setReverb(a)`/`setDelay(a)` → `this.reverb.wet.rampTo(clamp(a,0,1.5),0.05)` / `this.delay.wet.rampTo(clamp(a,0,1),0.05)`.
- Preload buffers once: `this.buffers = new Tone.Buffers(flatMapOf(INSTRUMENT_NOTE_URLS), { baseUrl: CLICKBATH_BASE_URL })`; await `Tone.loaded()`.
- **Per-voice chain** (`createVoice`): build a `Tone.Sampler` for the instrument (referencing preloaded URLs; envelope by behavior — pluck: attack 0.005/release 1.5; pad: attack 0.4/release 2.0; bloom: attack 1.5/release 3.0) → a `Tone.PitchShift` **glide node** (for the held-note root glide; 0 semitones by default) → `Tone.Volume` (start at `-Infinity`/muted) → NOT yet connected to master. Store `{sampler, glide, volume, modifier: null, behavior, instrument, held: false}`.
- **Held-note root glide:** the engine tracks `this.rootMidi` and each voice's assigned base MIDI. On `setRoot(newRoot)`, for **held** (pad/bloom/drone) voices, ramp the voice's `glide.pitch` to `(newRoot - voiceBaseRoot)` semitones over ~0.4 s so the sounding note bends; for triggered voices, the next trigger simply uses the new root (scheduler computes pitch). Store each voice's `baseRoot` = the root at trigger time.
- **setVoiceModifier:** if `modifierId` and the voice has no modifier yet → create the modifier node (Task 7 factory), insert it between `glide` and `volume`, and connect `volume → master` (voice becomes audible). If replacing → dispose old node, insert new (note envelope masks it). If `null` → disconnect `volume` from master and dispose the modifier (voice silent again).
- **triggerVoice:** pluck/bells → `sampler.triggerAttackRelease(Tone.Frequency(midi,"midi"), dur)`; pad/bloom → `sampler.triggerAttack(...)` and set `held=true` (release on `releaseVoice`).
- **resume/pause:** `await Tone.start()` on first resume; `Tone.Transport.start()/pause()`. `paused` reflects transport state.

- [ ] **Step 1: Implement `tone_engine.js`** per the interfaces + design notes above. (No unit test — Tone.js needs a browser AudioContext.)

- [ ] **Step 2: Static check.** Run: `node --check webapp/tone_engine.js` → no syntax errors.

- [ ] **Step 3: Commit**

```bash
rtk git add webapp/tone_engine.js
rtk git commit -m "feat(webapp): Tone.js engine (master wash, per-voice sampler chains, root glide)"
```

---

### Task 6: `scheduler.js` — generative trigger/gain loop

**Files:**
- Create: `webapp/scheduler.js`
- Test: manual + `node --check`

**Interfaces:**
- Consumes: `harmony.js`, `allocator.js`, `conductor.js`, `rng.js`; a `ToneEngine`.
- Produces: `class Scheduler(engine, {seed})` with `addVoice(voiceId, {behavior, bpm})`, `removeVoice(voiceId)`, `setRoot(midi)`, `start()`, `stop()`. Internally holds a `HarmonicField`, `PitchAllocator`, `VoiceConductor`, and a `Tone.Loop`.

**Design notes:**
- On `addVoice`: allocate a pitch assignment (`allocator.allocate(id, mulberry32(id), density, detuneClass)`), store `{behavior, bpm, assignment, lastTriggerBeat}`. Density = `min(1, activeCount/20)`.
- `Tone.Loop` at `"16n"`: each tick, `dt = Tone.Time("16n").toSeconds()`; `gains = conductor.update(activeIds, dt)`; for each voice `engine.setVoiceGain(id, gains.get(id), 0.05)`; then decide notes:
  - **pluck/bells:** probabilistic trigger — every `beatsPerNote` (from bpm + role), with a seeded-random gate, call `engine.triggerVoice(id, midiForCurrentRoot(assignment), noteDur)`.
  - **pad/bloom/drone:** trigger once (hold) when first active; rely on `engine`'s held-note glide for root changes; retrigger only if the voice reports not-held.
- `midiForCurrentRoot(assignment)` recomputes MIDI from the live smoothed root: `root + ROLE_SEMITONES[role] + 12*octave + detuneCents/100`.
- `setRoot` updates the field root and calls `engine.setRoot` (glide held voices).

- [ ] **Step 1: Implement `scheduler.js`.**
- [ ] **Step 2: `node --check webapp/scheduler.js`.**
- [ ] **Step 3: Commit** `feat(webapp): generative scheduler driving Tone.js voices`

---

### Task 7: Modifier factory (5 rows) — per-voice inserts

**Files:**
- Create: `webapp/modifiers.js`
- Test: `node --check`

**Interfaces:**
- Produces: `MODIFIER_ROWS = ["stretch","spectral","pitch","grainfx","spatial"]`; `MODIFIER_PRESETS` (25 ids, 5 per row); `createModifierNode(Tone, presetId) -> Tone node` (a single in/out effect node) and `MODIFIER_COLS` labels.

**Design notes (Tone.js effect per row; 5 variants via params):**
- **spatial** → `new Tone.Reverb({decay, wet})` (room→wash) or `new Tone.Freeverb`.
- **pitch** → `new Tone.PitchShift({pitch, feedback, wet})` (−12, +12, +7, +0.25 drift via detune, wide).
- **grainfx** → `Tone.Chorus`, `Tone.BitCrusher`, `Tone.Distortion`, `Tone.Chebyshev`, `Tone.AutoFilter`.
- **stretch** → `Tone.PitchShift` at 0 semitones with large `windowSize` + feedback as a smear/sustain approximation, or `Tone.FeedbackDelay` short+high-fb; variants = amount. (Freeze-grade stretch refined in a later pass.)
- **spectral** → approximation: `Tone.Chorus` + `Tone.FeedbackDelay` blur, or `Tone.Freeverb` heavy. Flagged weakest.
- Preset ids: `${row}_${1..5}`; `MODIFIER_PRESETS` mirrors the desktop grid shape so the UI grid maps cell→id the same way.

- [ ] **Step 1: Implement `modifiers.js`.**
- [ ] **Step 2: `node --check webapp/modifiers.js`.**
- [ ] **Step 3: Commit** `feat(webapp): per-voice modifier factory (5 Tone.js effect rows)`

---

### Task 8: Wire `main.js` synth mode to the Tone.js engine

**Files:**
- Modify: `webapp/main.js` (synth-mode seam), `webapp/index.html` (load `vendor/tone.js` + module scripts)
- Test: manual (browser) + `node --check webapp/main.js`

**Interfaces:**
- Consumes: `ToneEngine`, `Scheduler`, `modifiers.js`, source-grid config.
- Produces: synth-mode patch-bay wired to Tone.js; source rows `pluck/pad/bloom`, modifier rows from `MODIFIER_ROWS`.

**Design notes:**
- `index.html`: add `<script src="vendor/tone.js"></script>` before `main.js`; load new files as `<script type="module">` (or convert main.js to a module and import). Keep the existing DOM.
- Add a synth **source-grid config**: rows `["pluck","pad","bloom"]` with per-column instrument lists (from the desktop grid): pluck=[piano,guitar,tapeguitar,tapebell,casio], pad=[strings,flute,clarinet,casio,piano], bloom=[strings,flute,clarinet,guitar,tapebell]. (Rows 4–5 reserved for bells/drone — render as empty/disabled for now.)
- On `setMode("synth")`: instantiate `ToneEngine` + `Scheduler` (once), `await engine.init()`. Route the existing patch-bay handlers:
  - **Send** → add to Sources list (client-side single-use source), as today.
  - **assign source → generator jack** → `engine.createVoice(id, {instrument, behavior, hsv})` + `scheduler.addVoice(id, {behavior, bpm})`; **silent** (no modifier yet); consume the source; color the jack.
  - **cable generator → modifier jack** → `engine.setVoiceModifier(id, modifierId)` (voice becomes audible).
  - **drag placed jack → other generator jack** → move: dispose+recreate the voice on the new instrument (reuse color/bpm), reconnect modifier if any.
  - **off-grid** → `engine.setVoiceModifier(id, null)` (silent).
  - **remove** → `scheduler.removeVoice(id)` + `engine.disposeVoice(id)`.
  - **Play/Pause** → `engine.resume()/pause()`.
  - **root slider** (C2–C4) → `scheduler.setRoot(midi)`; **reverb/delay sliders** → `engine.setReverb/ setDelay`.
- Loop mode path unchanged (still posts to the worker).

- [ ] **Step 1: Implement the synth-mode seam in `main.js` + `index.html` changes.**
- [ ] **Step 2: `node --check webapp/main.js`.**
- [ ] **Step 3: Commit** `feat(webapp): wire synth mode to the Tone.js engine`

---

### Task 9: Static gate + manual smoke + docs

**Files:**
- Modify: `audio_prototype/tests/test_webapp_static.py` (or add a check) to `node --check` the new JS files
- Modify: `AGENTS.md`

- [ ] **Step 1: Add a static gate** — a test that runs `node --check` over `webapp/*.js` and `webapp/generative/*.js` and asserts exit 0 (skip if `node` absent). Run the pure-logic suite too: `node --test webapp/generative/`.

- [ ] **Step 2: Manual smoke (browser).** Serve `webapp/` (`cd webapp && python -m http.server`), open it, switch to Synth: Send a color → assign to a `pad`/`strings` jack → cable to `spatial` → Play → hear a clean sustained tone into reverb; add a `pluck`/`piano` voice cabled to `pitch`; raise Reverb/Delay; sweep the root and confirm held notes glide. Confirm no clicks on assign/cable/move/remove.

- [ ] **Step 3: Update `AGENTS.md`** "Pick up here": browser Tone.js synth MVP (native audio + ported brain), phasing (bells/drone + polish next), how to run (`python -m http.server` in `webapp/`).

- [ ] **Step 4: Commit** `docs: Tone.js synth MVP + static JS gate; update brief`

---

## Self-Review

**Spec coverage:** vendored offline Tone.js + assets (T1); ported harmony/allocator/conductor with tests (T2–4); native master wash + per-voice sampler chains + root glide (T5); generative scheduler (T6); 5 modifier rows (T7); patch-bay workflow rewired incl. silent-until-cabled, drag-reassign, controls (T8); static gate + manual smoke + brief (T9). Bells/drone + stretch/spectral polish explicitly deferred to phase 2 per the spec. ✅

**Placeholder scan:** pure-logic tasks carry full code + tests; Tone.js tasks carry interfaces + concrete node configs + design notes (audio can't be headless-tested here — stated in Global Constraints and the spec's testing section). No TBDs.

**Type consistency:** `mulberry32`/`uniform` (rng.js) used by T2–4, T6. `HarmonicField.midiForRole`, `PitchAllocator.allocate → {role,octave,detuneCents,midi,band}`, `VoiceConductor.update(activeIds, dt) → Map` consistent across T2–4 and T6. `ToneEngine` method names consistent between T5, T6, T8. `MODIFIER_ROWS`/`createModifierNode` consistent between T7 and T8. Source grid rows `pluck/pad/bloom` consistent T5/T6/T8.
