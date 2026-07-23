// Port of soundscape_conductor.py + soundscape_density.py role budgets.
import { mulberry32, uniform } from "./rng.js";

export const ROLE_GAIN = { foreground: 1.0, midground: 0.55, background: 0.28, dormant: 0.0 };
const FG = 5, MG = 8, BG = 8; // spec-9 upper budgets

export function assignVoiceRoles(orderIds) {
  const roles = new Map();
  const n = orderIds.length;
  const fgN = Math.min(n, FG);
  const mgN = Math.min(Math.max(0, n - fgN), MG);
  const bgN = Math.min(Math.max(0, n - fgN - mgN), BG);
  orderIds.forEach((vid, i) => {
    if (i < fgN) roles.set(vid, "foreground");
    else if (i < fgN + mgN) roles.set(vid, "midground");
    else if (i < fgN + mgN + bgN) roles.set(vid, "background");
    else roles.set(vid, "dormant");
  });
  return roles;
}

export class VoiceConductor {
  constructor({ seed = 0, minPeriod = 20, maxPeriod = 50, swellMin = 0.35, swellDepth = 0.65, smoothTau = 0.6 } = {}) {
    Object.assign(this, { seed, minPeriod, maxPeriod, swellMin, swellDepth, smoothTau });
    this._t = 0;
    this._params = new Map(); // vid -> {rate, phase}
    this._gain = new Map();   // vid -> smoothed gain
  }
  _paramsFor(vid) {
    let p = this._params.get(vid);
    if (!p) {
      const rng = mulberry32(this.seed * 1000003 + vid);
      const period = uniform(rng, this.minPeriod, this.maxPeriod);
      p = { rate: 1 / period, phase: uniform(rng, 0, 1) };
      this._params.set(vid, p);
    }
    return p;
  }
  _activity(vid) {
    const { rate, phase } = this._paramsFor(vid);
    return 0.5 + 0.5 * Math.sin(2 * Math.PI * (this._t * rate + phase));
  }
  update(activeIds, dt) {
    const keep = new Set(activeIds);
    for (const k of [...this._params.keys()]) if (!keep.has(k)) this._params.delete(k);
    for (const k of [...this._gain.keys()]) if (!keep.has(k)) this._gain.delete(k);
    const out = new Map();
    if (activeIds.length === 0) { this._t += dt; return out; }
    const activity = new Map(activeIds.map((v) => [v, this._activity(v)]));
    const ranked = [...activeIds].sort((a, b) => activity.get(b) - activity.get(a));
    const roles = assignVoiceRoles(ranked);
    const alpha = 1 - Math.exp(-dt / this.smoothTau);
    for (const vid of activeIds) {
      const target = ROLE_GAIN[roles.get(vid)] * (this.swellMin + this.swellDepth * activity.get(vid));
      let current = this._gain.has(vid) ? this._gain.get(vid) : target;
      current += alpha * (target - current);
      this._gain.set(vid, current);
      out.set(vid, current);
    }
    this._t += dt;
    return out;
  }
}
