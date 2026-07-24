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
