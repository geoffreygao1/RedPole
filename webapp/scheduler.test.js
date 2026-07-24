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
