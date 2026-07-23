// Port of soundscape_harmony.py's register logic + PitchAllocator.
import { midiToHz } from "./harmony.js";
import { uniform } from "./rng.js";

const REGISTER_BANDS = [
  ["sub", 40.0, 120.0], ["low", 120.0, 500.0], ["mid", 500.0, 2000.0],
  ["high", 2000.0, 6000.0], ["air", 6000.0, 14000.0],
];
export const REGISTER_LIMITS = { sub: 2, low: 3, mid: 5, high: 7, air: 8 };
export const DETUNE_CENTS_RANGE = { foreground: 4.0, background: 8.0, granular: 15.0, texture: 30.0 };

export function bandForHz(hz) {
  for (const [name, lo, hi] of REGISTER_BANDS) if (hz >= lo && hz < hi) return name;
  return hz >= REGISTER_BANDS[REGISTER_BANDS.length - 1][2] ? "air" : "sub";
}

export class PitchAllocator {
  constructor(field) {
    this.field = field;
    this._counts = Object.fromEntries(REGISTER_BANDS.map(([n]) => [n, 0]));
    this._byVoice = new Map();
  }
  _isCrowded(band) { return this._counts[band] >= REGISTER_LIMITS[band]; }
  _register(vid, band) { this.release(vid); this._counts[band] += 1; this._byVoice.set(vid, band); }
  release(vid) {
    const band = this._byVoice.get(vid);
    if (band !== undefined) { this._counts[band] -= 1; this._byVoice.delete(vid); }
  }
  allocate(vid, rng, density, detuneClass = "foreground") {
    const role = this.field.weightedRole(rng);
    let octave = 0, midi, band;
    let placed = false;
    for (let i = 0; i < 4; i++) {
      midi = this.field.midiForRole(role, octave);
      band = bandForHz(midiToHz(midi));
      if (!this._isCrowded(band)) { placed = true; break; }
      octave += 1;
    }
    if (!placed) {
      octave = 1 + Math.floor(rng() * 2); // rng.integers(1,3)
      midi = this.field.midiForRole(role, octave);
      band = bandForHz(midiToHz(midi));
    }
    if (density > 0.6 && (band === "sub" || band === "low")) {
      octave += 1;
      midi = this.field.midiForRole(role, octave);
      band = bandForHz(midiToHz(midi));
    }
    const limit = DETUNE_CENTS_RANGE[detuneClass] ?? DETUNE_CENTS_RANGE.foreground;
    const detuneCents = uniform(rng, -limit, limit);
    this._register(vid, band);
    return { role, octave, detuneCents, band, midi: midi + detuneCents / 100.0 };
  }
}
