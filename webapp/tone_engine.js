import { CLICKBATH_BASE_URL, INSTRUMENT_NOTE_URLS } from "./generative/instrument-maps.js";
import { midiToHz } from "./generative/harmony.js";
import { createMacroNode } from "./modifiers.js";

const NEGATIVE_INFINITY_DB = -Infinity;

// One shared Transport tempo for every voice's trigger grid, so patterns are
// phase-locked to a single clock instead of each source's own scanned BPM
// (independent per-voice clocks drift out of sync with each other over time).
const TRANSPORT_BPM = 90;

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

function disconnect(node) {
  try {
    node.disconnect();
  } catch {
    // Tone nodes may throw if already disconnected; lifecycle calls are idempotent.
  }
}

const BEHAVIOR_ENVELOPES = {
  pluck: { attack: 0.005, release: 1.5 },
  pad: { attack: 0.4, release: 2.0 },
  bloom: { attack: 1.5, release: 3.5 },
  bell: { attack: 0.002, release: 2.2 },
  drone: { attack: 2.5, release: 5.0 },
};

const HELD_BEHAVIORS = new Set(["pad", "bloom", "drone"]);

export class ToneEngine {
  constructor({ Tone: tone = globalThis.Tone } = {}) {
    if (!tone) throw new Error("Tone.js global is required before ToneEngine is created.");
    this.Tone = tone;
    this.master = null;
    this.delay = null;
    this.reverb = null;
    this.transpose = null;
    this.limiter = null;
    this.buffers = null;
    this.voices = new Map();
    this._started = false;
  }

