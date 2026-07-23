// Port of soundscape_harmony.py's HarmonicField, extended with clickbath-like
// mood palettes for the browser sampler.
export const PENTATONIC = [0, 2, 5, 7, 10];
export const HARMONIC_PALETTES = {
  open: {
    semitones: { root: 0, fifth: 7, fourth: 5, ninth: 2, seventh: 10, tension: 1 },
    weights: { root: 0.34, fifth: 0.26, fourth: 0.17, ninth: 0.13, seventh: 0.08, tension: 0.02 },
  },
  warm: {
    semitones: { root: 0, fifth: 7, third: 4, ninth: 2, sixth: 9, seventh: 11, tension: 6 },
    weights: { root: 0.3, fifth: 0.22, third: 0.19, ninth: 0.12, sixth: 0.1, seventh: 0.05, tension: 0.02 },
  },
  dusk: {
    semitones: { root: 0, fifth: 7, third: 3, fourth: 5, seventh: 10, ninth: 2, tension: 8 },
    weights: { root: 0.31, fifth: 0.22, third: 0.18, fourth: 0.12, seventh: 0.1, ninth: 0.05, tension: 0.02 },
  },
  glass: {
    semitones: { root: 0, fifth: 7, lydian: 6, ninth: 2, third: 4, sixth: 9, tension: 1 },
    weights: { root: 0.28, fifth: 0.2, lydian: 0.17, ninth: 0.16, third: 0.11, sixth: 0.06, tension: 0.02 },
  },
  tension: {
    semitones: { root: 0, fifth: 7, flatsecond: 1, seventh: 10, ninth: 2, fourth: 5, tension: 6 },
    weights: { root: 0.26, fifth: 0.18, flatsecond: 0.15, seventh: 0.14, ninth: 0.12, fourth: 0.1, tension: 0.05 },
  },
};
export const ROLE_SEMITONES = HARMONIC_PALETTES.open.semitones;
export const ROLE_WEIGHTS = HARMONIC_PALETTES.open.weights;

export function midiToHz(midi) {
  return 440.0 * Math.pow(2.0, (midi - 69.0) / 12.0);
}

export class HarmonicField {
  constructor(rootMidi = 48, tensionEnabled = true, mood = "open") {
    this.rootMidi = rootMidi;
    this.tensionEnabled = tensionEnabled;
    this.setMood(mood);
  }
  setMood(mood) {
    this.mood = HARMONIC_PALETTES[mood] ? mood : "open";
    this.palette = HARMONIC_PALETTES[this.mood];
  }
  roles() {
    const all = Object.keys(this.palette.weights);
    return this.tensionEnabled ? all : all.filter((r) => r !== "tension" && r !== "flatsecond");
  }
  weightedRole(rng) {
    const roles = this.roles();
    const weights = roles.map((r) => this.palette.weights[r]);
    const total = weights.reduce((a, b) => a + b, 0);
    let x = rng() * total;
    for (let i = 0; i < roles.length; i++) {
      x -= weights[i];
      if (x <= 0) return roles[i];
    }
    return roles[roles.length - 1];
  }
  semitoneForRole(role) {
    return this.palette.semitones[role] ?? this.palette.semitones.root;
  }
  midiForRole(role, octaveOffset = 0) {
    return this.rootMidi + this.semitoneForRole(role) + 12 * octaveOffset;
  }
}
