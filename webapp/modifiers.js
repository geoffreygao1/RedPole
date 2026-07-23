import { MACRO_COLS, MACRO_ROWS, macroPresetId } from "./soundbath_config.js";

export const MODIFIER_ROWS = MACRO_ROWS;
export const MODIFIER_COLS = MACRO_COLS;

const PRESET_DEFS = {
  veil: [
    { label: "soft", kind: "filter", frequency: 2600, type: "lowpass" },
    { label: "warm", kind: "eq", low: 1.5, mid: -1.5, high: -4 },
    { label: "blur", kind: "chorus", frequency: 0.08, delayTime: 3.5, depth: 0.25, feedback: 0.05, wet: 0.25 },
    { label: "far", kind: "series", nodes: [
      { kind: "filter", frequency: 900, type: "lowpass" },
      { kind: "gain", gain: 0.7 },
    ] },
    { label: "haze", kind: "chorus", frequency: 0.12, delayTime: 7, depth: 0.45, feedback: 0.12, wet: 0.4 },
  ],
  shimmer: [
    { label: "air", kind: "eq", low: -2, mid: -1, high: 2 },
    { label: "fifth shadow", kind: "shadow", interval: 7, gain: 0.18 },
    { label: "octave glint", kind: "shadow", interval: 12, gain: 0.16 },
    { label: "bright halo", kind: "series", nodes: [
      { kind: "filter", frequency: 1200, type: "highpass" },
      { kind: "chorus", frequency: 0.18, delayTime: 4, depth: 0.25, feedback: 0.05, wet: 0.22 },
    ] },
    { label: "rare stars", kind: "shadow", interval: 19, gain: 0.12 },
  ],
  flutter: [
    { label: "slow tremble", kind: "tremolo", frequency: 0.08, depth: 0.18, wet: 0.35 },
    { label: "tape drift", kind: "vibrato", frequency: 0.18, depth: 0.08, wet: 0.35 },
    { label: "filter sway", kind: "autoFilter", frequency: 0.06, depth: 0.35, baseFrequency: 500, octaves: 2.2, wet: 0.35 },
    { label: "choral wobble", kind: "chorus", frequency: 0.25, delayTime: 4, depth: 0.35, feedback: 0.08, wet: 0.32 },
    { label: "deep pulse", kind: "tremolo", frequency: 0.14, depth: 0.35, wet: 0.45 },
  ],
  scatter: [
    { label: "soft recall", kind: "delay", delayTime: 0.11, feedback: 0.12, wet: 0.16 },
    { label: "double", kind: "delay", delayTime: 0.19, feedback: 0.18, wet: 0.2 },
    { label: "fragments", kind: "scatter", density: 0.22, gain: 0.18 },
    { label: "trails", kind: "delay", delayTime: 0.28, feedback: 0.28, wet: 0.25 },
    { label: "constellation", kind: "scatter", density: 0.38, gain: 0.16 },
  ],
  space: [
    { label: "left drift", kind: "pan", pan: -0.35 },
    { label: "right drift", kind: "pan", pan: 0.35 },
    { label: "orbit", kind: "autoPanner", frequency: 0.08, depth: 0.55, wet: 0.55 },
    { label: "wide", kind: "widener", width: 0.6 },
    { label: "distant", kind: "series", nodes: [
      { kind: "filter", frequency: 650, type: "lowpass" },
      { kind: "gain", gain: 0.62 },
    ] },
  ],
};

export const MODIFIER_PRESETS = Object.fromEntries(
  MACRO_ROWS.flatMap((row, rowIndex) =>
    PRESET_DEFS[row].map((preset, col) => [
      macroPresetId(rowIndex, col),
      { id: macroPresetId(rowIndex, col), row, rowIndex, col, ...preset },
    ])
  )
);

function setWet(node, wet) {
  if (wet !== undefined && node.wet && "value" in node.wet) node.wet.value = wet;
  return node;
}

function startIfLfo(node) {
  if (typeof node.start === "function") {
    try { node.start(); } catch { /* Tone node does not expose a no-arg LFO starter. */ }
  }
  return node;
}

function buildNode(Tone, preset) {
  switch (preset.kind) {
    case "gain":
      return new Tone.Gain(preset.gain);
    case "filter":
      return new Tone.Filter({ frequency: preset.frequency, type: preset.type ?? "lowpass" });
    case "eq":
      return new Tone.EQ3({ low: preset.low, mid: preset.mid, high: preset.high });
    case "chorus":
      return startIfLfo(new Tone.Chorus({
        frequency: preset.frequency,
        delayTime: preset.delayTime,
        depth: preset.depth,
        feedback: preset.feedback,
        wet: preset.wet,
      }));
    case "tremolo":
      return startIfLfo(new Tone.Tremolo({ frequency: preset.frequency, depth: preset.depth, wet: preset.wet }));
    case "vibrato":
      return new Tone.Vibrato({ frequency: preset.frequency, depth: preset.depth, wet: preset.wet });
    case "autoFilter":
      return startIfLfo(new Tone.AutoFilter({
        frequency: preset.frequency,
        depth: preset.depth,
        baseFrequency: preset.baseFrequency,
        octaves: preset.octaves,
        wet: preset.wet,
      }));
    case "delay":
      return new Tone.FeedbackDelay({ delayTime: preset.delayTime, feedback: preset.feedback, wet: preset.wet });
    case "pan":
      return new Tone.PanVol({ pan: preset.pan, volume: 0 });
    case "autoPanner":
      return startIfLfo(new Tone.AutoPanner({ frequency: preset.frequency, depth: preset.depth, wet: preset.wet }));
    case "widener":
      return new Tone.StereoWidener(preset.width);
    case "shadow":
    case "scatter":
      return new Tone.Gain(1);
    default:
      throw new Error(`Unsupported macro kind: ${preset.kind}`);
  }
}

export function createMacroNode(Tone, presetId) {
  const preset = MODIFIER_PRESETS[presetId];
  if (!preset) throw new Error(`Unknown macro preset: ${presetId}`);
  if (preset.kind === "series") {
    const input = new Tone.Gain(1);
    const output = new Tone.Gain(1);
    const nodes = preset.nodes.map((nodePreset) => buildNode(Tone, nodePreset));
    let current = input;
    for (const node of nodes) {
      current.connect(node);
      current = node;
    }
    current.connect(output);
    return { input, output, nodes: [input, ...nodes, output], preset };
  }
  const node = setWet(buildNode(Tone, preset), preset.wet);
  return { input: node, output: node, nodes: [node], preset };
}
