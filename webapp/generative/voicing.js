// Pure pitch-selection helpers for macro-driven secondary triggers (shadow,
// scatter) and slow held-voice re-voicing. No Tone.js dependency, so these
// stay unit-testable without an audio context.
import { MAX_VOICE_MIDI } from "./harmony.js";

const WANDER_CHANCE = 0.4;

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

export function shadowMidi(baseMidi, interval) {
  return Math.min(baseMidi + interval, MAX_VOICE_MIDI);
}

// Highest octave for this role that still fits under MAX_VOICE_MIDI. Used to
// bound wander BEFORE picking, not after -- clamping the final result instead
// would let many different high-depth wander attempts all collapse onto the
// same ceiling pitch, which sounds like "no variety" even though the pick
// itself did vary.
function ceilingOctaveFor(field, role) {
  let octave = 0;
  while (field.midiForRole(role, octave + 1) <= MAX_VOICE_MIDI) octave += 1;
  return octave;
}

// Picks a nonzero integer octave offset (a "wander" that didn't move isn't a
// wander), weighted toward whichever direction has more room, and never
// exceeding the room actually available in that direction. At range=1 with
// equal room both ways this always has magnitude 1, matching the original
// fixed-magnitude behavior.
function pickWanderOffset(rng, range, maxDown, maxUp) {
  const down = Math.max(0, Math.min(range, maxDown));
  const up = Math.max(0, Math.min(range, maxUp));
  if (down === 0 && up === 0) return 0;
  const goUp = up > 0 && (down === 0 || rng() < up / (up + down));
  const available = goUp ? up : down;
  const magnitude = 1 + Math.floor(rng() * available);
  return goUp ? magnitude : -magnitude;
}

// Picks a fresh scale-respecting pitch for a scatter fragment: a new
// weighted role, occasionally wandering away from the voice's home octave
// instead of always echoing the same note. `depth` is the global Effect
// Depth knob (1 = authored default): higher depth widens both how often it
// wanders and how far, so pushing the knob gives more tonal variety, not
// just a louder/wetter effect. Still gated by the mood's octaveSpread --
// melancholy/mysterious (narrow spread) stay closer to home even at high
// depth, matching their more contained character.
export function scatterMidi(field, rng, assignment, depth = 1) {
  const role = field.weightedRole(rng);
  const spread = field.octaveSpread();
  const wanderChance = spread > 0 ? clamp(WANDER_CHANCE * depth, 0, 0.95) : 0;
  const desiredRange = spread > 0 ? Math.max(0, Math.round(depth)) : 0;
  let wander = 0;
  if (desiredRange > 0 && rng() < wanderChance) {
    const ceilingOctave = ceilingOctaveFor(field, role);
    const maxUp = Math.max(0, ceilingOctave - assignment.octave);
    const maxDown = assignment.octave;
    wander = pickWanderOffset(rng, desiredRange, maxDown, maxUp);
  }
  const octave = assignment.octave + wander;
  const midi = field.midiForRole(role, octave) + assignment.detuneCents / 100.0;
  return Math.min(midi, MAX_VOICE_MIDI);
}

export function ticksForSeconds(seconds, dtSeconds) {
  return Math.max(1, Math.round(seconds / dtSeconds));
}
