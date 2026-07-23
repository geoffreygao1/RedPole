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
