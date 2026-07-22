import numpy as np

from soundscape_engine import SoundscapeEngine
from soundscape_prototype import build_patches


def test_build_patches_connects_the_requested_count():
    engine = SoundscapeEngine(samplerate=44100, seed=1)
    rng = np.random.default_rng(1)
    build_patches(engine, 8, rng)
    assert len(engine._patches) == 8


def test_eight_simulated_patches_run_headless_without_error():
    engine = SoundscapeEngine(samplerate=44100, seed=1)
    rng = np.random.default_rng(1)
    build_patches(engine, 8, rng)
    total = np.concatenate([engine.generate_block(1024) for _ in range(80)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-3
    assert float(np.sqrt(np.mean(total[-8192:] ** 2))) > 0.005


def test_build_patches_uses_gamut_bounds():
    import modulation as mod

    engine = SoundscapeEngine(samplerate=44100, seed=1)
    rng = np.random.default_rng(1)
    build_patches(engine, 25, rng)
    for patch in engine._patches.values():
        assert mod.FINGER_HUE_MIN <= patch.hue <= mod.FINGER_HUE_MAX
        assert mod.FINGER_SAT_MIN <= patch.sat <= mod.FINGER_SAT_MAX
        assert mod.FINGER_VAL_MIN <= patch.val <= mod.FINGER_VAL_MAX
