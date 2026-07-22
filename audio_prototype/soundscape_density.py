"""Density-based gain scaling and voice-priority budgeting (spec section 9)."""

import numpy as np

GAIN_SMOOTHING = 0.05   # one-pole coefficient per block, spec 9.3 "apply smoothing"


class DensityGainSmoother:
    def __init__(self, base_gain=1.0, smoothing=GAIN_SMOOTHING):
        self.base_gain = base_gain
        self.smoothing = smoothing
        self._current = base_gain

    def update(self, active_count):
        target = self.base_gain / np.sqrt(max(1, active_count))
        self._current += self.smoothing * (target - self._current)
        return float(self._current)

FOREGROUND_BUDGET = (3, 5)     # spec 9.2
MIDGROUND_BUDGET = (5, 8)
BACKGROUND_BUDGET = (4, 8)

ROLE_FOREGROUND = "foreground"
ROLE_MIDGROUND = "midground"
ROLE_BACKGROUND = "background"
ROLE_DORMANT = "dormant"

ROLE_GAIN = {ROLE_FOREGROUND: 1.0, ROLE_MIDGROUND: 0.55, ROLE_BACKGROUND: 0.28, ROLE_DORMANT: 0.0}


def assign_voice_roles(order_ids):
    """order_ids: ids in priority order (e.g. most-recently-connected last).
    Returns {id: role} respecting spec 9.2 budgets."""
    roles = {}
    n = len(order_ids)
    fg_n = min(n, FOREGROUND_BUDGET[1])
    mg_n = min(max(0, n - fg_n), MIDGROUND_BUDGET[1])
    bg_n = min(max(0, n - fg_n - mg_n), BACKGROUND_BUDGET[1])
    for i, vid in enumerate(order_ids):
        if i < fg_n:
            roles[vid] = ROLE_FOREGROUND
        elif i < fg_n + mg_n:
            roles[vid] = ROLE_MIDGROUND
        elif i < fg_n + mg_n + bg_n:
            roles[vid] = ROLE_BACKGROUND
        else:
            roles[vid] = ROLE_DORMANT
    return roles


_EVENT_PROBABILITY_BUCKETS = (   # (lo, hi, p_at_lo, p_at_hi), spec 9.5
    (1, 5, 1.00, 0.70),
    (6, 12, 0.70, 0.35),
    (13, 20, 0.45, 0.15),
    (21, 25, 0.30, 0.05),
)


def event_probability(active_count):
    n = max(1, int(active_count))
    for lo, hi, p_lo, p_hi in _EVENT_PROBABILITY_BUCKETS:
        if lo <= n <= hi:
            frac = (n - lo) / max(1, hi - lo)
            p = p_lo + (p_hi - p_lo) * frac
            return float(np.clip(p, min(p_lo, p_hi), max(p_lo, p_hi)))
    return 0.05 if n > 25 else 1.0
