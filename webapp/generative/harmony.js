// Port of soundscape_harmony.py's HarmonicField, extended with clickbath-like
// mood palettes for the browser sampler.
export const PENTATONIC = [0, 2, 5, 7, 10];
export const HARMONIC_PALETTES = {
  optimistic: {
    // Clickbath's actual optimistic mode is the full major scale, picked with
    // near-equal probability (see clickbath src/index.js noteArray()) -- not a
    // narrow root-heavy subset. A narrow subset read as static/droney
    // regardless of which notes were in it, because with up to 25 sustained
    // voices sharing only 4 pitch classes you get heavy unison stacking.
    semitones: { root: 0, second: 2, third: 4, fourth: 5, fifth: 7, sixth: 9, seventh: 11 },
    weights: { root: 0.15, second: 0.14, third: 0.14, fourth: 0.13, fifth: 0.15, sixth: 0.14, seventh: 0.15 },
  },
  happy: {
    // Same full-scale breadth as optimistic, with thirds/sixths/sevenths
    // weighted up slightly for a brighter major-7 lean.
    semitones: { root: 0, second: 2, third: 4, fourth: 5, fifth: 7, sixth: 9, seventh: 11 },
    weights: { root: 0.13, second: 0.12, third: 0.16, fourth: 0.1, fifth: 0.14, sixth: 0.16, seventh: 0.19 },
  },
  mysterious: {
    // Clickbath mystery uses a minor/flat-six color; Root supplies the key.
    // Adds a rare flatSecond (a half-step above root) for occasional
    // unsettling color on top of that base.
    semitones: { root: 0, flatSecond: 1, minorThird: 3, fifth: 7, flatSixth: 8 },
    weights: { root: 0.28, flatSecond: 0.08, minorThird: 0.22, fifth: 0.22, flatSixth: 0.2 },
  },
  melancholy: {
    // Clickbath melancholy explicitly uses C, D, Eb, G.
    semitones: { root: 0, second: 2, minorThird: 3, fifth: 7 },
    weights: { root: 0.34, second: 0.16, minorThird: 0.26, fifth: 0.24 },
  },
};

// Ceiling for any voice's pitch, primary or macro-triggered (shadow/scatter
// companions). Matches the highest multisampled note most instruments in
// instrument-maps.js provide (piano/tapebell/casio/strings/flute/clarinet all
// go up to 84), so Tone.Sampler never has to pitch-shift more than a few
// semitones from a real sample -- avoids the thin/artificial "too high
// pitched" sound of shifting several octaves from the nearest sample.
export const MAX_VOICE_MIDI = 84;

// Matches the lowest multisampled note any instrument provides (tapeguitar's
// lowest is 36); used as a floor so a downward octave transpose can't push a
// voice further below any real sample than this.
export const MIN_VOICE_MIDI = 36;

export const MOOD_OCTAVE_SPREAD = {
  optimistic: 2,
  happy: 2,
  mysterious: 1,
  melancholy: 0,
};

export function octaveSpreadForMood(mood) {
  return MOOD_OCTAVE_SPREAD[mood] ?? MOOD_OCTAVE_SPREAD.melancholy;
}

const FOUNDATION_ROLES = new Set(["root", "fifth"]);
export function isFoundationRole(role) {
  return FOUNDATION_ROLES.has(role);
}

const SCALE_INTERVALS = {
  major: { root: 0, third: 4, fifth: 7, sixth: 9 },
  minor: { root: 0, minorThird: 3, fifth: 7, flatSixth: 8 },
};
const SCALE_WEIGHTS = {
  major: { root: 0.34, third: 0.24, fifth: 0.26, sixth: 0.16 },
  minor: { root: 0.34, minorThird: 0.26, fifth: 0.24, flatSixth: 0.16 },
};
export const ROLE_SEMITONES = HARMONIC_PALETTES.optimistic.semitones;
export const ROLE_WEIGHTS = HARMONIC_PALETTES.optimistic.weights;

export function paletteForId(id) {
  if (HARMONIC_PALETTES[id]) return HARMONIC_PALETTES[id];
  if (id === "scale:major") {
    return { semitones: SCALE_INTERVALS.major, weights: SCALE_WEIGHTS.major };
  }
  if (id === "scale:minor") {
    return { semitones: SCALE_INTERVALS.minor, weights: SCALE_WEIGHTS.minor };
  }
  return HARMONIC_PALETTES.optimistic;
}

export function midiToHz(midi) {
  return 440.0 * Math.pow(2.0, (midi - 69.0) / 12.0);
}

export class HarmonicField {
  constructor(rootMidi = 48, tensionEnabled = true, mood = "optimistic") {
    this.rootMidi = rootMidi;
    this.tensionEnabled = tensionEnabled;
    this.setMood(mood);
  }
  setMood(mood) {
    const palette = paletteForId(mood);
    this.mood = palette === HARMONIC_PALETTES.optimistic && mood !== "optimistic" ? "optimistic" : mood;
    this.palette = palette;
  }
  octaveSpread() {
    return octaveSpreadForMood(this.mood);
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
