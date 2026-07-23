import { VoiceConductor } from "./generative/conductor.js";
import { HarmonicField } from "./generative/harmony.js?v=20260723-scale-palettes";
import { PitchAllocator } from "./generative/allocator.js?v=20260723-trigger-families";
import { mulberry32 } from "./generative/rng.js";

const ROOT_MIN = 36;
const ROOT_MAX = 60;
const TICK_SUBDIVISION = "16n";
const TICKS_PER_BEAT = 4;
const BEHAVIOR_PERIODS = {
  pluck: [0.5, 6],
  bell: [1, 10],
  pad: [16, 48],
  bloom: [8, 32],
  drone: [32, 96],
};
const TRIGGER_FAMILIES = [
  { name: "still", speed: 1.4, probability: 0.48, clusterChance: 0, clusterLength: 0 },
  { name: "breath", speed: 1.0, probability: 0.58, clusterChance: 0.08, clusterLength: 1 },
  { name: "pulse", speed: 0.68, probability: 0.7, clusterChance: 0.16, clusterLength: 1 },
  { name: "ripple", speed: 0.42, probability: 0.78, clusterChance: 0.32, clusterLength: 2 },
  { name: "spark", speed: 0.26, probability: 0.62, clusterChance: 0.44, clusterLength: 3 },
];

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

function triggerFamily(fingerprint) {
  const phrase = fingerprint?.phraseBias ?? 0.3;
  const index = Math.min(TRIGGER_FAMILIES.length - 1, Math.floor(phrase * TRIGGER_FAMILIES.length));
  return TRIGGER_FAMILIES[index];
}

export class Scheduler {
  constructor(engine, { Tone: tone = engine.Tone ?? globalThis.Tone, seed = 2130 } = {}) {
    this.engine = engine;
    this.Tone = tone;
    this.seed = seed;
    this.rootMidi = 48;
    this.field = new HarmonicField(this.rootMidi);
    this.allocator = new PitchAllocator(this.field);
    this.conductor = new VoiceConductor({ seed, minPeriod: 20, maxPeriod: 90, smoothTau: 1.2 });
    this.voices = new Map();
    this.tick = 0;
    this.event = null;
  }

  addVoice(voiceId, { behavior, fingerprint = null }) {
    const density = Math.min(1, (this.voices.size + 1) / 20);
    const rng = mulberry32((fingerprint?.seed ?? voiceId) ^ this.seed ^ voiceId);
    const detuneClass = behavior === "drone" ? "background" : "foreground";
    const assignment = this.allocator.allocate(voiceId, rng, density, detuneClass);
    const [minBeats, maxBeats] = BEHAVIOR_PERIODS[behavior] ?? BEHAVIOR_PERIODS.pluck;
    const motion = fingerprint?.motionBias ?? 0.35;
    const family = triggerFamily(fingerprint);
    const periodBeats = (maxBeats - (maxBeats - minBeats) * motion) * family.speed;
    this.voices.set(voiceId, {
      behavior,
      fingerprint,
      detuneClass,
      assignment,
      rng,
      family,
      periodTicks: Math.max(1, Math.round(periodBeats * TICKS_PER_BEAT)),
      tickOffset: Math.floor(rng() * Math.max(1, Math.round(periodBeats * TICKS_PER_BEAT))),
      lastTriggerTick: -Infinity,
      burstRemaining: 0,
    });
  }

  removeVoice(voiceId) {
    this.engine.setVoiceMacro(voiceId, null);
    this.allocator.release(voiceId);
    this.voices.delete(voiceId);
  }

  setVoiceMacro(voiceId, macroId) {
    const voice = this.voices.get(voiceId);
    if (!voice) return;
    voice.macroId = macroId ?? null;
    this.engine.setVoiceMacro(voiceId, macroId);
    if (!macroId) this.engine.releaseVoice(voiceId);
  }

  setRoot(midi) {
    this.rootMidi = clamp(midi, ROOT_MIN, ROOT_MAX);
    this.field.rootMidi = this.rootMidi;
  }

  setMood(mood) {
    this.field.setMood(mood);
    this.allocator = new PitchAllocator(this.field);
    const density = Math.min(1, this.voices.size / 20);
    for (const [id, voice] of this.voices) {
      voice.assignment = this.allocator.allocate(id, voice.rng, density, voice.detuneClass);
    }
  }

  midiForVoice(voice) {
    const { role, octave, detuneCents } = voice.assignment;
    return this.rootMidi + this.field.semitoneForRole(role) + 12 * octave + detuneCents / 100.0;
  }

  start() {
    if (this.event !== null) return;
    this.event = this.Tone.Transport.scheduleRepeat(() => this._tick(), TICK_SUBDIVISION);
  }

  stop() {
    if (this.event === null) return;
    this.Tone.Transport.clear(this.event);
    this.event = null;
  }

  _tick() {
    const currentTick = this.tick++;
    const activeIds = [...this.voices.keys()].filter((id) => this.voices.get(id).macroId);
    const dt = this.Tone.Time(TICK_SUBDIVISION).toSeconds();
    const gains = this.conductor.update(activeIds, dt);
    for (const id of activeIds) {
      this.engine.setVoiceGain(id, gains.get(id) ?? 0, 0.18);
    }
    for (const id of activeIds) {
      const voice = this.voices.get(id);
      if (!voice) continue;
      const due = (currentTick + voice.tickOffset) % voice.periodTicks === 0;
      if (["pad", "bloom", "drone"].includes(voice.behavior)) {
        if (!this.engine.isVoiceHeld(id)) this.engine.triggerVoice(id, this.midiForVoice(voice), null);
        if (voice.behavior === "bloom" && due && voice.rng() < 0.16 + (voice.fingerprint?.densityBias ?? 0.3) * 0.14) {
          this.engine.releaseVoice(id);
          this.engine.triggerVoice(id, this.midiForVoice(voice), null);
        }
        continue;
      }
      if (!due && voice.burstRemaining <= 0) continue;
      const density = voice.fingerprint?.densityBias ?? 0.35;
      const inBurst = voice.burstRemaining > 0;
      const probability = inBurst ? 0.92 : (voice.behavior === "bell" ? 0.22 + density * 0.42 : 0.34 + density * 0.48) * voice.family.probability;
      if (voice.rng() > probability) {
        if (inBurst) voice.burstRemaining -= 1;
        continue;
      }
      const dur = voice.behavior === "bell" ? 1.8 : 2.4;
      voice.lastTriggerTick = currentTick;
      this.engine.triggerVoice(id, this.midiForVoice(voice), dur);
      if (inBurst) {
        voice.burstRemaining -= 1;
      } else if (voice.rng() < voice.family.clusterChance * (voice.fingerprint?.clusterBias ?? 0.35)) {
        voice.burstRemaining = voice.family.clusterLength;
      }
    }
  }
}
