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

from soundscape_density import (
    ROLE_BACKGROUND,
    ROLE_DORMANT,
    ROLE_FOREGROUND,
    ROLE_MIDGROUND,
    assign_voice_roles,
    event_probability,
)


def test_assign_voice_roles_small_group_is_all_foreground():
    roles = assign_voice_roles([1, 2, 3])
    assert all(r == ROLE_FOREGROUND for r in roles.values())


def test_assign_voice_roles_respects_budgets_for_large_group():
    order = list(range(1, 26))  # 25 patches
    roles = assign_voice_roles(order)
    counts = {}
    for r in roles.values():
        counts[r] = counts.get(r, 0) + 1
    assert 3 <= counts.get(ROLE_FOREGROUND, 0) <= 5
    assert 5 <= counts.get(ROLE_MIDGROUND, 0) <= 8
    assert 4 <= counts.get(ROLE_BACKGROUND, 0) <= 8
    assert counts.get(ROLE_DORMANT, 0) > 0
    assert sum(counts.values()) == 25


def test_event_probability_decreases_with_density():
    assert event_probability(3) > event_probability(10) > event_probability(18) > event_probability(24)
    assert 0.0 <= event_probability(24) <= 1.0


def test_event_probability_within_bucket_bounds():
    assert 0.70 <= event_probability(1) <= 1.00
    assert 0.05 <= event_probability(25) <= 0.30
