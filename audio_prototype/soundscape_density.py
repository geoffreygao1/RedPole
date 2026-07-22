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
