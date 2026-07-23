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

test("deriveFingerprint keeps max hue in the last harmonic lane", () => {
  assert.equal(deriveFingerprint({ hue: 1, sat: 0.7, val: 0.95, bpm: 70 }).harmonicBias, 5);
  assert.equal(deriveFingerprint({ hue: 2, sat: 0.7, val: 0.95, bpm: 70 }).harmonicBias, 5);
});

test("deriveFingerprint defaults non-finite and omitted scan fields", () => {
  const fp = deriveFingerprint({
    hue: Number.NaN,
    sat: Number.POSITIVE_INFINITY,
    val: Number.NEGATIVE_INFINITY,
  });
  assert.equal(fp.hue, 0);
  assert.equal(fp.sat, 0.68);
  assert.equal(fp.val, 0.94);
  assert.equal(fp.bpm, 70);
  assert.deepEqual(deriveFingerprint(), fp);
});
