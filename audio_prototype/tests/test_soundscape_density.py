import numpy as np

from soundscape_density import DensityGainSmoother


def test_gain_decreases_as_count_grows_once_settled():
    low = DensityGainSmoother()
    high = DensityGainSmoother()
    for _ in range(200):
        g_low = low.update(2)
        g_high = high.update(20)
    assert g_high < g_low


def test_gain_approaches_formula_after_settling():
    smoother = DensityGainSmoother(base_gain=1.0)
    for _ in range(500):
        g = smoother.update(9)
    assert abs(g - 1.0 / np.sqrt(9)) < 0.01


def test_gain_changes_smoothly_not_abruptly():
    smoother = DensityGainSmoother()
    smoother.update(1)
    g_before = smoother.update(1)
    g_after_jump = smoother.update(25)
    # a single block should not jump all the way to the new target
    target = 1.0 / np.sqrt(25)
    assert abs(g_after_jump - target) > abs(g_before - target) * 0.01
    assert g_after_jump < g_before
