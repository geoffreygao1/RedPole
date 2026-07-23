// Port of soundscape_harmony.py's HarmonicField (spec 6/17).
export const PENTATONIC = [0, 2, 5, 7, 10];
export const ROLE_SEMITONES = { root: 0, fifth: 7, fourth: 5, ninth: 2, seventh: 10, tension: 1 };
export const ROLE_WEIGHTS = { root: 0.32, fifth: 0.24, fourth: 0.16, ninth: 0.14, seventh: 0.1, tension: 0.04 };

export function midiToHz(midi) {
  return 440.0 * Math.pow(2.0, (midi - 69.0) / 12.0);
}

export class HarmonicField {
  constructor(rootMidi = 48, tensionEnabled = true) {
    this.rootMidi = rootMidi;
    this.tensionEnabled = tensionEnabled;
  }
  roles() {
    const all = Object.keys(ROLE_WEIGHTS);
    return this.tensionEnabled ? all : all.filter((r) => r !== "tension");
  }
  weightedRole(rng) {
    const roles = this.roles();
    const weights = roles.map((r) => ROLE_WEIGHTS[r]);
    const total = weights.reduce((a, b) => a + b, 0);
    let x = rng() * total;
    for (let i = 0; i < roles.length; i++) {
      x -= weights[i];
      if (x <= 0) return roles[i];
    }
    return roles[roles.length - 1];
  }
  semitoneForRole(role) {
    return ROLE_SEMITONES[role];
  }
  midiForRole(role, octaveOffset = 0) {
    return this.rootMidi + this.semitoneForRole(role) + 12 * octaveOffset;
  }
}
