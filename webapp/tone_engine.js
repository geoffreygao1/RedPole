import { CLICKBATH_BASE_URL, INSTRUMENT_NOTE_URLS } from "./generative/instrument-maps.js";
import { midiToHz } from "./generative/harmony.js";
import { createModifierNode } from "./modifiers.js";

const ROOT_MIN = 36;
const ROOT_MAX = 60;
const NEGATIVE_INFINITY_DB = -Infinity;

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

function gainToDb(gain) {
  if (gain <= 0) return NEGATIVE_INFINITY_DB;
  return 20 * Math.log10(gain);
}

function rampParam(param, value, seconds) {
  if (!param) return;
  if (typeof param.rampTo === "function") {
    param.rampTo(value, seconds);
  } else if (typeof param.linearRampToValueAtTime === "function") {
    param.linearRampToValueAtTime(value, seconds);
  } else if ("value" in param) {
    param.value = value;
  }
}

function setPitchShiftPitch(node, pitch, seconds) {
  if (!node) return;
  if (node.pitch && typeof node.pitch.rampTo === "function") {
    node.pitch.rampTo(pitch, seconds);
  } else if (node.pitch && "value" in node.pitch) {
    node.pitch.value = pitch;
  } else {
    node.pitch = pitch;
  }
}

function disconnect(node) {
  try {
    node.disconnect();
  } catch {
    // Tone nodes may throw if already disconnected; lifecycle calls are idempotent.
  }
}

function connectOnce(from, to) {
  disconnect(from);
  from.connect(to);
}

const BEHAVIOR_ENVELOPES = {
  pluck: { attack: 0.005, release: 1.5 },
  pad: { attack: 0.4, release: 2.0 },
  bloom: { attack: 1.5, release: 3.0 },
};

export class ToneEngine {
  constructor({ Tone: tone = globalThis.Tone } = {}) {
    if (!tone) throw new Error("Tone.js global is required before ToneEngine is created.");
    this.Tone = tone;
    this.master = null;
    this.delay = null;
    this.reverb = null;
    this.buffers = null;
    this.rootMidi = 48;
    this.voices = new Map();
    this._started = false;
  }

  async init() {
    if (this.master) return;
    this.master = new this.Tone.Gain(this.Tone.dbToGain(-6));
    this.delay = new this.Tone.FeedbackDelay({ delayTime: 0.4, feedback: 0.5, wet: 0 });
    this.reverb = new this.Tone.Reverb({ decay: 8, wet: 0 });
    this.master.chain(this.delay, this.reverb, this.Tone.Destination);

    const urls = {};
    for (const [instrument, notes] of Object.entries(INSTRUMENT_NOTE_URLS)) {
      for (const [note, file] of Object.entries(notes)) {
        urls[`${instrument}_${note}`] = file;
      }
    }
    this.buffers = new this.Tone.Buffers(urls, { baseUrl: CLICKBATH_BASE_URL });
    await this.Tone.loaded();
  }

  setReverb(amount) {
    if (!this.reverb) return;
    rampParam(this.reverb.wet, clamp(amount, 0, 1.5), 0.05);
  }

  setDelay(amount) {
    if (!this.delay) return;
    rampParam(this.delay.wet, clamp(amount, 0, 1), 0.05);
  }

  setRoot(midiFloat) {
    this.rootMidi = clamp(midiFloat, ROOT_MIN, ROOT_MAX);
    for (const voice of this.voices.values()) {
      if (!voice.held || voice.baseRoot === null) continue;
      setPitchShiftPitch(voice.glide, this.rootMidi - voice.baseRoot, 0.4);
    }
  }

  async resume() {
    await this.Tone.start();
    this._started = true;
    this.Tone.Transport.start();
  }

  pause() {
    this.Tone.Transport.pause();
  }

  get paused() {
    return this.Tone.Transport.state !== "started";
  }

  createVoice(voiceId, { instrument, behavior, hue, sat, val }) {
    this.disposeVoice(voiceId);
    const envelope = BEHAVIOR_ENVELOPES[behavior] ?? BEHAVIOR_ENVELOPES.pluck;
    const urls = INSTRUMENT_NOTE_URLS[instrument] ?? INSTRUMENT_NOTE_URLS.piano;
    const sampler = new this.Tone.Sampler({
      urls,
      baseUrl: CLICKBATH_BASE_URL,
      attack: envelope.attack,
      release: envelope.release,
    });
    const glide = new this.Tone.PitchShift({ pitch: 0, windowSize: 0.08 });
    const volume = new this.Tone.Volume(NEGATIVE_INFINITY_DB);
    sampler.chain(glide, volume);
    this.voices.set(voiceId, {
      sampler,
      glide,
      volume,
      modifier: null,
      modifierId: null,
      behavior,
      instrument,
      hue,
      sat,
      val,
      held: false,
      baseRoot: null,
      baseMidi: null,
      connected: false,
    });
  }

  setVoiceModifier(voiceId, modifierId) {
    const voice = this.voices.get(voiceId);
    if (!voice) return;
    if (voice.modifier) {
      disconnect(voice.glide);
      disconnect(voice.modifier);
      voice.modifier.dispose();
      voice.modifier = null;
      voice.modifierId = null;
      voice.glide.connect(voice.volume);
    }
    if (!modifierId) {
      disconnect(voice.volume);
      voice.connected = false;
      return;
    }
    const modifier = createModifierNode(this.Tone, modifierId);
    connectOnce(voice.glide, modifier);
    modifier.connect(voice.volume);
    if (!voice.connected) {
      voice.volume.connect(this.master);
      voice.connected = true;
    }
    voice.modifier = modifier;
    voice.modifierId = modifierId;
  }

  setVoiceGain(voiceId, gain, rampSeconds = 0.05) {
    const voice = this.voices.get(voiceId);
    if (!voice) return;
    rampParam(voice.volume.volume, gainToDb(clamp(gain, 0, 1)), rampSeconds);
  }

  triggerVoice(voiceId, midi, durationSeconds = null) {
    const voice = this.voices.get(voiceId);
    if (!voice) return;
    const frequency = midiToHz(midi);
    voice.baseMidi = midi;
    voice.baseRoot = this.rootMidi;
    setPitchShiftPitch(voice.glide, 0, 0.02);
    if (voice.behavior === "pad" || voice.behavior === "bloom" || voice.behavior === "drone") {
      if (!voice.held) {
        voice.sampler.triggerAttack(frequency);
        voice.held = true;
      }
      return;
    }
    const dur = durationSeconds ?? 0.5;
    voice.sampler.triggerAttackRelease(frequency, dur);
  }

  releaseVoice(voiceId) {
    const voice = this.voices.get(voiceId);
    if (!voice || !voice.held) return;
    voice.sampler.triggerRelease();
    voice.held = false;
    voice.baseRoot = null;
  }

  disposeVoice(voiceId) {
    const voice = this.voices.get(voiceId);
    if (!voice) return;
    this.releaseVoice(voiceId);
    disconnect(voice.sampler);
    disconnect(voice.glide);
    disconnect(voice.volume);
    if (voice.modifier) {
      disconnect(voice.modifier);
      voice.modifier.dispose();
    }
    voice.sampler.dispose();
    voice.glide.dispose();
    voice.volume.dispose();
    this.voices.delete(voiceId);
  }
}
