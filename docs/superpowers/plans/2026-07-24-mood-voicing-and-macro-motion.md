# Mood Voicing & Macro Motion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the webapp Synth mode's "everything sounds melancholy/droney" problem by (1) giving `optimistic`/`happy` moods the full-scale breadth clickbath actually uses, (2) making register spread mood-aware instead of pure collision-avoidance, (3) implementing the `shadow` and `scatter` macro presets (currently silent no-ops), and (4) giving permanently-held `pad`/`bloom`/`drone` voices slow pitch movement instead of a note frozen forever.

**Architecture:** All new deterministic pitch/timing logic goes in `webapp/generative/` as pure, seed-deterministic functions (matching the existing `harmony.js`/`allocator.js`/`conductor.js` pattern) so it can be unit-tested with Node's built-in test runner without a browser or Tone.js. `scheduler.js` and `tone_engine.js` stay thin orchestrators that call into that pure logic and into Tone.js respectively — consistent with the existing split in the codebase.

**Tech Stack:** Vanilla JS, Tone.js (browser-only, vendored at `webapp/vendor/tone.js`), Node's built-in `node:test` + `node:assert/strict` for unit tests, Python `pytest` for the static/literal-string test suite in `audio_prototype/tests/test_webapp_static.py`.

## Global Constraints

- **Node.js is not available in the primary dev/agent environment for this session.** Every task below has a `node --test ...` verification step — the user runs these themselves in their own terminal and reports pass/fail. Do not claim a JS test "passes" without that confirmation.
- **Do not alter any cache-busting `?v=...` import query strings** (e.g. `from "./generative/harmony.js?v=20260723-root-note-scale"`, `from "./scheduler.js?v=20260723-5x5-deploy"`). Dozens of literal-string assertions in `audio_prototype/tests/test_webapp_static.py` hard-code these exact strings across `main.js`, `scheduler.js`, `tone_engine.js`, `index.html`. Add new imports without a version suffix (matching the existing unsuffixed `./generative/rng.js` import), and never edit an existing versioned import line.
- **Do not alter these exact existing lines** (locked by `test_scheduler_adds_sparse_fast_garnishes_without_speeding_sustained_voices` and neighboring tests in `test_webapp_static.py`) — only add new lines around them:
  - `const GARNISH_BEHAVIORS = new Set(["pluck", "bell"]);`
  - `const GARNISH_TICK_INTERVAL = 2;`
  - `this.engine.triggerVoice(id, this.midiForVoice(voice), garnishDuration(voice));`
  - `pluck: [0.5, 4]`, `bell: [0.75, 7]`, `pad: [8, 24]`, `bloom: [5, 18]`, `drone: [16, 48]`
  - `{ name: "still", speed: 0.9, probability: 0.56` and `{ name: "spark", speed: 0.22, probability: 0.7`
  - `this.engine.setVoiceGain(voiceId, 0.55, 0.02);` and `this.engine.triggerVoice(voiceId, this.midiForVoice(voice), this.immediateDuration(voice));`
  - `this.rootMidi = 48;`
  - `"major: { root: 0, third: 4, fifth: 7, sixth: 9 }"` / `"minor: { root: 0, minorThird: 3, fifth: 7, flatSixth: 8 }"` (these are `SCALE_INTERVALS`, not `HARMONIC_PALETTES.optimistic` — do not confuse the two)
- **Do not change `HARMONIC_PALETTES.melancholy` or `HARMONIC_PALETTES.mysterious`.** They already read correctly per user feedback; only `optimistic`/`happy` are being fixed.
- Run `rtk python -m pytest audio_prototype/tests/test_webapp_static.py -q` after every task that touches `harmony.js`, `scheduler.js`, or `tone_engine.js`, to confirm none of the locked literal strings above were disturbed.
- Follow this repo's commit style: `type(webapp): summary` (e.g. `feat(webapp): ...`, `fix(webapp): ...`), matching recent history.

---

### Task 1: Broaden optimistic/happy harmony + mood-aware octave spread

**Files:**
- Modify: `webapp/generative/harmony.js`
- Test: `webapp/generative/harmony.test.js`

**Interfaces:**
- Produces: `MOOD_OCTAVE_SPREAD` (object), `octaveSpreadForMood(mood)`, `isFoundationRole(role)`, `HarmonicField.prototype.octaveSpread()` — all consumed by Task 2 (`voicing.js`) and Task 3 (`allocator.js`).

- [ ] **Step 1: Write the failing tests**

Add to the end of `webapp/generative/harmony.test.js`:

