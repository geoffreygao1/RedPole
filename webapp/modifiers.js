export const MODIFIER_ROWS = ["stretch", "spectral", "pitch", "grainfx", "spatial"];
export const MODIFIER_COLS = ["I", "II", "III", "IV", "V"];

const PRESET_DEFS = {
  stretch: [
    { label: "smear", kind: "delay", delayTime: 0.06, feedback: 0.25, wet: 0.28 },
    { label: "trail", kind: "delay", delayTime: 0.11, feedback: 0.42, wet: 0.36 },
    { label: "hold", kind: "pitchShift", pitch: 0, windowSize: 0.18, feedback: 0.35, wet: 0.45 },
    { label: "glass", kind: "pitchShift", pitch: 0, windowSize: 0.28, feedback: 0.55, wet: 0.55 },
    { label: "freeze", kind: "delay", delayTime: 0.2, feedback: 0.72, wet: 0.62 },
  ],
  spectral: [
    { label: "soft blur", kind: "chorus", frequency: 0.08, delayTime: 2.5, depth: 0.25, feedback: 0.08, wet: 0.28 },
    { label: "comb veil", kind: "delay", delayTime: 0.035, feedback: 0.5, wet: 0.35 },
    { label: "wide blur", kind: "chorus", frequency: 0.12, delayTime: 6, depth: 0.45, feedback: 0.18, wet: 0.42 },
    { label: "cloud", kind: "freeverb", roomSize: 0.72, dampening: 2800, wet: 0.48 },
    { label: "wash blur", kind: "freeverb", roomSize: 0.9, dampening: 1800, wet: 0.58 },
  ],
  pitch: [
    { label: "oct down", kind: "pitchShift", pitch: -12, windowSize: 0.08, feedback: 0.05, wet: 0.85 },
    { label: "oct up", kind: "pitchShift", pitch: 12, windowSize: 0.08, feedback: 0.04, wet: 0.75 },
    { label: "fifth", kind: "pitchShift", pitch: 7, windowSize: 0.08, feedback: 0.08, wet: 0.65 },
    { label: "drift", kind: "pitchShift", pitch: 0.25, windowSize: 0.16, feedback: 0.18, wet: 0.55 },
    { label: "wide", kind: "pitchShift", pitch: -0.25, windowSize: 0.22, feedback: 0.35, wet: 0.62 },
  ],
  grainfx: [
    { label: "chorus", kind: "chorus", frequency: 0.35, delayTime: 4, depth: 0.35, feedback: 0.08, wet: 0.35 },
    { label: "crush", kind: "bitCrusher", bits: 6, wet: 0.28 },
    { label: "warm drive", kind: "distortion", distortion: 0.18, wet: 0.28 },
    { label: "fold", kind: "chebyshev", order: 20, wet: 0.18 },
    { label: "filter pulse", kind: "autoFilter", frequency: 0.08, depth: 0.45, baseFrequency: 320, octaves: 2.4, wet: 0.45 },
  ],
  spatial: [
    { label: "room", kind: "reverb", decay: 1.8, wet: 0.28 },
    { label: "hall", kind: "reverb", decay: 3.2, wet: 0.34 },
    { label: "plate", kind: "reverb", decay: 4.8, wet: 0.42 },
    { label: "far", kind: "freeverb", roomSize: 0.72, dampening: 3600, wet: 0.5 },
    { label: "wash", kind: "reverb", decay: 8.5, wet: 0.58 },
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

function wetNode(node, wet) {
  if (node.wet) node.wet.value = wet;
  return node;
}

export function createModifierNode(Tone, presetId) {
  const preset = MODIFIER_PRESETS[presetId];
  if (!preset) throw new Error(`Unknown modifier preset: ${presetId}`);
  let node;
  switch (preset.kind) {
    case "reverb":
      node = new Tone.Reverb({ decay: preset.decay, wet: preset.wet });
      break;
    case "freeverb":
      node = new Tone.Freeverb({
        roomSize: preset.roomSize,
        dampening: preset.dampening,
        wet: preset.wet,
      });
      break;
    case "pitchShift":
      node = new Tone.PitchShift({
        pitch: preset.pitch,
        windowSize: preset.windowSize,
        feedback: preset.feedback,
        wet: preset.wet,
      });
      break;
    case "chorus":
      node = new Tone.Chorus({
        frequency: preset.frequency,
        delayTime: preset.delayTime,
        depth: preset.depth,
        feedback: preset.feedback,
        wet: preset.wet,
      });
      if (typeof node.start === "function") node.start();
      break;
    case "bitCrusher":
      node = wetNode(new Tone.BitCrusher({ bits: preset.bits }), preset.wet);
      break;
    case "distortion":
      node = new Tone.Distortion({ distortion: preset.distortion, wet: preset.wet });
      break;
    case "chebyshev":
      node = new Tone.Chebyshev({ order: preset.order, wet: preset.wet });
      break;
    case "autoFilter":
      node = new Tone.AutoFilter({
        frequency: preset.frequency,
        depth: preset.depth,
        baseFrequency: preset.baseFrequency,
        octaves: preset.octaves,
        wet: preset.wet,
      }).start();
      break;
    case "delay":
      node = new Tone.FeedbackDelay({
        delayTime: preset.delayTime,
        feedback: preset.feedback,
        wet: preset.wet,
      });
      break;
    default:
      throw new Error(`Unsupported modifier type: ${preset.kind}`);
  }
  return node;
}
