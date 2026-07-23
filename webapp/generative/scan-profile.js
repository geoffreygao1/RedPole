function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

function hashFloat(value, scale) {
  return Math.round(value * scale) | 0;
}

const FINGER_HUE_MIN = 0.0;
const FINGER_HUE_MAX = 0.085;
const FINGER_SAT_MIN = 0.64;
const FINGER_SAT_MAX = 0.72;
const FINGER_VAL_MIN = 0.9;
const FINGER_VAL_MAX = 0.98;
const BPM_MIN = 45;
const BPM_MAX = 180;

function normalizeRange(value, lo, hi) {
  if (hi <= lo) return 0;
  return clamp((value - lo) / (hi - lo), 0, 1);
}

export function deriveFingerprint({ hue, sat, val, bpm } = {}) {
  const h = clamp(Number.isFinite(hue) ? hue : 0, 0, 1);
  const s = clamp(Number.isFinite(sat) ? sat : 0.68, 0, 1);
  const v = clamp(Number.isFinite(val) ? val : 0.94, 0, 1);
  const b = clamp(Number.isFinite(bpm) ? bpm : 70, 20, 300);
  const hueNorm = normalizeRange(h, FINGER_HUE_MIN, FINGER_HUE_MAX);
  const satNorm = normalizeRange(s, FINGER_SAT_MIN, FINGER_SAT_MAX);
  const valNorm = normalizeRange(v, FINGER_VAL_MIN, FINGER_VAL_MAX);
  const bpmNorm = normalizeRange(b, BPM_MIN, BPM_MAX);
  const seed =
    (hashFloat(h, 1000000) * 73856093) ^
    (hashFloat(s, 1000000) * 19349663) ^
    (hashFloat(v, 1000000) * 83492791) ^
    (hashFloat(b, 1000) * 2654435761);
  return {
    hue: h,
    sat: s,
    val: v,
    bpm: b,
    hueNorm,
    satNorm,
    valNorm,
    bpmNorm,
    seed: seed >>> 0,
    harmonicBias: Math.min(5, Math.floor(hueNorm * 6)),
    registerBias: clamp(0.2 + hueNorm * 0.65 + (valNorm - 0.5) * 0.18, 0, 1),
    brightnessBias: clamp(0.18 + valNorm * 0.5 + satNorm * 0.28, 0, 1),
    motionBias: clamp(0.08 + bpmNorm * 0.82 + hueNorm * 0.1, 0, 1),
    densityBias: clamp(0.12 + bpmNorm * 0.62 + satNorm * 0.18, 0, 1),
    softnessBias: clamp(1 - (satNorm * 0.48 + valNorm * 0.24), 0, 1),
    washBias: clamp(0.24 + valNorm * 0.4 + (1 - satNorm) * 0.22, 0, 1),
    clusterBias: clamp(hueNorm * 0.55 + bpmNorm * 0.45, 0, 1),
    phraseBias: clamp(hueNorm * 0.35 + bpmNorm * 0.65, 0, 1),
  };
}
