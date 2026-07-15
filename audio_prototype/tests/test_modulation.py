import numpy as np
import pytest

import modulation as mod


def test_clamp():
    assert mod.clamp(5, 0, 10) == 5
    assert mod.clamp(-1, 0, 10) == 0
    assert mod.clamp(11, 0, 10) == 10


def test_bpm_to_hz():
    assert mod.bpm_to_hz(60) == pytest.approx(1.0)
    assert mod.bpm_to_hz(120) == pytest.approx(2.0)


def test_hue_to_bipolar_center_and_edges():
    assert mod.hue_to_bipolar(mod.FINGER_HUE_MIN) == pytest.approx(-1.0)
    assert mod.hue_to_bipolar(mod.FINGER_HUE_MAX) == pytest.approx(1.0)
    assert mod.hue_to_bipolar((mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2) == pytest.approx(0.0)


def test_hue_to_bipolar_clamps_outside_gamut():
    assert mod.hue_to_bipolar(0.4) == pytest.approx(1.0)
    assert mod.hue_to_bipolar(-0.1) == pytest.approx(-1.0)


def test_finger_color_window_normalizes_new_picker_range():
    assert mod.hue_to_unit(mod.FINGER_HUE_MIN) == pytest.approx(0.0)
    assert mod.hue_to_unit(mod.FINGER_HUE_MAX) == pytest.approx(1.0)
    assert mod.sat_to_unit(mod.FINGER_SAT_MIN) == pytest.approx(0.0)
    assert mod.sat_to_unit(mod.FINGER_SAT_MAX) == pytest.approx(1.0)
    assert mod.val_to_unit(mod.FINGER_VAL_MIN) == pytest.approx(0.0)
    assert mod.val_to_unit(mod.FINGER_VAL_MAX) == pytest.approx(1.0)


def test_hue_to_warble_depth_bounds():
    assert mod.hue_to_warble_depth((mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2) == pytest.approx(mod.PER_LAYER_MIN_WARBLE)
    assert mod.hue_to_warble_depth(mod.FINGER_HUE_MIN) == pytest.approx(mod.PER_LAYER_MAX_WARBLE)
    assert mod.hue_to_warble_depth(mod.FINGER_HUE_MAX) == pytest.approx(mod.PER_LAYER_MAX_WARBLE)
    mid = mod.hue_to_warble_depth(mod.FINGER_HUE_MIN + (mod.FINGER_HUE_MAX - mod.FINGER_HUE_MIN) * 0.25)
    assert mod.PER_LAYER_MIN_WARBLE < mid < mod.PER_LAYER_MAX_WARBLE


def test_sat_val_to_bloom_depth_bounds():
    assert mod.sat_val_to_bloom_depth(0.0, 0.0) == pytest.approx(mod.PER_LAYER_MIN_BLOOM)
    assert mod.sat_val_to_bloom_depth(1.0, 1.0) == pytest.approx(mod.PER_LAYER_MAX_BLOOM)


def test_combine_layers_empty():
    combined = mod.combine_layers([])
    assert combined == {"warble_depth": 0.0, "bloom_depth": 0.0, "rate_hz": 0.0}


def test_combine_layers_sums_depth_and_averages_rate():
    layers = [
        {"hue": mod.FINGER_HUE_MAX, "sat": 1.0, "val": 1.0, "bpm": 60.0},
        {"hue": mod.FINGER_HUE_MAX, "sat": 1.0, "val": 1.0, "bpm": 120.0},
    ]
    combined = mod.combine_layers(layers)
    assert combined["warble_depth"] == pytest.approx(
        min(2 * mod.PER_LAYER_MAX_WARBLE, mod.MAX_WARBLE_DEPTH)
    )
    assert combined["bloom_depth"] == pytest.approx(
        min(2 * mod.PER_LAYER_MAX_BLOOM, mod.MAX_BLOOM_DEPTH)
    )
    assert combined["rate_hz"] == pytest.approx(1.5)  # average of 1.0 and 2.0 Hz


def test_combine_layers_clamps_depth_with_many_layers():
    layers = [{"hue": mod.FINGER_HUE_MAX, "sat": 1.0, "val": 1.0, "bpm": 60.0} for _ in range(20)]
    combined = mod.combine_layers(layers)
    assert combined["warble_depth"] == pytest.approx(mod.MAX_WARBLE_DEPTH)
    assert combined["bloom_depth"] == pytest.approx(mod.MAX_BLOOM_DEPTH)


def test_limiter_passes_quiet_signal_unchanged():
    lim = mod.RmsLimiter(target_rms=0.35)
    x = 0.1 * np.sin(np.linspace(0, 40 * np.pi, 4096))
    out = lim.process(x)
    np.testing.assert_allclose(out, x, atol=1e-6)
    assert lim.gain == pytest.approx(1.0, abs=0.01)


def test_limiter_tames_sustained_loud_signal():
    lim = mod.RmsLimiter(target_rms=0.35)
    x = 0.9 * np.sin(np.linspace(0, 40 * np.pi, 1024))
    out = None
    for _ in range(30):
        out = lim.process(x)
    rms = float(np.sqrt(np.mean(out**2)))
    assert rms <= 0.35 * 1.15  # settles at (or just above) the target
    assert lim.gain < 1.0


def test_limiter_recovers_after_loud_passage():
    lim = mod.RmsLimiter(target_rms=0.35)
    loud = 0.9 * np.sin(np.linspace(0, 40 * np.pi, 1024))
    for _ in range(30):
        lim.process(loud)
    assert lim.gain < 1.0
    quiet = 0.05 * np.sin(np.linspace(0, 40 * np.pi, 1024))
    for _ in range(400):
        lim.process(quiet)
    assert lim.gain == pytest.approx(1.0, abs=0.05)


def test_limiter_handles_silence():
    lim = mod.RmsLimiter(target_rms=0.35)
    out = lim.process(np.zeros(1024))
    np.testing.assert_allclose(out, np.zeros(1024))
    assert not np.any(np.isnan(out))


def test_soft_clip_leaves_small_values_untouched():
    x = np.array([-0.5, 0.0, 0.5, 0.89])
    np.testing.assert_allclose(mod.soft_clip(x, threshold=0.9), x)


def test_soft_clip_bounds_large_values():
    x = np.array([5.0, -5.0])
    y = mod.soft_clip(x, threshold=0.9)
    assert np.all(np.abs(y) < 1.0)
    assert np.all(np.abs(y) > 0.9)
