import { test } from "node:test";
import assert from "node:assert/strict";
import { scaleTriggerPreset, applyDepthToMacro } from "./modifiers.js";

function fakeParamNode(props) {
  const node = {};
  for (const [key, value] of Object.entries(props)) node[key] = { value };
  return node;
}

test("scaleTriggerPreset scales a shadow preset's gain only", () => {
  const preset = { kind: "shadow", interval: 7, gain: 0.2 };
  const scaled = scaleTriggerPreset(preset, 0.5);
  assert.equal(scaled.gain, 0.1);
  assert.equal(scaled.interval, 7);
});

test("scaleTriggerPreset scales a scatter preset's gain and density, clamped to 1", () => {
  const preset = { kind: "scatter", density: 0.4, gain: 0.2 };
  const scaled = scaleTriggerPreset(preset, 2);
  assert.equal(scaled.gain, 0.4);
  assert.equal(scaled.density, 0.8);
  const clamped = scaleTriggerPreset(preset, 5);
  assert.equal(clamped.gain, 1);
  assert.equal(clamped.density, 1);
});

test("scaleTriggerPreset leaves non-trigger presets untouched", () => {
  const preset = { kind: "filter", frequency: 900, type: "lowpass" };
  assert.equal(scaleTriggerPreset(preset, 1.5), preset);
});

test("depth 0 lands on each kind's neutral/dry value, not an extreme", () => {
  const cases = [
    { preset: { kind: "gain", gain: 0.7 }, prop: "gain", neutral: 1 },
    { preset: { kind: "eq", low: 1.5, mid: -1.5, high: -4 }, prop: "low", neutral: 0 },
    { preset: { kind: "chorus", wet: 0.4, depth: 0.45 }, prop: "wet", neutral: 0 },
    { preset: { kind: "pan", pan: 0.35 }, prop: "pan", neutral: 0 },
    // StereoWidener's neutral (unmodified stereo image) is 0.5, NOT 0 (0 is
    // mono) -- this is the exact bug that shipped: depth 0 was collapsing to
    // mono instead of passing the original stereo image through.
    { preset: { kind: "widener", width: 0.6 }, prop: "width", neutral: 0.5 },
  ];
  for (const { preset, prop, neutral } of cases) {
    const node = fakeParamNode({ [prop]: preset[prop] });
    const macro = { nodes: [node], preset };
    applyDepthToMacro(macro, 0);
    assert.equal(node[prop].value, neutral, `${preset.kind}.${prop} at depth 0`);
  }
});

test("widener scales further from its 0.5 neutral point as depth rises above 1", () => {
  const preset = { kind: "widener", width: 0.6 };
  const node = fakeParamNode({ width: 0.6 });
  const macro = { nodes: [node], preset };
  applyDepthToMacro(macro, 1);
  assert.equal(node.width.value, 0.6);
  applyDepthToMacro(macro, 2);
  assert.ok(Math.abs(node.width.value - 0.7) < 1e-9);
});
