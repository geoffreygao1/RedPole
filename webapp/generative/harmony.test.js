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
