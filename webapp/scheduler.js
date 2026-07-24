import { VoiceConductor } from "./generative/conductor.js";
import { HarmonicField, MIN_VOICE_MIDI, MAX_VOICE_MIDI } from "./generative/harmony.js?v=20260723-root-note-scale";
import { PitchAllocator } from "./generative/allocator.js?v=20260723-trigger-families";
import { mulberry32 } from "./generative/rng.js";
import { shadowMidi, scatterMidi, ticksForSeconds } from "./generative/voicing.js";

const ROOT_MIN = 36;
const ROOT_MAX = 60;
const TICK_SUBDIVISION = "16n";
const TICKS_PER_BEAT = 4;
const GARNISH_BEHAVIORS = new Set(["pluck", "bell"]);
const GARNISH_TICK_INTERVAL = 2;
const REVOICE_MIN_SECONDS = 45;
const REVOICE_MAX_SECONDS = 150;
const BEHAVIOR_PERIODS = {
  pluck: [0.5, 4],
  bell: [0.75, 7],
  pad: [8, 24],
  bloom: [5, 18],
  drone: [16, 48],
};
const TRIGGER_FAMILIES = [
  { name: "still", speed: 0.9, probability: 0.56, clusterChance: 0, clusterLength: 0 },
  { name: "breath", speed: 0.72, probability: 0.64, clusterChance: 0.08, clusterLength: 1 },
  { name: "pulse", speed: 0.5, probability: 0.76, clusterChance: 0.16, clusterLength: 1 },
  { name: "ripple", speed: 0.34, probability: 0.84, clusterChance: 0.32, clusterLength: 2 },
  { name: "spark", speed: 0.22, probability: 0.7, clusterChance: 0.44, clusterLength: 3 },
];

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

function triggerFamily(fingerprint) {
  const phrase = fingerprint?.phraseBias ?? 0.3;
  const index = Math.min(TRIGGER_FAMILIES.length - 1, Math.floor(phrase * TRIGGER_FAMILIES.length));
  return TRIGGER_FAMILIES[index];
}

function garnishChance(voice) {
  const density = voice.fingerprint?.densityBias ?? 0.35;
  const cluster = voice.fingerprint?.clusterBias ?? 0.35;
  const motion = voice.fingerprint?.motionBias ?? 0.35;
  const base = voice.behavior === "bell" ? 0.006 : 0.01;
  return base + density * 0.012 + cluster * 0.01 + motion * 0.008;
}

function garnishDuration(voice) {
  return voice.behavior === "bell" ? 0.75 : 0.45;
}

