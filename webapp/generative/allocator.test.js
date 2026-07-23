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
