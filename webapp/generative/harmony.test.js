import { test } from "node:test";
import assert from "node:assert/strict";
import { mulberry32 } from "./rng.js";
import { HARMONIC_PALETTES, HarmonicField, ROLE_SEMITONES, midiToHz, paletteForId, octaveSpreadForMood, isFoundationRole } from "./harmony.js";

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

test("harmonic field can switch clickbath-derived mood palettes", () => {
  const f = new HarmonicField(48, true, "optimistic");
  assert.equal(f.midiForRole("third"), 52);
  assert.equal(f.midiForRole("sixth"), 57);
  f.setMood("happy");
  assert.equal(f.midiForRole("second"), 50);
  assert.equal(f.midiForRole("sixth"), 57);
  f.setMood("mysterious");
  assert.equal(f.midiForRole("root"), 48);
  assert.equal(f.midiForRole("minorThird"), 51);
  f.setMood("melancholy");
  assert.equal(f.midiForRole("minorThird"), 51);
  assert.equal(f.midiForRole("second"), 50);
  assert.deepEqual(Object.keys(HARMONIC_PALETTES), ["optimistic", "happy", "mysterious", "melancholy"]);
});

test("harmonic field can use clickbath-style root major and minor scales", () => {
  const major = paletteForId("scale:major");
  assert.deepEqual(major.semitones, { root: 0, third: 4, fifth: 7, sixth: 9 });

  const minor = paletteForId("scale:minor");
  assert.deepEqual(minor.semitones, { root: 0, minorThird: 3, fifth: 7, flatSixth: 8 });

  const f = new HarmonicField(54, true, "scale:minor");
  assert.equal(f.midiForRole("root"), 54);
  assert.equal(f.midiForRole("flatSixth"), 62);
});

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

test("mysterious adds a rare flatSecond a half-step above root", () => {
  const f = new HarmonicField(48, true, "mysterious");
  assert.equal(f.midiForRole("flatSecond"), 49);
  assert.ok(f.palette.weights.flatSecond > 0 && f.palette.weights.flatSecond < 0.15);
  const total = Object.values(f.palette.weights).reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(total - 1) < 1e-9);
});

test("isFoundationRole flags only root and fifth", () => {
  assert.ok(isFoundationRole("root"));
  assert.ok(isFoundationRole("fifth"));
  assert.ok(!isFoundationRole("second"));
  assert.ok(!isFoundationRole("seventh"));
});