export class Scheduler {
  constructor(engine, { Tone: tone = engine.Tone ?? globalThis.Tone, seed = 2130 } = {}) {
    this.engine = engine;
    this.Tone = tone;
    this.seed = seed;
    this.rootMidi = 36;
    this.transposeSemitones = 0;
    this.field = new HarmonicField(this.rootMidi);
    this.allocator = new PitchAllocator(this.field);
    this.conductor = new VoiceConductor({ seed, minPeriod: 20, maxPeriod: 90, smoothTau: 1.2 });
    this.voices = new Map();
    this.tick = 0;
    this.event = null;
    this.dtSeconds = this.Tone.Time(TICK_SUBDIVISION).toSeconds();
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
    const periodTicks = Math.max(1, Math.round(periodBeats * TICKS_PER_BEAT));
    const isHeld = ["pad", "bloom", "drone"].includes(behavior);
    const revoiceSeconds = REVOICE_MIN_SECONDS + (REVOICE_MAX_SECONDS - REVOICE_MIN_SECONDS) * rng();
    const revoicePeriodTicks = isHeld ? ticksForSeconds(revoiceSeconds, this.dtSeconds) : Infinity;
    this.voices.set(voiceId, {
      behavior,
      fingerprint,
      detuneClass,
      assignment,
      rng,
      family,
      periodTicks,
      tickOffset: Math.floor(rng() * periodTicks),
      lastTriggerTick: -Infinity,
      burstRemaining: 0,
      revoicePeriodTicks,
      revoiceTickOffset: Number.isFinite(revoicePeriodTicks) ? Math.floor(rng() * revoicePeriodTicks) : 0,
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

  // Whole-octave steps only. An octave lines up with real recorded samples
  // (piano/tapebell/casio/strings all sample every octave), so shifting by
  // exact octaves and letting the sampler pick the nearest real sample sounds
  // far cleaner than running the whole mix through a real-time granular
  // PitchShift effect (the previous approach) ever did.
  setTranspose(semitones) {
    const value = Number.isFinite(semitones) ? semitones : 0;
    this.transposeSemitones = Math.round(value / 12) * 12;
  }

  midiForVoice(voice) {
    const { role, octave, detuneCents } = voice.assignment;
    const midi = this.rootMidi + this.field.semitoneForRole(role) + 12 * octave + this.transposeSemitones + detuneCents / 100.0;
    return clamp(midi, MIN_VOICE_MIDI, MAX_VOICE_MIDI);
  }

  _applyTranspose(midi) {
    return clamp(midi + this.transposeSemitones, MIN_VOICE_MIDI, MAX_VOICE_MIDI);
  }

  immediateDuration(voice) {
    if (["pad", "bloom", "drone"].includes(voice.behavior)) return null;
    return voice.behavior === "bell" ? 1.4 : 1.8;
  }

  triggerVoiceNow(voiceId) {
    const voice = this.voices.get(voiceId);
    if (!voice || !voice.macroId) return;
    this.engine.setVoiceGain(voiceId, 0.55, 0.02);
    this.engine.triggerVoice(voiceId, this.midiForVoice(voice), this.immediateDuration(voice));
    this._triggerCompanions(voiceId, voice);
  }

  triggerConnectedVoicesNow() {
    for (const voiceId of this.voices.keys()) {
      this.triggerVoiceNow(voiceId);
    }
  }

  // At the authored default (Effect Depth 100%) a voice's primary retrigger
  // always lands on its fixed home pitch, same as before Effect Depth
  // existed. Pushing depth above 100% introduces a rising chance of landing
  // on a different (still scale-respecting, ceiling-bounded) pitch instead --
  // this is the "a C source has an increased chance of retriggering at a
  // different pitch at higher depth" behavior, independent of which macro
  // (if any) the voice is cabled to.
  _retriggerMidi(voice) {
    const depth = this.engine.macroDepth ?? 1;
    const chance = clamp((depth - 1) * 0.5, 0, 0.5);
    if (chance > 0 && voice.rng() < chance) {
      return this._applyTranspose(scatterMidi(this.field, voice.rng, voice.assignment, depth));
    }
    return this.midiForVoice(voice);
  }

  _triggerCompanions(voiceId, voice) {
    const preset = this.engine.voiceMacroPreset(voiceId);
    if (!preset) return;
    const baseMidi = this.midiForVoice(voice);
    if (preset.kind === "shadow") {
      this.engine.triggerAccent(voiceId, shadowMidi(baseMidi, preset.interval), 0.6, preset.gain);
    } else if (preset.kind === "scatter" && voice.rng() < preset.density) {
      this.engine.triggerAccent(voiceId, this._applyTranspose(scatterMidi(this.field, voice.rng, voice.assignment, preset.effectDepth)), 0.5, preset.gain);
    }
  }

  _revoiceDue(voice, currentTick) {
    if (!Number.isFinite(voice.revoicePeriodTicks)) return false;
    return (currentTick + voice.revoiceTickOffset) % voice.revoicePeriodTicks === 0;
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
    let powerSum = 0;
    for (const gain of gains.values()) powerSum += gain * gain;
    this.engine.setActiveVoicePower?.(powerSum);
    for (const id of activeIds) {
      const voice = this.voices.get(id);
      if (!voice) continue;
      const due = (currentTick + voice.tickOffset) % voice.periodTicks === 0;
      const garnishDue =
        !due &&
        voice.burstRemaining <= 0 &&
        GARNISH_BEHAVIORS.has(voice.behavior) &&
        currentTick % GARNISH_TICK_INTERVAL === 0;
      if (["pad", "bloom", "drone"].includes(voice.behavior)) {
        if (!this.engine.isVoiceHeld(id)) this.engine.triggerVoice(id, this.midiForVoice(voice), null);
        if (voice.behavior === "bloom" && due && voice.rng() < 0.16 + (voice.fingerprint?.densityBias ?? 0.3) * 0.14) {
          this.engine.releaseVoice(id);
          this.engine.triggerVoice(id, this.midiForVoice(voice), null);
        }
        if (this._revoiceDue(voice, currentTick)) {
          voice.assignment = this.allocator.allocate(id, voice.rng, Math.min(1, this.voices.size / 20), voice.detuneClass);
          this.engine.releaseVoice(id);
          this.engine.triggerVoice(id, this.midiForVoice(voice), null);
        }
        if (due) this._triggerCompanions(id, voice);
        continue;
      }
      if (garnishDue && voice.rng() < garnishChance(voice) * voice.family.probability) {
        this.engine.triggerVoice(id, this.midiForVoice(voice), garnishDuration(voice));
        this._triggerCompanions(id, voice);
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
      this.engine.triggerVoice(id, this._retriggerMidi(voice), dur);
      this._triggerCompanions(id, voice);
      if (inBurst) {
        voice.burstRemaining -= 1;
      } else if (voice.rng() < voice.family.clusterChance * (voice.fingerprint?.clusterBias ?? 0.35)) {
        voice.burstRemaining = voice.family.clusterLength;
      }
    }
  }
}
