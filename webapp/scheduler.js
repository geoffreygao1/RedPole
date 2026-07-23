import { TRIGGER_PRESETS } from "./triggers.js?v=20260723-faster-triggers";

const ROOT_MIN = 36;
const ROOT_MAX = 60;
const TICK_SUBDIVISION = "16n";
const TICKS_PER_BEAT = 4; // 16th notes per quarter-note beat

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

// Drives every connected voice from ONE shared Tone.Transport tick instead of
// each source's own scanned BPM. A per-voice free-running clock drifts out
// of phase with every other voice over time (different BPMs are unrelated
// multiples of each other); checking a shared tick counter keeps every
// voice's pattern phase-locked to the same clock and to each other.
export class Scheduler {
  constructor(engine, { Tone: tone = engine.Tone ?? globalThis.Tone } = {}) {
    this.engine = engine;
    this.Tone = tone;
    this.rootMidi = 60;
    this.voices = new Map(); // voiceId -> {behavior, semitoneOffset, centsOffset, triggerId, tickOffset}
    this.tick = 0;
    this.event = null;
  }

  addVoice(voiceId, { behavior, semitoneOffset = 0, centsOffset = 0 }) {
    this.voices.set(voiceId, {
      behavior,
      semitoneOffset,
      centsOffset,
      triggerId: null,
      // A small per-voice tick offset (derived from the id) so same-pattern
      // voices don't all land on tick 0 in lockstep -- they still share the
      // same period/phase grid, just started at a different point on it.
      tickOffset: voiceId % TICKS_PER_BEAT,
    });
  }

  removeVoice(voiceId) {
    this.setVoiceTrigger(voiceId, null);
    this.voices.delete(voiceId);
  }

  // Cabling a source onto a trigger-grid cell connects it (audible) and gives
  // it a pattern; uncabling (triggerId=null) disconnects it (silent, zero
  // audio-node cost -- see ToneEngine.setVoiceConnected).
  setVoiceTrigger(voiceId, triggerId) {
    const voice = this.voices.get(voiceId);
    if (!voice) return;
    voice.triggerId = triggerId ?? null;
    this.engine.setVoiceConnected(voiceId, Boolean(triggerId));
    if (!triggerId) this.engine.releaseVoice(voiceId);
  }

  setRoot(midi) {
    this.rootMidi = clamp(midi, ROOT_MIN, ROOT_MAX);
  }

  midiForVoice(voice) {
    return this.rootMidi + voice.semitoneOffset + voice.centsOffset / 100.0;
  }

  noteDurationForPreset(preset) {
    return preset.beatsPerStep >= 8 ? 3.0 : 0.6;
  }

  triggerVoiceNow(voiceId) {
    const voice = this.voices.get(voiceId);
    const preset = TRIGGER_PRESETS[voice?.triggerId];
    if (!voice || !preset) return;
    this.engine.triggerVoice(voiceId, this.midiForVoice(voice), this.noteDurationForPreset(preset));
  }

  triggerConnectedVoicesNow() {
    for (const voiceId of this.voices.keys()) {
      this.triggerVoiceNow(voiceId);
    }
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
    for (const [id, voice] of this.voices) {
      const preset = TRIGGER_PRESETS[voice.triggerId];
      if (!preset) continue; // uncabled: no pattern, no trigger
      const ticksPerStep = preset.beatsPerStep * TICKS_PER_BEAT;
      if ((currentTick + voice.tickOffset) % ticksPerStep !== 0) continue;
      if (voice.behavior === "pad") {
        const engineVoice = this.engine.voices.get(id);
        if (engineVoice && engineVoice.held) continue; // already sustaining
      }
      if (Math.random() > preset.probability) continue;
      this.engine.triggerVoice(id, this.midiForVoice(voice), this.noteDurationForPreset(preset));
    }
  }
}