```js
test("optimistic and happy moods use the full clickbath major scale, evenly weighted", () => {
  const f = new HarmonicField(48, true, "optimistic");
  const expectedRoles = ["fifth", "fourth", "root", "second", "seventh", "sixth", "third"];
  assert.deepEqual(f.roles().sort(), expectedRoles.sort());
  for (const r of f.roles()) {
    assert.ok(f.palette.weights[r] <= 0.2, `optimistic ${r} weight ${f.palette.weights[r]} should be near-flat`);
  }
  f.setMood("happy");
  assert.deepEqual(f.roles().sort(), expectedRoles.sort());
  for (const r of f.roles()) {
    assert.ok(f.palette.weights[r] <= 0.2, `happy ${r} weight ${f.palette.weights[r]} should be near-flat`);
  }
});

test("optimistic/happy octave spread is wider than mysterious/melancholy", () => {
  assert.equal(octaveSpreadForMood("optimistic"), 2);
  assert.equal(octaveSpreadForMood("happy"), 2);
  assert.equal(octaveSpreadForMood("mysterious"), 1);
  assert.equal(octaveSpreadForMood("melancholy"), 0);
  assert.equal(octaveSpreadForMood("unknown-mood-id"), 0);
});

test("HarmonicField.octaveSpread() reflects the current mood", () => {
  const f = new HarmonicField(48, true, "melancholy");
  assert.equal(f.octaveSpread(), 0);
  f.setMood("optimistic");
  assert.equal(f.octaveSpread(), 2);
});

test("isFoundationRole flags only root and fifth", () => {
  assert.ok(isFoundationRole("root"));
  assert.ok(isFoundationRole("fifth"));
  assert.ok(!isFoundationRole("second"));
  assert.ok(!isFoundationRole("seventh"));
});
```

Update the existing import line at the top of `webapp/generative/harmony.test.js` to:

```js
import { HARMONIC_PALETTES, HarmonicField, ROLE_SEMITONES, midiToHz, paletteForId, octaveSpreadForMood, isFoundationRole } from "./harmony.js";
```

- [ ] **Step 2: Run tests to verify they fail**

Ask the user to run: `rtk node --test webapp/generative/harmony.test.js`
Expected: FAIL — `octaveSpreadForMood is not a function` / `isFoundationRole is not a function` / roles-length assertion failures.

- [ ] **Step 3: Implement**

In `webapp/generative/harmony.js`, replace the `optimistic` and `happy` entries inside `HARMONIC_PALETTES` (currently the 4-note weighted subsets) with:

```js
  optimistic: {
    // Clickbath's actual optimistic mode is the full major scale, picked with
    // near-equal probability (see clickbath src/index.js noteArray()) -- not a
    // narrow root-heavy subset. A narrow subset read as static/droney
    // regardless of which notes were in it, because with up to 25 sustained
    // voices sharing only 4 pitch classes you get heavy unison stacking.
    semitones: { root: 0, second: 2, third: 4, fourth: 5, fifth: 7, sixth: 9, seventh: 11 },
    weights: { root: 0.15, second: 0.14, third: 0.14, fourth: 0.13, fifth: 0.15, sixth: 0.14, seventh: 0.15 },
  },
  happy: {
    // Same full-scale breadth as optimistic, with thirds/sixths/sevenths
    // weighted up slightly for a brighter major-7 lean.
    semitones: { root: 0, second: 2, third: 4, fourth: 5, fifth: 7, sixth: 9, seventh: 11 },
    weights: { root: 0.13, second: 0.12, third: 0.16, fourth: 0.1, fifth: 0.14, sixth: 0.16, seventh: 0.19 },
  },
```

Immediately after the closing `};` of `HARMONIC_PALETTES` (before `const SCALE_INTERVALS = {`), add:

```js
export const MOOD_OCTAVE_SPREAD = {
  optimistic: 2,
  happy: 2,
  mysterious: 1,
  melancholy: 0,
};

export function octaveSpreadForMood(mood) {
  return MOOD_OCTAVE_SPREAD[mood] ?? MOOD_OCTAVE_SPREAD.melancholy;
}

const FOUNDATION_ROLES = new Set(["root", "fifth"]);
export function isFoundationRole(role) {
  return FOUNDATION_ROLES.has(role);
}
```

Inside the `HarmonicField` class, add a method right after `setMood(mood) { ... }`:

