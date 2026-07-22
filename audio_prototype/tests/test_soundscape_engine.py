import numpy as np

from soundscape_engine import SoundscapeEngine


def test_no_patches_is_silence():
    engine = SoundscapeEngine(samplerate=44100, seed=1)
    block = engine.generate_block(1024)
    assert block.shape == (1024,)
    assert block.dtype == np.float32
    np.testing.assert_allclose(block, np.zeros(1024))


def test_one_patch_is_audible_bounded_and_nan_free():
    engine = SoundscapeEngine(samplerate=44100, seed=1)
    engine.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="additive_2")
    total = np.concatenate([engine.generate_block(1024) for _ in range(80)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-3
    assert float(np.sqrt(np.mean(total[-8192:] ** 2))) > 0.01


def test_disconnect_removes_the_voice():
    engine = SoundscapeEngine(samplerate=44100, seed=1)
    pid = engine.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="noise_2")
    engine.generate_block(512)
    engine.disconnect_patch(pid)
    silent = engine.generate_block(512)
    np.testing.assert_allclose(silent, np.zeros(512))


def test_eight_patches_stay_bounded_and_nan_free():
    engine = SoundscapeEngine(samplerate=44100, seed=2)
    presets = ["additive_1", "granular_2", "resonant_3", "noise_4", "texture_5",
               "additive_5", "resonant_1", "granular_4"]
    for i, preset in enumerate(presets):
        engine.connect_patch(hue=0.01 * i, sat=0.66, val=0.92, bpm=70.0 + 5 * i,
                              source_preset=preset, transform_preset="spatial_1")
    for _ in range(80):
        block = engine.generate_block(1024)
        assert not np.any(np.isnan(block))
        assert np.max(np.abs(block)) <= 1.0 + 1e-3


def test_transform_preset_audibly_changes_the_voice():
    dry = SoundscapeEngine(samplerate=44100, seed=1)
    dry.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="additive_2")
    wet = SoundscapeEngine(samplerate=44100, seed=1)
    wet.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="additive_2",
                       transform_preset="grainfx_5")
    dry_out = np.concatenate([dry.generate_block(1024) for _ in range(20)])
    wet_out = np.concatenate([wet.generate_block(1024) for _ in range(20)])
    assert not np.allclose(dry_out, wet_out)
