// Pure pitch-selection helpers for macro-driven secondary triggers (shadow,
// scatter) and slow held-voice re-voicing. No Tone.js dependency, so these
// stay unit-testable without an audio context.

const WANDER_CHANCE = 0.4;

export function shadowMidi(baseMidi, interval) {
  return baseMidi + interval;
}

// Picks a fresh scale-respecting pitch for a scatter fragment: a new
// weighted role at the voice's home octave, occasionally wandering one
// octave within the mood's spread instead of always echoing the same note.
export function scatterMidi(field, rng, assignment) {
  const role = field.weightedRole(rng);
  const spread = field.octaveSpread();
  const wander = spread > 0 && rng() < WANDER_CHANCE ? (rng() < 0.5 ? -1 : 1) : 0;
  const octave = Math.max(0, assignment.octave + wander);
  return field.midiForRole(role, octave) + assignment.detuneCents / 100.0;
}

export function ticksForSeconds(seconds, dtSeconds) {
  return Math.max(1, Math.round(seconds / dtSeconds));
}
