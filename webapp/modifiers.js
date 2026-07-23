export const MODIFIER_ROWS = ["stretch", "spectral", "pitch", "grainfx", "spatial"];
export const MODIFIER_COLS = ["I", "II", "III", "IV", "V"];

// All modifiers are LIGHT, native Tone.js nodes. Deliberately NO per-voice
// convolution reverb / Freeverb / PitchShift -- those are heavy and (for
// reverb) redundant with the global reverb+delay wash on the master bus.
const PRESET_DEFS = {
  // Sustain / smear via feedback delays (cheap). smear -> near-freeze.
  stretch: [
    { label: "smear", kind: "delay", delayTime: 0.06, feedback: 0.25, wet: 0.3 },
    { label: "trail", kind: "delay", delayTime: 0.12, feedback: 0.45, wet: 0.4 },
    { label: "hold", kind: "delay", delayTime: 0.18, feedback: 0.65, wet: 0.5 },
    { label: "drift", kind: "pingPong", delayTime: 0.2, feedback: 0.5, wet: 0.45 },
    { label: "freeze", kind: "delay", delayTime: 0.25, feedback: 0.82, wet: 0.6 },
  ],
  // Blur / veil via chorus, comb-delay, phaser, vibrato (cheap).
  spectral: [
    { label: "soft blur", kind: "chorus", frequency: 0.08, delayTime: 2.5, depth: 0.25, feedback: 0.08, wet: 0.3 },
    { label: "comb veil", kind: "delay", delayTime: 0.02, feedback: 0.55, wet: 0.35 },
    { label: "wide blur", kind: "chorus", frequency: 0.15, delayTime: 6, depth: 0.5, feedback: 0.2, wet: 0.45 },
    { label: "swirl", kind: "phaser", frequency: 0.3, octaves: 3, baseFrequency: 400, wet: 0.5 },
    { label: "shimmer", kind: "vibrato", frequency: 4, depth: 0.3, wet: 0.5 },
  ],
  // Single-sideband frequency shift (cheap, native). Inharmonic detune/shimmer.
  pitch: [
    { label: "down", kind: "freqShift", frequency: -180, wet: 0.8 },
    { label: "up", kind: "freqShift", frequency: 180, wet: 0.7 },
    { label: "shimmer", kind: "freqShift", frequency: 60, wet: 0.6 },
    { label: "detune", kind: "freqShift", frequency: -20, wet: 0.55 },
    { label: "wide", kind: "freqShift", frequency: 360, wet: 0.6 },
  ],
  // Texture / waveshaping (all light, native).
  grainfx: [
    { label: "chorus", kind: "chorus", frequency: 0.35, delayTime: 4, depth: 0.35, feedback: 0.08, wet: 0.35 },
    { label: "crush", kind: "bitCrusher", bits: 6, wet: 0.28 },
    { label: "warm drive", kind: "distortion", distortion: 0.18, wet: 0.28 },
    { label: "fold", kind: "chebyshev", order: 20, wet: 0.18 },
    { label: "filter pulse", kind: "autoFilter", frequency: 0.08, depth: 0.45, baseFrequency: 320, octaves: 2.4, wet: 0.45 },
  ],
  // Spatial MOVEMENT (rotate/space/swirl/distance) -- no per-voice reverb; the
  // global wash reverberates everything already.
  spatial: [
    { label: "rotate", kind: "autoPanner", frequency: 0.1, depth: 0.8, wet: 0.6 },
    { label: "wide rotate", kind: "autoPanner", frequency: 0.28, depth: 1.0, wet: 0.7 },
    { label: "ping space", kind: "pingPong", delayTime: 0.25, feedback: 0.35, wet: 0.4 },
    { label: "far", kind: "filter", frequency: 700, filterType: "lowpass" },
    { label: "swirl", kind: "phaser", frequency: 0.2, octaves: 3, baseFrequency: 300, wet: 0.5 },
  ],
};

export const MODIFIER_PRESETS = Object.fromEntries(
  MODIFIER_ROWS.flatMap((row) =>
    PRESET_DEFS[row].map((preset, index) => [
      `${row}_${index + 1}`,
      { id: `${row}_${index + 1}`, row, col: index, ...preset },
    ])
  )
);

function setWet(node, wet) {
  if (wet !== undefined && node.wet && "value" in node.wet) node.wet.value = wet;
  return node;
}

function startIfLfo(node) {
  // AutoPanner/AutoFilter/Chorus/Tremolo need their LFO started; Phaser/Vibrato
  // auto-run. Guard so we only call start() when it exists as a no-arg starter.
  if (typeof node.start === "function") {
    try {
      node.start();
    } catch {
      // some nodes' start() needs a time arg / isn't an LFO starter; ignore.
    }
  }
  return node;
}

export function createModifierNode(Tone, presetId) {
  const preset = MODIFIER_PRESETS[presetId];
  if (!preset) throw new Error(`Unknown modifier preset: ${presetId}`);
  switch (preset.kind) {
    case "freqShift": {
      const node = new Tone.FrequencyShifter(preset.frequency);
      return setWet(node, preset.wet);
    }
    case "chorus":
      return startIfLfo(
        new Tone.Chorus({
          frequency: preset.frequency,
          delayTime: preset.delayTime,
          depth: preset.depth,
          feedback: preset.feedback,
          wet: preset.wet,
        })
      );
    case "phaser":
      return new Tone.Phaser({
        frequency: preset.frequency,
        octaves: preset.octaves,
        baseFrequency: preset.baseFrequency,
        wet: preset.wet,
      });
    case "vibrato":
      return new Tone.Vibrato({ frequency: preset.frequency, depth: preset.depth, wet: preset.wet });
    case "autoPanner":
      return startIfLfo(
        new Tone.AutoPanner({ frequency: preset.frequency, depth: preset.depth, wet: preset.wet })
      );
    case "autoFilter":
      return startIfLfo(
        new Tone.AutoFilter({
          frequency: preset.frequency,
          depth: preset.depth,
          baseFrequency: preset.baseFrequency,
          octaves: preset.octaves,
          wet: preset.wet,
        })
      );
    case "delay":
      return new Tone.FeedbackDelay({
        delayTime: preset.delayTime,
        feedback: preset.feedback,
        wet: preset.wet,
      });
    case "pingPong":
      return new Tone.PingPongDelay({
        delayTime: preset.delayTime,
        feedback: preset.feedback,
        wet: preset.wet,
      });
    case "filter":
      return new Tone.Filter({ frequency: preset.frequency, type: preset.filterType ?? "lowpass" });
    case "bitCrusher":
      return setWet(new Tone.BitCrusher({ bits: preset.bits }), preset.wet);
    case "distortion":
      return new Tone.Distortion({ distortion: preset.distortion, wet: preset.wet });
    case "chebyshev":
      return new Tone.Chebyshev({ order: preset.order, wet: preset.wet });
    default:
      throw new Error(`Unsupported modifier type: ${preset.kind}`);
  }
}
