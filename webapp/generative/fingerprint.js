function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

function hashFloat(value, scale) {
  return Math.round(value * scale) | 0;
}

export function deriveFingerprint({ hue, sat, val, bpm }) {
  const h = clamp(Number.isFinite(hue) ? hue : 0, 0, 1);
  const s = clamp(Number.isFinite(sat) ? sat : 0.68, 0, 1);
  const v = clamp(Number.isFinite(val) ? val : 0.94, 0, 1);
  const b = clamp(Number.isFinite(bpm) ? bpm : 70, 20, 300);
  const bpmNorm = (b - 20) / 280;
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
    seed: seed >>> 0,
    harmonicBias: Math.floor(h * 6),
    registerBias: clamp(0.25 + h * 0.65 + (v - 0.5) * 0.2, 0, 1),
    brightnessBias: clamp(0.2 + v * 0.55 + s * 0.25, 0, 1),
    motionBias: clamp(0.15 + bpmNorm * 0.75, 0, 1),
    densityBias: clamp(0.1 + bpmNorm * 0.55 + s * 0.2, 0, 1),
    softnessBias: clamp(1 - (s * 0.45 + v * 0.25), 0, 1),
    washBias: clamp(0.25 + v * 0.35 + (1 - s) * 0.25, 0, 1),
  };
}