  async init() {
    if (this.master) return;
    this.Tone.Transport.bpm.value = TRANSPORT_BPM;
    this.master = new this.Tone.Gain(this.Tone.dbToGain(-6));
    // Matches clickbath's wash character: a long convolution reverb (~10s
    // decay, clickbath uses 10) and a tempo-synced feedback delay with a long
    // trailing echo (clickbath: FeedbackDelay('2n', 0.85)).
    this.delay = new this.Tone.FeedbackDelay({ delayTime: "4n", feedback: 0.78, wet: 0 });
    this.reverb = new this.Tone.Reverb({ decay: 10, wet: 0 });
    this.transpose = new this.Tone.PitchShift({ pitch: 0, windowSize: 0.08, delayTime: 0.03, feedback: 0, wet: 1 });
    this.limiter = new this.Tone.Limiter(-1);
    this.master.chain(this.transpose, this.delay, this.reverb, this.limiter, this.Tone.Destination);

    // Decode every instrument sample ONCE. Per-voice samplers reference these
    // shared buffers (see _buildNodes) instead of re-fetching/re-decoding.
    const urls = {};
    for (const [instrument, notes] of Object.entries(INSTRUMENT_NOTE_URLS)) {
      for (const [note, file] of Object.entries(notes)) {
        urls[`${instrument}_${note}`] = file;
      }
    }
    this.buffers = new this.Tone.Buffers({ urls, baseUrl: CLICKBATH_BASE_URL });
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

  setTranspose(semitones) {
    if (!this.transpose) return;
    const value = Number.isFinite(semitones) ? semitones : 0;
    // Tone 14.7.77 exposes PitchShift.pitch as a numeric property, not a Param.
    this.transpose.pitch = clamp(value, -12, 12);
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

  // Placed sources start as pure metadata: no Tone nodes are created until the
  // first macro assignment. After uncabling, built nodes may remain but are
  // disconnected and silent until a macro is assigned again.
  createVoice(voiceId, { instrument, behavior, fingerprint = null }) {
    this.disposeVoice(voiceId);
    this.voices.set(voiceId, {
      instrument,
      behavior,
      fingerprint,
      macro: null,
      macroId: null,
      connected: false,
      nodes: null,
      held: false,
    });
  }

  _buildNodes(voice) {
    const env = BEHAVIOR_ENVELOPES[voice.behavior] ?? BEHAVIOR_ENVELOPES.pluck;
    const noteMap = INSTRUMENT_NOTE_URLS[voice.instrument] ?? INSTRUMENT_NOTE_URLS.piano;
    const urls = {};
    for (const note of Object.keys(noteMap)) {
      // Reuse the already-decoded shared buffer -> no per-voice fetch/decode.
      urls[note] = this.buffers.get(`${voice.instrument}_${note}`);
    }
    const sampler = new this.Tone.Sampler({ urls, attack: env.attack, release: env.release });
    const input = new this.Tone.Gain(1);
    const volume = new this.Tone.Volume(NEGATIVE_INFINITY_DB);
    sampler.connect(input);
    input.connect(volume);
    voice.nodes = { sampler, input, volume };
  }

  _disposeMacro(voice) {
    if (!voice.macro) return;
    if (voice.nodes?.input) {
      try {
        voice.nodes.input.disconnect();
      } catch {
        // already disconnected
      }
    }
    for (const node of voice.macro.nodes ?? []) {
      try {
        node.disconnect();
      } catch {
        // already disconnected
      }
      if (typeof node.dispose === "function") node.dispose();
    }
    voice.macro = null;
    voice.macroId = null;
  }

  _connectVoiceChain(voice) {
    const { input, volume } = voice.nodes;
    try {
      input.disconnect();
    } catch {
      // reconnecting
    }
    if (voice.macro) {
      input.connect(voice.macro.input);
      voice.macro.output.connect(volume);
    } else {
      input.connect(volume);
    }
    try {
      volume.disconnect();
    } catch {
      // reconnecting
    }
    if (voice.connected) volume.connect(this.master);
  }

  setVoiceMacro(voiceId, macroId) {
    const voice = this.voices.get(voiceId);
    if (!voice) return;
    if (macroId && !voice.nodes) this._buildNodes(voice);
    if (!macroId) {
      voice.connected = false;
      if (voice.nodes) {
        this._disposeMacro(voice);
        try {
          voice.nodes.volume.disconnect();
        } catch {
          // already disconnected
        }
        this.releaseVoice(voiceId);
      }
      return;
    }
    const nextMacro = createMacroNode(this.Tone, macroId);
    this._disposeMacro(voice);
    voice.macro = nextMacro;
    voice.macroId = macroId;
    voice.connected = true;
    this._connectVoiceChain(voice);
  }

  setVoiceConnected(voiceId, connected) {
    if (connected) return;
    this.setVoiceMacro(voiceId, null);
  }

  _teardownNodes(voice) {
    if (!voice.nodes) return;
    const { sampler, input, volume } = voice.nodes;
    if (voice.held) {
      try {
        sampler.triggerRelease();
      } catch {
        // ignore
      }
      voice.held = false;
    }
    this._disposeMacro(voice);
    disconnect(sampler);
    disconnect(input);
    disconnect(volume);
    sampler.dispose();
    input.dispose();
    volume.dispose();
    voice.nodes = null;
  }

  setVoiceGain(voiceId, gain, rampSeconds = 0.05) {
    const voice = this.voices.get(voiceId);
    if (!voice || !voice.nodes) return;
    rampParam(voice.nodes.volume.volume, gainToDb(clamp(gain, 0, 1)), rampSeconds);
  }

  triggerVoice(voiceId, midi, durationSeconds = null) {
    const voice = this.voices.get(voiceId);
    if (!voice || !voice.nodes || !voice.connected || !voice.macro) return;
    const frequency = midiToHz(midi);
    if (HELD_BEHAVIORS.has(voice.behavior)) {
      if (!voice.held) {
        voice.nodes.sampler.triggerAttack(frequency);
        voice.held = true;
      }
      return;
    }
    voice.nodes.sampler.triggerAttackRelease(frequency, durationSeconds ?? 0.5);
  }

  isVoiceHeld(voiceId) {
    return Boolean(this.voices.get(voiceId)?.held);
  }

  voiceMacroPreset(voiceId) {
    return this.voices.get(voiceId)?.macro?.preset ?? null;
  }

  releaseVoice(voiceId) {
    const voice = this.voices.get(voiceId);
    if (!voice || !voice.nodes || !voice.held) return;
    voice.nodes.sampler.triggerRelease();
    voice.held = false;
  }

  disposeVoice(voiceId) {
    const voice = this.voices.get(voiceId);
    if (!voice) return;
    this._teardownNodes(voice);
    this.voices.delete(voiceId);
  }
}