```js
  octaveSpread() {
    return octaveSpreadForMood(this.mood);
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Ask the user to run: `rtk node --test webapp/generative/harmony.test.js`
Expected: PASS, all tests including the pre-existing ones (`third`→52, `sixth`→57, `happy.second`→50, etc. are unchanged since those semitone values were preserved).

- [ ] **Step 5: Run the static Python suite**

Run: `rtk python -m pytest audio_prototype/tests/test_webapp_static.py -q`
Expected: PASS (this task never touches `SCALE_INTERVALS` or any locked literal).

- [ ] **Step 6: Commit**

```bash
git add webapp/generative/harmony.js webapp/generative/harmony.test.js
git commit -m "fix(webapp): broaden optimistic/happy moods to full scale, add mood octave spread"
```

---

### Task 2: Pure pitch-selection helpers for macro-driven motion

**Files:**
- Create: `webapp/generative/voicing.js`
- Test: `webapp/generative/voicing.test.js`

**Interfaces:**
- Consumes: `HarmonicField.prototype.octaveSpread()`, `HarmonicField.prototype.weightedRole(rng)`, `HarmonicField.prototype.midiForRole(role, octave)` (all from Task 1 / existing `harmony.js`).
- Produces: `shadowMidi(baseMidi, interval)`, `scatterMidi(field, rng, assignment)`, `ticksForSeconds(seconds, dtSeconds)` — consumed by Task 5, Task 6, Task 7 (`scheduler.js`).

- [ ] **Step 1: Write the failing tests**

Create `webapp/generative/voicing.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { mulberry32 } from "./rng.js";
import { HarmonicField } from "./harmony.js";
import { shadowMidi, scatterMidi, ticksForSeconds } from "./voicing.js";

test("shadowMidi adds the preset interval in semitones", () => {
  assert.equal(shadowMidi(60, 7), 67);
  assert.equal(shadowMidi(60, 12), 72);
  assert.equal(shadowMidi(60, 19), 79);
});

test("scatterMidi returns a finite pitch at or above the field's root", () => {
  const field = new HarmonicField(48, true, "optimistic");
  const rng = mulberry32(11);
  const assignment = { octave: 1, detuneCents: 0 };
  const midi = scatterMidi(field, rng, assignment);
  assert.ok(Number.isFinite(midi));
  assert.ok(midi >= 48);
});

test("scatterMidi is seed-deterministic given the same field and rng seed", () => {
  const assignment = { octave: 1, detuneCents: 2.5 };
  const a = scatterMidi(new HarmonicField(48, true, "optimistic"), mulberry32(5), assignment);
  const b = scatterMidi(new HarmonicField(48, true, "optimistic"), mulberry32(5), assignment);
  assert.equal(a, b);
});

test("scatterMidi never wanders when the mood's octave spread is 0", () => {
  const field = new HarmonicField(48, true, "melancholy");
  const rng = mulberry32(3);
  const assignment = { octave: 0, detuneCents: 0 };
  const midi = scatterMidi(field, rng, assignment);
  // With spread 0, octave stays at assignment.octave (0); role semitones for
  // melancholy are all within 0-8, so midi must land within one octave of root.
  assert.ok(midi >= 48 && midi < 60);
});

