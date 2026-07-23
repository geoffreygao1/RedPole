import { CLICKBATH_BASE_URL, INSTRUMENT_NOTE_URLS } from "./generative/instrument-maps.js";
import { midiToHz } from "./generative/harmony.js";

const NEGATIVE_INFINITY_DB = -Infinity;
const DEFAULT_CONNECTED_GAIN = 0.55;
const REVERB_UI_MAX = 1.5;

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
};

const HELD_BEHAVIORS = new Set(["pad"]);

export class ToneEngine {
  constructor({ Tone: tone = globalThis.Tone } = {}) {
    if (!tone) throw new Error("Tone.js global is required before ToneEngine is created.");
    this.Tone = tone;
    this.master = null;
    this.delay = null;
    this.reverb = null;
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
    this.master.chain(this.delay, this.reverb, this.Tone.Destination);

    // Decode every instrument sample ONCE. Per-voice samplers reference these
    // shared buffers (see _buildNodes) instead of re-fetching/re-decoding.
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
    const normalized = clamp(amount / REVERB_UI_MAX, 0, 1);
    rampParam(this.reverb.wet, normalized, 0.05);
  }

  setDelay(amount) {
    if (!this.delay) return;
    rampParam(this.delay.wet, clamp(amount, 0, 1), 0.05);
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

  // A placed-but-uncabled source is pure metadata: NO audio nodes are created,
  // so loading many silent sources into the patch bay costs nothing. The Tone
  // nodes are built lazily the first time the voice is connected (cabled to a
  // trigger-grid cell).
  createVoice(voiceId, { instrument, behavior }) {
    this.disposeVoice(voiceId);
    this.voices.set(voiceId, {
      instrument,
      behavior,
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
    const volume = new this.Tone.Volume(gainToDb(DEFAULT_CONNECTED_GAIN));
    sampler.connect(volume);
    volume.connect(this.master);
    voice.nodes = { sampler, volume };
  }

  _teardownNodes(voice) {
    if (!voice.nodes) return;
    const { sampler, volume } = voice.nodes;
    if (voice.held) {
      try {
        sampler.triggerRelease();
      } catch {
        // ignore
      }
      voice.held = false;
    }
    disconnect(sampler);
    disconnect(volume);
    sampler.dispose();
    volume.dispose();
    voice.nodes = null;
  }

  // Connecting a voice (cabling it to a trigger-grid cell) is what makes it
  // audible; disconnecting tears the DSP down again (silent, zero cost).
  setVoiceConnected(voiceId, connected) {
    const voice = this.voices.get(voiceId);
    if (!voice) return;
    if (connected && !voice.nodes) this._buildNodes(voice);
    if (!connected) this._teardownNodes(voice);
  }

  setVoiceGain(voiceId, gain, rampSeconds = 0.05) {
    const voice = this.voices.get(voiceId);
    if (!voice || !voice.nodes) return;
    rampParam(voice.nodes.volume.volume, gainToDb(clamp(gain, 0, 1)), rampSeconds);
  }

  triggerVoice(voiceId, midi, durationSeconds = null) {
    const voice = this.voices.get(voiceId);
    if (!voice || !voice.nodes) return; // unconnected voices make no sound
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
