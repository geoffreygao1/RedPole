"""Slow evolving-mix conductor for the soundscape (feedback: ebb and flow
instead of a constant wall of sound). Produces a per-voice gain that fades
voices in and out over tens of seconds and rotates which voices sit in the
foreground, reusing the spec-9 role budgets. Deterministic given a seed."""

import numpy as np

from soundscape_density import ROLE_GAIN, assign_voice_roles


class VoiceConductor:
    def __init__(self, samplerate, seed=None, min_period=20.0, max_period=50.0,
                 swell_min=0.35, swell_depth=0.65, smooth_tau=0.6):
        self.samplerate = float(samplerate)
        self.seed = 0 if seed is None else int(seed)
        self.min_period = float(min_period)
        self.max_period = float(max_period)
        self.swell_min = float(swell_min)
        self.swell_depth = float(swell_depth)
        self.smooth_tau = float(smooth_tau)
        self._t = 0.0
        self._params = {}   # vid -> (rate_hz, phase)
        self._gain = {}     # vid -> smoothed gain

    def _params_for(self, vid):
        params = self._params.get(vid)
        if params is None:
            rng = np.random.default_rng(self.seed * 1_000_003 + int(vid))
            period = rng.uniform(self.min_period, self.max_period)
            phase = rng.uniform(0.0, 1.0)
            params = (1.0 / period, phase)
            self._params[vid] = params
        return params

    def _activity(self, vid):
        rate, phase = self._params_for(vid)
        return 0.5 + 0.5 * np.sin(2.0 * np.pi * (self._t * rate + phase))

    def update(self, active_ids, frames):
        active = list(active_ids)
        # GC state for voices that disappeared.
        keep = set(active)
        self._params = {v: p for v, p in self._params.items() if v in keep}
        self._gain = {v: g for v, g in self._gain.items() if v in keep}
        if not active:
            self._t += frames / self.samplerate
            return {}

        activity = {vid: float(self._activity(vid)) for vid in active}
        ranked = sorted(active, key=lambda v: activity[v], reverse=True)
        roles = assign_voice_roles(ranked)

        dt = frames / self.samplerate
        alpha = 1.0 - np.exp(-dt / self.smooth_tau)
        out = {}
        for vid in active:
            target = ROLE_GAIN[roles[vid]] * (self.swell_min + self.swell_depth * activity[vid])
            current = self._gain.get(vid, target)
            current += alpha * (target - current)
            self._gain[vid] = current
            out[vid] = current
        self._t += dt
        return out
