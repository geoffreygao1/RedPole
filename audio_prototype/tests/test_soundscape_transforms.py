import numpy as np

from soundscape_transforms import DELAY_PRESETS, DelayTransform, SPECTRAL_PRESETS, SpectralTransform


def _click_train(frames, period, samplerate=44100):
    x = np.zeros(frames)
    x[::period] = 1.0
    return x


def test_delay_has_five_presets_with_required_keys():
    assert len(DELAY_PRESETS) == 5
    for p in DELAY_PRESETS:
        assert {"id", "subdivision", "feedback", "reverse"} <= set(p)


def test_delay_produces_a_later_echo_of_a_click():
    fx = DelayTransform(44100)
    x = np.zeros(4096)
    x[10] = 1.0
    out = fx.render(1, x, bpm=120.0, preset=dict(DELAY_PRESETS[1], reverse=False))
    assert not np.any(np.isnan(out))
    # some later sample should be non-zero due to the fed-back click
    assert np.max(np.abs(out[100:])) > 0.0


def test_delay_feedback_keeps_output_bounded_over_many_blocks():
    fx = DelayTransform(44100)
    rng = np.random.default_rng(1)
    total = []
    for _ in range(60):
        x = rng.uniform(-0.2, 0.2, size=1024)
        total.append(fx.render(1, x, bpm=100.0, preset=DELAY_PRESETS[3]))
    total = np.concatenate(total)
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) < 5.0


def test_delay_voice_dropped_on_sync():
    fx = DelayTransform(44100)
    fx.render(1, np.zeros(256), 100.0, DELAY_PRESETS[0])
    assert 1 in fx._voices
    fx.sync([])
    assert 1 not in fx._voices


def test_spectral_has_five_presets_with_required_keys():
    assert len(SPECTRAL_PRESETS) == 5
    for p in SPECTRAL_PRESETS:
        assert {"id", "suspension", "smear"} <= set(p)


def test_spectral_transform_returns_same_length_and_is_bounded():
    fx = SpectralTransform(44100, seed=2)
    rng = np.random.default_rng(0)
    for preset in SPECTRAL_PRESETS:
        x = rng.uniform(-0.3, 0.3, size=512)
        out = fx.render(1, x, preset)
        assert out.shape == (512,)
        assert not np.any(np.isnan(out))
        assert np.max(np.abs(out)) < 5.0


def test_spectral_transform_voice_dropped_on_sync():
    fx = SpectralTransform(44100, seed=2)
    fx.render(1, np.zeros(256), SPECTRAL_PRESETS[0])
    assert 1 in fx._voices
    fx.sync([])
    assert 1 not in fx._voices

from soundscape_transforms import GRAINFX_PRESETS, PITCH_PRESETS, GranularTransform, PitchResonanceTransform


def test_pitch_has_five_presets_with_required_keys():
    assert len(PITCH_PRESETS) == 5
    for p in PITCH_PRESETS:
        assert {"id", "semitones", "mix"} <= set(p)


def test_pitch_transform_is_bounded_and_nan_free():
    fx = PitchResonanceTransform(44100, seed=3)
    rng = np.random.default_rng(0)
    x = rng.uniform(-0.4, 0.4, size=1024)
    for preset in PITCH_PRESETS:
        out = fx.render(1, x, preset)
        assert out.shape == (1024,)
        assert not np.any(np.isnan(out))
        assert np.max(np.abs(out)) < 5.0


def test_sub_octave_preset_differs_from_dry_signal():
    fx = PitchResonanceTransform(44100, seed=3)
    x = np.sin(2 * np.pi * 220 * np.arange(1024) / 44100)
    out = fx.render(1, x, PITCH_PRESETS[0])
    assert not np.allclose(out, x)


def test_pitch_voice_dropped_on_sync():
    fx = PitchResonanceTransform(44100, seed=3)
    fx.render(1, np.zeros(256), PITCH_PRESETS[0])
    assert 1 in fx._voices
    fx.sync([])
    assert 1 not in fx._voices


def test_grainfx_has_five_presets_with_required_keys():
    assert len(GRAINFX_PRESETS) == 5
    for p in GRAINFX_PRESETS:
        assert "id" in p and "kind" in p


def test_grainfx_presets_are_bounded_and_differ_from_dry():
    fx = GranularTransform(44100, seed=4)
    x = np.sin(2 * np.pi * 220 * np.arange(2048) / 44100) * 0.5
    for preset in GRAINFX_PRESETS:
        out = fx.render(1, x.copy(), preset)
        assert out.shape == (2048,)
        assert not np.any(np.isnan(out))
        assert np.max(np.abs(out)) < 5.0
        if preset["kind"] != "granulate":
            assert not np.allclose(out, x)


def test_grainfx_voice_dropped_on_sync():
    fx = GranularTransform(44100, seed=4)
    fx.render(1, np.zeros(256), GRAINFX_PRESETS[1])
    assert 1 in fx._voices
    fx.sync([])
    assert 1 not in fx._voices
