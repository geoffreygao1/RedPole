import { test } from "node:test";
import assert from "node:assert/strict";
import { mulberry32 } from "./rng.js";
import { HarmonicField } from "./harmony.js";
import { shadowMidi, scatterMidi, ticksForSeconds } from "./voicing.js";
import { MAX_VOICE_MIDI } from "./harmony.js";

test("shadowMidi adds the preset interval in semitones", () => {
  assert.equal(shadowMidi(60, 7), 67);
  assert.equal(shadowMidi(60, 12), 72);
  assert.equal(shadowMidi(60, 19), 79);
});

test("shadowMidi never exceeds MAX_VOICE_MIDI even with a high base and a wide interval", () => {
  assert.equal(shadowMidi(80, 19), MAX_VOICE_MIDI);
});

test("scatterMidi never exceeds MAX_VOICE_MIDI", () => {
  const field = new HarmonicField(60, true, "optimistic"); // ROOT_MAX
  const assignment = { octave: 3, detuneCents: 4 };
  for (let seed = 0; seed < 20; seed++) {
    const midi = scatterMidi(field, mulberry32(seed), assignment);
    assert.ok(midi <= MAX_VOICE_MIDI, `seed ${seed} produced ${midi}`);
  }
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

// A fake field with a role fixed to a known 0-semitone value isolates the
// octave-wander math from the mood's own role/semitone weighting, so the
// octave offset can be read back from `midi` exactly (no rounding ambiguity
// from a real weighted role's 0-11 semitone contribution).
function fakeField(spread) {
  return {
    weightedRole: () => "root",
    octaveSpread: () => spread,
    midiForRole: (_role, octave) => 48 + 12 * octave,
  };
}

test("higher effect depth widens how far scatterMidi wanders from home octave", () => {
  const field = fakeField(2);
  const assignment = { octave: 2, detuneCents: 0 };
  const maxAbsOffset = (depth) => {
    let max = 0;
    for (let seed = 0; seed < 60; seed++) {
      const midi = scatterMidi(field, mulberry32(seed), assignment, depth);
      const offset = Math.round((midi - 48) / 12) - assignment.octave;
      max = Math.max(max, Math.abs(offset));
    }
    return max;
  };
  const atDepth1 = maxAbsOffset(1);
  const atDepth4 = maxAbsOffset(4);
  assert.equal(atDepth1, 1, "depth 1 should reproduce the original fixed +-1 octave wander");
  assert.ok(atDepth4 > atDepth1, `depth 4 max offset (${atDepth4}) should exceed depth 1 (${atDepth1})`);
});

test("scatterMidi never wanders when octaveSpread is 0, regardless of depth", () => {
  const field = fakeField(0);
  const assignment = { octave: 2, detuneCents: 0 };
  for (let seed = 0; seed < 20; seed++) {
    const midi = scatterMidi(field, mulberry32(seed), assignment, 4);
    assert.equal(midi, 48 + 12 * assignment.octave);
  }
});

test("ticksForSeconds converts seconds to ticks and floors at 1", () => {
  assert.equal(ticksForSeconds(10, 2), 5);
  assert.equal(ticksForSeconds(0.1, 2), 1);
  assert.equal(ticksForSeconds(1, 1), 1);
});
