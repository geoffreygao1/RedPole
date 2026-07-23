import { PitchAllocator } from "./generative/allocator.js";
import { HarmonicField, ROLE_SEMITONES } from "./generative/harmony.js";
import { VoiceConductor } from "./generative/conductor.js";
import { mulberry32 } from "./generative/rng.js";

const ROOT_MIN = 36;
const ROOT_MAX = 60;
const ROLE_BEAT_MULTIPLIER = {
  root: 4,
  fifth: 3,
  fourth: 4,
  ninth: 5,
  seventh: 6,
  tension: 8,
};
const GATE_PROBABILITY = {
  root: 0.85,
  fifth: 0.75,
  fourth: 0.65,
  ninth: 0.55,
  seventh: 0.45,
  tension: 0.3,
};

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

function detuneClassForBehavior(behavior) {
  if (behavior === "bloom") return "granular";
  if (behavior === "pad" || behavior === "drone") return "background";
  return "foreground";
}

function isHeldBehavior(behavior) {
  return behavior === "pad" || behavior === "bloom" || behavior === "drone";
}

export class Scheduler {
  constructor(engine, { seed = 0 } = {}) {
    this.engine = engine;
    this.Tone = engine.Tone ?? globalThis.Tone;
    this.seed = seed;
    this.field = new HarmonicField(48);
    this.allocator = new PitchAllocator(this.field);
    this.conductor = new VoiceConductor({ seed });
    this.voices = new Map();
    this.loop = null;
  }

  addVoice(voiceId, { behavior, bpm }) {
    const activeCount = this.voices.size + 1;
    const density = Math.min(1, activeCount / 20);
    const assignment = this.allocator.allocate(
      voiceId,
      mulberry32(voiceId),
      density,
      detuneClassForBehavior(behavior)
    );
    this.voices.set(voiceId, {
      behavior,
      bpm,
      assignment,
      lastTriggerBeat: -Infinity,
      elapsedBeats: 0,
      rng: mulberry32(this.seed * 1000003 + voiceId),
    });
  }

  removeVoice(voiceId) {
    this.allocator.release(voiceId);
    this.engine.releaseVoice(voiceId);
    this.voices.delete(voiceId);
  }

  setRoot(midi) {
    const root = clamp(midi, ROOT_MIN, ROOT_MAX);
    this.field.rootMidi = root;
    this.engine.setRoot(root);
  }

  start() {
    if (!this.loop) {
      this.loop = new this.Tone.Loop(() => this._tick(), "16n");
    }
    this.loop.start(0);
  }

  stop() {
    if (!this.loop) return;
    this.loop.stop(0);
  }

  _tick() {
    const dt = this.Tone.Time("16n").toSeconds();
    const activeIds = [...this.voices.keys()];
    const gains = this.conductor.update(activeIds, dt);
    for (const id of activeIds) {
      this.engine.setVoiceGain(id, gains.get(id) ?? 0, 0.05);
    }
    for (const [id, voice] of this.voices) {
      if (isHeldBehavior(voice.behavior)) {
        const engineVoice = this.engine.voices.get(id);
        if (!engineVoice || !engineVoice.held) {
          this.engine.triggerVoice(id, this.midiForCurrentRoot(voice.assignment), null);
        }
        continue;
      }
      const secondsPerBeat = 60 / Math.max(20, Math.min(300, voice.bpm || 70));
      const beatsThisTick = dt / secondsPerBeat;
      voice.elapsedBeats += beatsThisTick;
      const beatsPerNote = ROLE_BEAT_MULTIPLIER[voice.assignment.role] ?? 4;
      if (voice.elapsedBeats - voice.lastTriggerBeat < beatsPerNote) continue;
      const gate = GATE_PROBABILITY[voice.assignment.role] ?? 0.5;
      if (voice.rng() <= gate) {
        const noteDur = secondsPerBeat * Math.min(2.5, beatsPerNote * 0.7);
        this.engine.triggerVoice(id, this.midiForCurrentRoot(voice.assignment), noteDur);
      }
      voice.lastTriggerBeat = voice.elapsedBeats;
    }
  }

  midiForCurrentRoot(assignment) {
    return (
      this.field.rootMidi +
      ROLE_SEMITONES[assignment.role] +
      12 * assignment.octave +
      assignment.detuneCents / 100.0
    );
  }
}
