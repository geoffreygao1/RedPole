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

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

function setWet(node, wet) {
  if (wet !== undefined && node.wet && "value" in node.wet) node.wet.value = wet;
  return node;
}

// Depth is a global 0-2 knob (1 = the authored preset strength, this file's
// literal numbers). Each macro `kind` has its own notion of "stronger" --
// scaling every kind by one generic multiplier would push a lowpass filter
// the WRONG way (higher frequency = less filtering, not more), so each kind
// gets its own scaling rule instead of a single formula.
function scaleWet(baseWet, depth) {
  return clamp((baseWet ?? 0) * depth, 0, 1);
}

function scaleDepthParam(baseDepth, depth) {
  return clamp((baseDepth ?? 0) * depth, 0, 1);
}

function scaleGainReduction(baseGain, depth) {
  // baseGain < 1 means "attenuated"; push further from unity as depth rises,
  // back toward unity (no reduction) as depth falls toward 0.
  return clamp(1 - (1 - baseGain) * depth, 0, 1);
}

function scaleFilterFrequency(baseFrequency, type, depth) {
  const safeDepth = Math.max(depth, 0.01);
  if (type === "highpass") return clamp(baseFrequency * safeDepth, 20, 12000);
  return clamp(baseFrequency / safeDepth, 60, 18000);
}

function scaleEQDb(baseDb, depth) {
  return clamp((baseDb ?? 0) * depth, -12, 12);
}

function scalePan(basePan, depth) {
  return clamp(basePan * depth, -1, 1);
}

function scaleWidth(baseWidth, depth) {
  // StereoWidener's neutral/unmodified-stereo point is 0.5, not 0 (0 is fully
  // collapsed to mono) -- depth 0 must land there, not at mono.
  return clamp(0.5 + (baseWidth - 0.5) * depth, 0, 1);
}

function scaleFeedback(baseFeedback, depth) {
  return clamp(baseFeedback * depth, 0, 0.95);
}

// Shadow/scatter aren't audio-graph nodes (their whole effect is a
// scheduler-triggered companion note), so their "depth" scales the values
// scheduler.js reads at trigger time -- see ToneEngine.voiceMacroPreset().
export function scaleTriggerPreset(preset, depth) {
  if (preset.kind === "shadow") {
    return { ...preset, gain: scaleWet(preset.gain, depth) };
  }
  if (preset.kind === "scatter") {
    return { ...preset, gain: scaleWet(preset.gain, depth), density: scaleWet(preset.density, depth), effectDepth: depth };
  }
  return preset;
}

// Tone.js exposes some of these (wet, gain, frequency) as Param objects with
// a settable .value, and others (e.g. an effect's `depth`) as plain numeric
// properties depending on the node class -- set whichever shape it actually
// is rather than assuming, so this can't throw if a given build differs.
function setParam(node, key, value) {
  const param = node?.[key];
  if (param && typeof param === "object" && "value" in param) {
    param.value = value;
  } else if (typeof param === "number") {
    node[key] = value;
  }
}

function applyDepthToNode(node, preset, depth) {
  switch (preset.kind) {
    case "gain":
      setParam(node, "gain", scaleGainReduction(preset.gain, depth));
      return;
    case "filter":
      setParam(node, "frequency", scaleFilterFrequency(preset.frequency, preset.type ?? "lowpass", depth));
      return;
    case "eq":
      setParam(node, "low", scaleEQDb(preset.low, depth));
      setParam(node, "mid", scaleEQDb(preset.mid, depth));
      setParam(node, "high", scaleEQDb(preset.high, depth));
      return;
    case "chorus":
    case "tremolo":
    case "autoFilter":
    case "autoPanner":
    case "vibrato":
      setParam(node, "wet", scaleWet(preset.wet, depth));
      setParam(node, "depth", scaleDepthParam(preset.depth, depth));
      return;
    case "delay":
      setParam(node, "wet", scaleWet(preset.wet, depth));
      setParam(node, "feedback", scaleFeedback(preset.feedback, depth));
      return;
    case "pan":
      setParam(node, "pan", scalePan(preset.pan, depth));
      return;
    case "widener":
      setParam(node, "width", scaleWidth(preset.width, depth));
      return;
    default:
      return; // shadow/scatter: no audio-graph node to touch
  }
}

// Re-applies depth scaling to an already-built macro's LIVE nodes, always
// relative to the original authored preset (macro.preset) so repeated calls
// don't compound. Called both right after createMacroNode() and whenever the
// global Depth knob changes.
export function applyDepthToMacro(macro, depth) {
  if (!macro) return;
  const preset = macro.preset;
  if (preset.kind === "series") {
    const subNodes = macro.nodes.slice(1, -1);
    subNodes.forEach((node, i) => applyDepthToNode(node, preset.nodes[i], depth));
  } else {
    applyDepthToNode(macro.nodes[0], preset, depth);
  }
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

export function createMacroNode(Tone, presetId, depth = 1) {
  const preset = MODIFIER_PRESETS[presetId];
  if (!preset) throw new Error(`Unknown macro preset: ${presetId}`);
  let macro;
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
    macro = { input, output, nodes: [input, ...nodes, output], preset };
  } else {
    const node = setWet(buildNode(Tone, preset), preset.wet);
    macro = { input: node, output: node, nodes: [node], preset };
  }
  applyDepthToMacro(macro, depth);
  return macro;
}
