import { CLICKBATH_BASE_URL, INSTRUMENT_NOTE_URLS } from "./generative/instrument-maps.js";
import { midiToHz } from "./generative/harmony.js";
import { createMacroNode, applyDepthToMacro, scaleTriggerPreset } from "./modifiers.js";

const NEGATIVE_INFINITY_DB = -Infinity;
const DEFAULT_CONNECTED_GAIN = 0.55;
const REVERB_UI_MAX = 1.5;
const BASE_MASTER_GAIN_DB = -6;

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
    this.limiter = null;
    this.buffers = null;
    this.voices = new Map();
    this._started = false;
    this.macroDepth = 1;
    this._reverbFeedbackBase = 0.72;
    this._delayWet = 0;
    this._voicePowerDb = 0;
    this._reverbHeadroomDb = 0;
  }

  async init() {
    if (this.master) return;
    this.Tone.Transport.bpm.value = TRANSPORT_BPM;
    this.master = new this.Tone.Gain(this.Tone.dbToGain(BASE_MASTER_GAIN_DB));
    // Extends clickbath's wash character with a longer tail and tempo-synced
    // feedback delay for a denser max-wet sound bath.
    this.delay = new this.Tone.FeedbackDelay({ delayTime: "4n", feedback: 0.78, wet: 0 });
    this.reverb = new this.Tone.Reverb({ decay: 20, preDelay: 0.05, wet: 0 });
    this.reverb.decay = 20;
    this.limiter = new this.Tone.Limiter(-1);
    this.master.chain(this.delay, this.reverb, this.limiter, this.Tone.Destination);

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
    const normalized = clamp((Number.isFinite(amount) ? amount : 0) / REVERB_UI_MAX, 0, 1);
    const shaped = normalized * normalized;
    rampParam(this.reverb.wet, clamp(shaped * 1.25, 0, 1), 0.08);
    this._reverbFeedbackBase = clamp(0.72 + shaped * 0.18, 0, 0.92);
    this._applyDelayFeedback();
    // The longer 20s decay rings for longer at any given moment than the
    // previous 14s did, so it accumulates more cumulative energy at high wet
    // -- back off extra headroom as it rises to compensate, the same way
    // setActiveVoicePower() already does for a dense patch.
    this._reverbHeadroomDb = -shaped * 4;
    this._applyMasterGain();
  }

  setDelay(amount) {
    if (!this.delay) return;
    this._delayWet = clamp(Number.isFinite(amount) ? amount : 0, 0, 1);
    rampParam(this.delay.wet, this._delayWet, 0.05);
    this._applyDelayFeedback();
  }

  // Feedback used to be driven solely by the Reverb knob, so turning the
  // Delay knob down only muted the wet/dry OUTPUT mix -- the internal repeat
  // loop kept circulating at Reverb's feedback level regardless of Delay's
  // position, and turning Delay back up later revealed whatever was still
  // silently circulating this whole time, sounding like stale "captured"
  // echoes that never cleared. Scaling feedback by the Delay knob too means
  // Delay all the way down actually starves the loop so it decays away for
  // real, instead of just muting an output that keeps refilling itself.
  _applyDelayFeedback() {
    if (!this.delay) return;
    const base = this._reverbFeedbackBase ?? 0.72;
    const wet = this._delayWet ?? 0;
    rampParam(this.delay.feedback, clamp(base * wet, 0, 0.92), 0.05);
  }

  // Global 0-2 strength knob for the per-voice macro grid (1 = each preset's
  // authored default). Re-applies live to every currently-connected voice's
  // macro so dragging the knob is heard immediately, not just on new cables.
  setMacroDepth(amount) {
    this.macroDepth = clamp(Number.isFinite(amount) ? amount : 1, 0, 2);
    for (const voice of this.voices.values()) {
      if (voice.macro) applyDepthToMacro(voice.macro, this.macroDepth);
    }
  }

  // Master gain was a fixed -6dB regardless of how many voices were actually
  // summing into it -- fine for 1-2 voices, not enough headroom once a dense
  // patch has several simultaneously-loud (foreground-role) voices adding up.
  // powerSum is the sum of each active voice's current gain squared (from the
  // conductor), an approximation of aggregate signal power; back off further
  // as it rises so a dense patch doesn't clip while a sparse one isn't left
  // needlessly quiet.
  setActiveVoicePower(powerSum) {
    if (!this.master) return;
    this._voicePowerDb = -10 * Math.log10(Math.max(1, powerSum));
    this._applyMasterGain();
  }

  // Master gain is the combination of both headroom needs below, applied
  // together instead of one overwriting the other (the same bug the
  // delay/reverb feedback sharing had).
  _applyMasterGain() {
    if (!this.master) return;
    const totalDb = BASE_MASTER_GAIN_DB + (this._voicePowerDb ?? 0) + (this._reverbHeadroomDb ?? 0);
    rampParam(this.master.gain, this.Tone.dbToGain(totalDb), 0.3);
  }

  async resume() {
    await this.Tone.start();
    this._started = true;
    this.Tone.Transport.start();
  }

  // Transport.pause() only stops the scheduler's clock -- it does not
  // silence anything already sounding. Held pad/bloom/drone voices trigger
  // via triggerAttack with no matching triggerRelease until _tick() decides
  // to move them, so without this they keep sustaining (and feeding the
  // shared reverb/delay wash) indefinitely through a pause, which read as
  // "reverb and delay keep going" even after pressing pause.
  pause() {
    for (const voice of this.voices.values()) {
      if (voice.held && voice.nodes) {
        voice.nodes.sampler.triggerRelease();
        voice.held = false;
      }
    }
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
    const volume = new this.Tone.Volume(gainToDb(DEFAULT_CONNECTED_GAIN));
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
    const nextMacro = createMacroNode(this.Tone, macroId, this.macroDepth);
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

  // Fires a short companion note through the SAME sampler as the primary
  // voice, at a reduced velocity, without going through the HELD_BEHAVIORS
  // held-note gate in triggerVoice(). Used by shadow (fixed-interval overtone)
  // and scatter (wandering pitch echo) macros so they can layer a note on top
  // of an already-sustaining pad/bloom/drone voice.
  //
  // The companion's velocity is scaled by the voice's CURRENT conductor-driven
  // gain, not fired at a fixed level -- otherwise a companion note sums with
  // an already-near-full-gain foreground voice's own sample (both play through
  // the same sampler/volume/master chain) with no headroom accounted for,
  // which is what was causing clipping on dense/stacked patches.
  triggerAccent(voiceId, midi, durationSeconds, velocity = 1) {
    const voice = this.voices.get(voiceId);
    if (!voice || !voice.nodes || !voice.connected || !voice.macro) return;
    const frequency = midiToHz(midi);
    const currentGain = this.Tone.dbToGain(voice.nodes.volume.volume.value);
    voice.nodes.sampler.triggerAttackRelease(frequency, durationSeconds, undefined, clamp(velocity * currentGain, 0, 1));
  }

  isVoiceHeld(voiceId) {
    return Boolean(this.voices.get(voiceId)?.held);
  }

  voiceMacroPreset(voiceId) {
    const preset = this.voices.get(voiceId)?.macro?.preset ?? null;
    return preset ? scaleTriggerPreset(preset, this.macroDepth) : null;
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
