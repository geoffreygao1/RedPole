import { VoiceConductor } from "./generative/conductor.js";
import { HarmonicField, ROLE_SEMITONES } from "./generative/harmony.js";
import { PitchAllocator } from "./generative/allocator.js";
import { mulberry32 } from "./generative/rng.js";

const ROOT_MIN = 36;
const ROOT_MAX = 60;
const TICK_SUBDIVISION = "16n";
const TICKS_PER_BEAT = 4;
const BEHAVIOR_PERIODS = {
  pluck: [2, 8],
  bell: [4, 16],
  pad: [16, 48],
  bloom: [12, 40],
  drone: [32, 96],
};

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
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
    const assignment = this.allocator.allocate(voiceId, rng, density, behavior === "drone" ? "background" : "foreground");
    const [minBeats, maxBeats] = BEHAVIOR_PERIODS[behavior] ?? BEHAVIOR_PERIODS.pluck;
    const motion = fingerprint?.motionBias ?? 0.35;
    const periodBeats = maxBeats - (maxBeats - minBeats) * motion;
    this.voices.set(voiceId, {
      behavior,
      fingerprint,
      assignment,
      rng,
      periodTicks: Math.max(1, Math.round(periodBeats * TICKS_PER_BEAT)),
      tickOffset: voiceId % TICKS_PER_BEAT,
      lastTriggerTick: -Infinity,
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

  midiForVoice(voice) {
    const { role, octave, detuneCents } = voice.assignment;
    return this.rootMidi + ROLE_SEMITONES[role] + 12 * octave + detuneCents / 100.0;
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
      if (["pad", "bloom", "drone"].includes(voice.behavior)) {
        if (!this.engine.isVoiceHeld(id)) this.engine.triggerVoice(id, this.midiForVoice(voice), null);
        continue;
      }
      if ((currentTick + voice.tickOffset) % voice.periodTicks !== 0) continue;
      const density = voice.fingerprint?.densityBias ?? 0.35;
      const probability = voice.behavior === "bell" ? 0.18 + density * 0.32 : 0.3 + density * 0.45;
      if (voice.rng() > probability) continue;
      const dur = voice.behavior === "bell" ? 1.8 : 2.4;
      voice.lastTriggerTick = currentTick;
      this.engine.triggerVoice(id, this.midiForVoice(voice), dur);
    }
  }
}