test("ticksForSeconds converts seconds to ticks and floors at 1", () => {
  assert.equal(ticksForSeconds(10, 2), 5);
  assert.equal(ticksForSeconds(0.1, 2), 1);
  assert.equal(ticksForSeconds(1, 1), 1);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Ask the user to run: `rtk node --test webapp/generative/voicing.test.js`
Expected: FAIL — `Cannot find module './voicing.js'`.

- [ ] **Step 3: Implement**

Create `webapp/generative/voicing.js`:

```js
// Pure pitch-selection helpers for macro-driven secondary triggers (shadow,
// scatter) and slow held-voice re-voicing. No Tone.js dependency, so these
// stay unit-testable without an audio context.

const WANDER_CHANCE = 0.4;

export function shadowMidi(baseMidi, interval) {
  return baseMidi + interval;
}

// Picks a fresh scale-respecting pitch for a scatter fragment: a new
// weighted role at the voice's home octave, occasionally wandering one
// octave within the mood's spread instead of always echoing the same note.
export function scatterMidi(field, rng, assignment) {
  const role = field.weightedRole(rng);
  const spread = field.octaveSpread();
  const wander = spread > 0 && rng() < WANDER_CHANCE ? (rng() < 0.5 ? -1 : 1) : 0;
  const octave = Math.max(0, assignment.octave + wander);
  return field.midiForRole(role, octave) + assignment.detuneCents / 100.0;
}

export function ticksForSeconds(seconds, dtSeconds) {
  return Math.max(1, Math.round(seconds / dtSeconds));
}
```

- [ ] **Step 4: Run tests to verify they pass**

Ask the user to run: `rtk node --test webapp/generative/voicing.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/generative/voicing.js webapp/generative/voicing.test.js
git commit -m "feat(webapp): add pure pitch helpers for macro-driven voice motion"
```

---

### Task 3: Mood-aware register allocation

**Files:**
- Modify: `webapp/generative/allocator.js`
- Test: `webapp/generative/allocator.test.js`

**Interfaces:**
- Consumes: `isFoundationRole(role)` (Task 1), `HarmonicField.prototype.octaveSpread()` (Task 1).
- Produces: no new exports; `PitchAllocator.prototype.allocate()` behavior changes (still returns `{ role, octave, detuneCents, band, midi }`).

- [ ] **Step 1: Write the failing tests**

Add to `webapp/generative/allocator.test.js`:

```js
test("allocate anchors sub/low register voices on a foundation role", () => {
  const alloc = new PitchAllocator(new HarmonicField(48, true, "optimistic"));
  for (let vid = 0; vid < 15; vid++) {
    const a = alloc.allocate(vid, mulberry32(vid + 1), 0.2, "foreground");
    if (a.band === "sub" || a.band === "low") {
      assert.ok(["root", "fifth"].includes(a.role), `expected foundation role in ${a.band}, got ${a.role}`);
    }
  }
});

test("melancholy (spread 0) always starts the octave search at 0", () => {
  const field = new HarmonicField(48, true, "melancholy");
  assert.equal(field.octaveSpread(), 0);
  const alloc = new PitchAllocator(field);
  const a = alloc.allocate(1, mulberry32(1), 0.1, "foreground");
  assert.equal(a.octave, 0);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Ask the user to run: `rtk node --test webapp/generative/allocator.test.js`
Expected: FAIL on the foundation-role assertion (current code lets any weighted role land in any band).

- [ ] **Step 3: Implement**

In `webapp/generative/allocator.js`, change the import line from:

```js
import { midiToHz } from "./harmony.js";
```

to:

```js
import { isFoundationRole, midiToHz } from "./harmony.js";
```

Replace the body of `allocate(vid, rng, density, detuneClass = "foreground")` with:

```js
  allocate(vid, rng, density, detuneClass = "foreground") {
    const role = this.field.weightedRole(rng);
    const spread = this.field.octaveSpread();
    let octave = spread > 0 ? Math.floor(rng() * (spread + 1)) : 0;
    let midi, band;
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
    let finalRole = role;
    if ((band === "sub" || band === "low") && !isFoundationRole(role)) {
      finalRole = "root";
      midi = this.field.midiForRole(finalRole, octave);
      band = bandForHz(midiToHz(midi));
    }
    const limit = DETUNE_CENTS_RANGE[detuneClass] ?? DETUNE_CENTS_RANGE.foreground;
    const detuneCents = uniform(rng, -limit, limit);
    this._register(vid, band);
    return { role: finalRole, octave, detuneCents, band, midi: midi + detuneCents / 100.0 };
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Ask the user to run: `rtk node --test webapp/generative/allocator.test.js`
Expected: PASS, including the two pre-existing tests (`allocate returns a coherent assignment`, `allocate is seed-deterministic`) — both assert self-consistency of the returned object, not hardcoded octave/role values, so they remain valid.

- [ ] **Step 5: Run the static Python suite**

Run: `rtk python -m pytest audio_prototype/tests/test_webapp_static.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/generative/allocator.js webapp/generative/allocator.test.js
git commit -m "feat(webapp): anchor low-register voices on root/fifth, spread octave pick by mood"
```

---

### Task 4: ToneEngine companion-note trigger

**Files:**
- Modify: `webapp/tone_engine.js`

**Interfaces:**
- Produces: `ToneEngine.prototype.triggerAccent(voiceId, midi, durationSeconds, velocity)` — consumed by Task 5/6 (`scheduler.js`).

No unit test file exists for `tone_engine.js` today (it requires a live Tone.js audio context; the project's existing convention, per `webapp/AGENTS.md`, is manual browser smoke-testing for this file). This task is verified via `node --check` syntax validation and manual browser testing in Task 8.

- [ ] **Step 1: Implement**

In `webapp/tone_engine.js`, add a new method immediately after `triggerVoice(voiceId, midi, durationSeconds = null) { ... }` and before `isVoiceHeld(voiceId)`:

```js
  // Fires a short companion note through the SAME sampler as the primary
  // voice, at a reduced velocity, without going through the HELD_BEHAVIORS
  // held-note gate in triggerVoice(). Used by shadow (fixed-interval overtone)
  // and scatter (wandering pitch echo) macros so they can layer a note on top
  // of an already-sustaining pad/bloom/drone voice.
  triggerAccent(voiceId, midi, durationSeconds, velocity = 1) {
    const voice = this.voices.get(voiceId);
    if (!voice || !voice.nodes || !voice.connected || !voice.macro) return;
    const frequency = midiToHz(midi);
    voice.nodes.sampler.triggerAttackRelease(frequency, durationSeconds, undefined, clamp(velocity, 0, 1));
  }
```

- [ ] **Step 2: Run the syntax check**

Ask the user to run: `rtk node --check webapp/tone_engine.js`
Expected: exits 0, no output.

- [ ] **Step 3: Run the static Python suite**

Run: `rtk python -m pytest audio_prototype/tests/test_webapp_static.py -q`
Expected: PASS (this method is new code, doesn't touch any locked line).

- [ ] **Step 4: Commit**

```bash
git add webapp/tone_engine.js
git commit -m "feat(webapp): add triggerAccent for macro companion notes"
```

---

### Task 5: Wire the `shadow` macro (fixed-interval overtone)

**Files:**
- Modify: `webapp/scheduler.js`
- Create: `webapp/scheduler.test.js`
- Modify: `audio_prototype/tests/test_webapp_static.py`

**Interfaces:**
- Consumes: `shadowMidi(baseMidi, interval)` (Task 2), `ToneEngine.prototype.triggerAccent()` (Task 4), `ToneEngine.prototype.voiceMacroPreset(voiceId)` (already exists in `tone_engine.js`).
- Produces: `Scheduler.prototype._triggerCompanions(voiceId, voice)` — extended in Task 6 with a scatter branch, and called from Task 7's held-voice logic.

**Note on why a new `scheduler.test.js` is needed:** `scheduler.js` currently has zero behavioral unit tests (only literal-string presence checks in the Python suite). Since it takes its `engine` and `Tone` dependencies as constructor parameters, it can be tested with lightweight fakes — no real Tone.js required.

- [ ] **Step 1: Widen the Python suite's Node test scan to include `webapp/scheduler.test.js`**

In `audio_prototype/tests/test_webapp_static.py`, in `test_webapp_generative_suite_passes_node_test`, change:

```python
    result = subprocess.run(
        [node, "--test", "webapp/generative/"],
```

to:

```python
    result = subprocess.run(
        [node, "--test", "webapp/generative/", "webapp/scheduler.test.js"],
```

- [ ] **Step 2: Write the failing tests**

Create `webapp/scheduler.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { Scheduler } from "./scheduler.js";

function fakeTone(dtSeconds = 0.25) {
  return {
    Time: () => ({ toSeconds: () => dtSeconds }),
    Transport: { scheduleRepeat: () => 1, clear: () => {} },
  };
}

function fakeEngine(presetsByVoice = new Map()) {
  const calls = { setVoiceMacro: [], releaseVoice: [], triggerVoice: [], setVoiceGain: [], triggerAccent: [] };
  return {
    calls,
    setVoiceMacro(id, macroId) { calls.setVoiceMacro.push([id, macroId]); },
    releaseVoice(id) { calls.releaseVoice.push(id); },
    triggerVoice(id, midi, dur) { calls.triggerVoice.push([id, midi, dur]); },
    setVoiceGain(id, gain, ramp) { calls.setVoiceGain.push([id, gain, ramp]); },
    triggerAccent(id, midi, dur, velocity) { calls.triggerAccent.push([id, midi, dur, velocity]); },
    isVoiceHeld() { return false; },
    voiceMacroPreset(id) { return presetsByVoice.get(id) ?? null; },
  };
}

test("_triggerCompanions is a no-op when the voice has no macro cabled", () => {
  const engine = fakeEngine();
  const scheduler = new Scheduler(engine, { Tone: fakeTone(), seed: 1 });
  scheduler.addVoice(1, { behavior: "pluck" });
  scheduler._triggerCompanions(1, scheduler.voices.get(1));
  assert.equal(engine.calls.triggerAccent.length, 0);
});

test("_triggerCompanions fires a shadow companion at base midi + interval, at preset gain velocity", () => {
  const engine = fakeEngine(new Map([[2, { kind: "shadow", interval: 7, gain: 0.18 }]]));
  const scheduler = new Scheduler(engine, { Tone: fakeTone(), seed: 1 });
  scheduler.addVoice(2, { behavior: "pluck" });
  const voice = scheduler.voices.get(2);
  scheduler._triggerCompanions(2, voice);
  assert.equal(engine.calls.triggerAccent.length, 1);
  const [id, midi, , velocity] = engine.calls.triggerAccent[0];
  assert.equal(id, 2);
  assert.equal(midi, scheduler.midiForVoice(voice) + 7);
  assert.equal(velocity, 0.18);
});
```

- [ ] **Step 3: Run tests to verify they fail**

Ask the user to run: `rtk node --test webapp/scheduler.test.js`
Expected: FAIL — `scheduler._triggerCompanions is not a function`.

- [ ] **Step 4: Implement**

In `webapp/scheduler.js`, add a new import line after the existing `rng.js` import (do not touch the existing versioned imports above it):

```js
import { shadowMidi } from "./generative/voicing.js";
```

Add a new method to the `Scheduler` class, placed right before `start()`:

```js
  _triggerCompanions(voiceId, voice) {
    const preset = this.engine.voiceMacroPreset(voiceId);
    if (!preset) return;
    const baseMidi = this.midiForVoice(voice);
    if (preset.kind === "shadow") {
      this.engine.triggerAccent(voiceId, shadowMidi(baseMidi, preset.interval), 0.6, preset.gain);
    }
  }
```

Wire it into the three trigger call sites. In `triggerVoiceNow(voiceId)`, after the existing `this.engine.triggerVoice(voiceId, this.midiForVoice(voice), this.immediateDuration(voice));` line, add:

```js
    this._triggerCompanions(voiceId, voice);
```

In `_tick()`, after the existing garnish-branch line `this.engine.triggerVoice(id, this.midiForVoice(voice), garnishDuration(voice));`, add (still before the existing `continue;`):

```js
        this._triggerCompanions(id, voice);
```

In `_tick()`, after the existing `this.engine.triggerVoice(id, this.midiForVoice(voice), dur);` line (in the main due-trigger branch), add:

```js
      this._triggerCompanions(id, voice);
```

- [ ] **Step 5: Run tests to verify they pass**

Ask the user to run: `rtk node --test webapp/scheduler.test.js`
Expected: PASS.

- [ ] **Step 6: Run the full static Python suite**

Run: `rtk python -m pytest audio_prototype/tests/test_webapp_static.py -q`
Expected: PASS — this confirms the new import and inserted lines didn't disturb any locked literal, and that the widened `node --test` invocation from Step 1 also runs (it will attempt to spawn `node`; if Node is unavailable it skips as before).

- [ ] **Step 7: Commit**

```bash
git add webapp/scheduler.js webapp/scheduler.test.js audio_prototype/tests/test_webapp_static.py
git commit -m "feat(webapp): implement shadow macro as a fixed-interval overtone trigger"
```

---

### Task 6: Wire the `scatter` macro (scale-wandering echo, same instrument)

**Files:**
- Modify: `webapp/scheduler.js`
- Modify: `webapp/scheduler.test.js`

**Interfaces:**
- Consumes: `scatterMidi(field, rng, assignment)` (Task 2).
- Produces: extends `Scheduler.prototype._triggerCompanions` with the `"scatter"` branch.

- [ ] **Step 1: Write the failing tests**

Add to `webapp/scheduler.test.js`:

```js
test("_triggerCompanions fires a scatter companion through the same sampler when the density gate passes", () => {
  const engine = fakeEngine(new Map([[3, { kind: "scatter", density: 1, gain: 0.2 }]]));
  const scheduler = new Scheduler(engine, { Tone: fakeTone(), seed: 1 });
  scheduler.addVoice(3, { behavior: "pluck" });
  scheduler._triggerCompanions(3, scheduler.voices.get(3));
  assert.equal(engine.calls.triggerAccent.length, 1);
  assert.equal(engine.calls.triggerAccent[0][0], 3); // same voiceId => same sampler
  assert.equal(engine.calls.triggerAccent[0][3], 0.2);
});

test("_triggerCompanions skips the scatter companion when the density gate fails", () => {
  const engine = fakeEngine(new Map([[4, { kind: "scatter", density: 0, gain: 0.2 }]]));
  const scheduler = new Scheduler(engine, { Tone: fakeTone(), seed: 1 });
  scheduler.addVoice(4, { behavior: "pluck" });
  scheduler._triggerCompanions(4, scheduler.voices.get(4));
  assert.equal(engine.calls.triggerAccent.length, 0);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Ask the user to run: `rtk node --test webapp/scheduler.test.js`
Expected: FAIL — first new test gets 0 calls instead of 1 (scatter branch doesn't exist yet).

- [ ] **Step 3: Implement**

In `webapp/scheduler.js`, change the import line added in Task 5 from:

```js
import { shadowMidi } from "./generative/voicing.js";
```

to:

```js
import { shadowMidi, scatterMidi } from "./generative/voicing.js";
```

Update `_triggerCompanions` to:

```js
  _triggerCompanions(voiceId, voice) {
    const preset = this.engine.voiceMacroPreset(voiceId);
    if (!preset) return;
    const baseMidi = this.midiForVoice(voice);
    if (preset.kind === "shadow") {
      this.engine.triggerAccent(voiceId, shadowMidi(baseMidi, preset.interval), 0.6, preset.gain);
    } else if (preset.kind === "scatter" && voice.rng() < preset.density) {
      this.engine.triggerAccent(voiceId, scatterMidi(this.field, voice.rng, voice.assignment), 0.5, preset.gain);
    }
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Ask the user to run: `rtk node --test webapp/scheduler.test.js`
Expected: PASS.

- [ ] **Step 5: Run the full static Python suite**

Run: `rtk python -m pytest audio_prototype/tests/test_webapp_static.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/scheduler.js webapp/scheduler.test.js
git commit -m "feat(webapp): implement scatter macro as a scale-wandering same-instrument echo"
```

---

### Task 7: Slow re-voicing for held (pad/bloom/drone) voices

**Files:**
- Modify: `webapp/scheduler.js`
- Modify: `webapp/scheduler.test.js`

**Interfaces:**
- Consumes: `ticksForSeconds(seconds, dtSeconds)` (Task 2), `PitchAllocator.prototype.allocate()` (Task 3, already existed but now foundation-anchored).
- Produces: `Scheduler.prototype._revoiceDue(voice, currentTick)`; `addVoice()` now sets `revoicePeriodTicks`/`revoiceTickOffset` on every voice; `_tick()`'s held-behavior branch now reassigns pitch periodically.

- [ ] **Step 1: Write the failing tests**

Add to `webapp/scheduler.test.js`:

```js
test("addVoice gives held behaviors a finite revoice period and non-held behaviors an infinite one", () => {
  const engine = fakeEngine();
  const scheduler = new Scheduler(engine, { Tone: fakeTone(0.25), seed: 1 });
  scheduler.addVoice(5, { behavior: "pluck" });
  scheduler.addVoice(6, { behavior: "drone" });
  assert.equal(scheduler.voices.get(5).revoicePeriodTicks, Infinity);
  assert.ok(Number.isFinite(scheduler.voices.get(6).revoicePeriodTicks));
});

test("_revoiceDue is always false for an infinite period", () => {
  const engine = fakeEngine();
  const scheduler = new Scheduler(engine, { Tone: fakeTone(0.25), seed: 1 });
  scheduler.addVoice(7, { behavior: "pluck" });
  const voice = scheduler.voices.get(7);
  assert.equal(scheduler._revoiceDue(voice, 0), false);
  assert.equal(scheduler._revoiceDue(voice, 999999), false);
});

test("_revoiceDue fires exactly once per period for held behaviors", () => {
  const engine = fakeEngine();
  const scheduler = new Scheduler(engine, { Tone: fakeTone(0.25), seed: 1 });
  scheduler.addVoice(8, { behavior: "drone" });
  const voice = scheduler.voices.get(8);
  let hits = 0;
  for (let t = 0; t < voice.revoicePeriodTicks * 3; t++) {
    if (scheduler._revoiceDue(voice, t)) hits += 1;
  }
  assert.equal(hits, 3);
});

test("held voices reassign pitch and crossfade (release+retrigger) at their revoice moment", () => {
  const engine = fakeEngine();
  const scheduler = new Scheduler(engine, { Tone: fakeTone(0.25), seed: 1 });
  scheduler.addVoice(9, { behavior: "drone" });
  scheduler.setVoiceMacro(9, "veil_1");
  const voice = scheduler.voices.get(9);
  voice.tickOffset = 0;
  voice.periodTicks = 4;
  voice.revoiceTickOffset = 0;
  const before = voice.assignment;
  scheduler._tick();
  assert.notEqual(voice.assignment, before);
  assert.ok(engine.calls.releaseVoice.includes(9));
});
```

- [ ] **Step 2: Run tests to verify they fail**

Ask the user to run: `rtk node --test webapp/scheduler.test.js`
Expected: FAIL — `voice.revoicePeriodTicks` is `undefined`, `scheduler._revoiceDue is not a function`.

- [ ] **Step 3: Implement**

In `webapp/scheduler.js`, update the import from Task 6 to also pull in `ticksForSeconds`:

```js
import { shadowMidi, scatterMidi, ticksForSeconds } from "./generative/voicing.js";
```

Near the top of the file, alongside the other constants (after `const GARNISH_TICK_INTERVAL = 2;`), add:

```js
const REVOICE_MIN_SECONDS = 45;
const REVOICE_MAX_SECONDS = 150;
```

In the `Scheduler` constructor, after the line `this.event = null;`, add:

```js
    this.dtSeconds = this.Tone.Time(TICK_SUBDIVISION).toSeconds();
```

Replace the body of `addVoice(voiceId, { behavior, fingerprint = null })` with:

```js
  addVoice(voiceId, { behavior, fingerprint = null }) {
    const density = Math.min(1, (this.voices.size + 1) / 20);
    const rng = mulberry32((fingerprint?.seed ?? voiceId) ^ this.seed ^ voiceId);
    const detuneClass = behavior === "drone" ? "background" : "foreground";
    const assignment = this.allocator.allocate(voiceId, rng, density, detuneClass);
    const [minBeats, maxBeats] = BEHAVIOR_PERIODS[behavior] ?? BEHAVIOR_PERIODS.pluck;
    const motion = fingerprint?.motionBias ?? 0.35;
    const family = triggerFamily(fingerprint);
    const periodBeats = (maxBeats - (maxBeats - minBeats) * motion) * family.speed;
    const periodTicks = Math.max(1, Math.round(periodBeats * TICKS_PER_BEAT));
    const isHeld = ["pad", "bloom", "drone"].includes(behavior);
    const revoiceSeconds = REVOICE_MIN_SECONDS + (REVOICE_MAX_SECONDS - REVOICE_MIN_SECONDS) * rng();
    const revoicePeriodTicks = isHeld ? ticksForSeconds(revoiceSeconds, this.dtSeconds) : Infinity;
    this.voices.set(voiceId, {
      behavior,
      fingerprint,
      detuneClass,
      assignment,
      rng,
      family,
      periodTicks,
      tickOffset: Math.floor(rng() * periodTicks),
      lastTriggerTick: -Infinity,
      burstRemaining: 0,
      revoicePeriodTicks,
      revoiceTickOffset: Number.isFinite(revoicePeriodTicks) ? Math.floor(rng() * revoicePeriodTicks) : 0,
    });
  }
```

Add a new method right after `_triggerCompanions`:

```js
  _revoiceDue(voice, currentTick) {
    if (!Number.isFinite(voice.revoicePeriodTicks)) return false;
    return (currentTick + voice.revoiceTickOffset) % voice.revoicePeriodTicks === 0;
  }
```

In `_tick()`, inside the `if (["pad", "bloom", "drone"].includes(voice.behavior)) { ... }` branch, after the existing bloom-crossfade block and before `continue;`, add:

```js
        if (this._revoiceDue(voice, currentTick)) {
          voice.assignment = this.allocator.allocate(id, voice.rng, Math.min(1, this.voices.size / 20), voice.detuneClass);
          this.engine.releaseVoice(id);
          this.engine.triggerVoice(id, this.midiForVoice(voice), null);
        }
        if (due) this._triggerCompanions(id, voice);
```

- [ ] **Step 4: Run tests to verify they pass**

Ask the user to run: `rtk node --test webapp/scheduler.test.js`
Expected: PASS, all tests in the file including Tasks 5/6's tests.

- [ ] **Step 5: Run the full static Python suite**

Run: `rtk python -m pytest audio_prototype/tests/test_webapp_static.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/scheduler.js webapp/scheduler.test.js
git commit -m "feat(webapp): give held pad/bloom/drone voices slow mood-weighted re-voicing"
```

---

### Task 8: Manual browser verification and living-doc refresh

**Files:**
- Modify: `AGENTS.md` (root)

- [ ] **Step 1: Serve the webapp locally**

Run: `cd webapp && rtk npx serve .` (or `python -m http.server` per `AGENTS.md`), then open the served URL in a browser.

- [ ] **Step 2: Smoke-test optimistic/happy breadth**

Send a scan, auto-assign or manually cable 5-10 sources across different rows (pluck/pad/bloom/bell/drone), set Mood to "Optimistic", press Play, and listen for at least 60 seconds. Confirm: more melodic movement/variety than before, not just root/fifth/sixth repetition. Repeat briefly for "Happy".

- [ ] **Step 3: Smoke-test melancholy/mysterious are unchanged**

Switch Mood to "Melancholy", confirm it still sounds the same as before this work (narrow, contained character preserved).

- [ ] **Step 4: Smoke-test the shadow macro**

Cable a source into a `shimmer` column macro (e.g. "fifth shadow" or "octave glint"). Confirm you can hear a quiet overtone at the expected interval alongside the primary note, where previously that cell was silent/no-op.

- [ ] **Step 5: Smoke-test the scatter macro**

Cable a source into a `scatter` column macro (e.g. "fragments" or "constellation"). Confirm you hear occasional quiet echoes through the same instrument at varying pitches, where previously that cell was silent/no-op.

- [ ] **Step 6: Smoke-test held-voice re-voicing**

Cable a `drone` or `pad` source, press Play, and leave it running for 2-3 minutes without touching any cables. Confirm the held voice's pitch changes at least once (a brief release+retrigger at a new note), instead of sustaining the exact same pitch indefinitely.

- [ ] **Step 7: Update the living doc**

In `AGENTS.md`, update the "⏱ Pick up here" section's **Last session** and **Next up** entries to reflect this work (full-scale optimistic/happy moods, mood-aware octave spread and low-register anchoring, working shadow/scatter macros, held-voice re-voicing) and note any tuning adjustments made by ear during Steps 2-6.

- [ ] **Step 8: Commit**

```bash
git add AGENTS.md
git commit -m "docs: refresh living doc after mood voicing and macro motion work"
```
