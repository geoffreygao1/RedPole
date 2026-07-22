import numpy as np

from soundscape_color import calibrate_color
from soundscape_harmony import HarmonicField, PitchAllocator
from soundscape_sources import ADDITIVE_PRESETS, AdditiveDroneSource


def _assignment(midi=62):
    field = HarmonicField(root_midi=midi)
    allocator = PitchAllocator(field)
    rng = np.random.default_rng(0)
    return allocator.allocate(1, rng, density=0.1)


def test_additive_has_five_presets_with_required_keys():
    assert len(ADDITIVE_PRESETS) == 5
    for p in ADDITIVE_PRESETS:
        assert {"id", "register_bias", "brightness_bias", "attack"} <= set(p)


def test_additive_produces_a_bounded_sustained_tone():
    src = AdditiveDroneSource(44100, seed=1)
    assignment = _assignment()
    timbre = calibrate_color(0.03, 0.68, 0.94)
    preset = ADDITIVE_PRESETS[0]
    blocks = [src.render(1, assignment, timbre, 1024, preset) for _ in range(80)]
    total = np.concatenate(blocks)
    assert total.dtype == np.float64
    assert np.max(np.abs(total)) <= 1.0 + 1e-6
    assert not np.any(np.isnan(total))
    tail_rms = float(np.sqrt(np.mean(total[-8192:] ** 2)))
    assert tail_rms > 0.02


def test_additive_attack_ramps_up_from_silence():
    src = AdditiveDroneSource(44100, seed=1)
    assignment = _assignment()
    timbre = calibrate_color(0.03, 0.68, 0.94)
    preset = dict(ADDITIVE_PRESETS[0], attack=1.0)  # 1s attack, short enough to observe
    first = src.render(1, assignment, timbre, 1024, preset)
    later = None
    for _ in range(60):
        later = src.render(1, assignment, timbre, 1024, preset)
    assert np.sqrt(np.mean(first ** 2)) < np.sqrt(np.mean(later ** 2))


def test_additive_voice_is_dropped_on_sync():
    src = AdditiveDroneSource(44100, seed=1)
    assignment = _assignment()
    timbre = calibrate_color(0.03, 0.68, 0.94)
    src.render(1, assignment, timbre, 256, ADDITIVE_PRESETS[0])
    assert 1 in src._voices
    src.sync([])
    assert 1 not in src._voices

from soundscape_sources import GRANULAR_PRESETS, GranularCloudSource


def test_granular_has_five_presets_with_required_keys():
    assert len(GRANULAR_PRESETS) == 5
    for p in GRANULAR_PRESETS:
        assert {"id", "grain_ms", "density_hz", "spread_ms"} <= set(p)


def test_granular_cloud_is_audible_and_bounded():
    src = GranularCloudSource(44100, seed=2)
    timbre = calibrate_color(0.03, 0.68, 0.94)
    blocks = [src.render(1, timbre, 90.0, 1024, GRANULAR_PRESETS[0]) for _ in range(60)]
    total = np.concatenate(blocks)
    assert total.dtype == np.float64
    assert np.max(np.abs(total)) <= 1.0 + 1e-6
    assert not np.any(np.isnan(total))
    assert float(np.sqrt(np.mean(total ** 2))) > 0.005


def test_granular_cloud_is_deterministic_given_seed():
    timbre = calibrate_color(0.03, 0.68, 0.94)
    a = GranularCloudSource(44100, seed=9)
    b = GranularCloudSource(44100, seed=9)
    out_a = np.concatenate([a.render(1, timbre, 90.0, 512, GRANULAR_PRESETS[1]) for _ in range(20)])
    out_b = np.concatenate([b.render(1, timbre, 90.0, 512, GRANULAR_PRESETS[1]) for _ in range(20)])
    np.testing.assert_array_equal(out_a, out_b)


def test_granular_cloud_voice_dropped_on_sync():
    src = GranularCloudSource(44100, seed=2)
    timbre = calibrate_color(0.03, 0.68, 0.94)
    src.render(1, timbre, 90.0, 256, GRANULAR_PRESETS[0])
    assert 1 in src._voices
    src.sync([])
    assert 1 not in src._voices

from soundscape_sources import RESONANT_PRESETS, ResonantPulseSource


def test_resonant_has_five_presets_with_required_keys():
    assert len(RESONANT_PRESETS) == 5
    for p in RESONANT_PRESETS:
        assert {"id", "interval_semitones", "decay", "excite_gain"} <= set(p)
        assert 0.0 < p["decay"] < 1.0


def test_resonant_pulse_is_audible_bounded_and_stable():
    src = ResonantPulseSource(44100, seed=3)
    assignment = _assignment()
    blocks = [src.render(1, assignment, 90.0, 1024, RESONANT_PRESETS[1]) for _ in range(80)]
    total = np.concatenate(blocks)
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-3
    assert float(np.sqrt(np.mean(total ** 2))) > 0.01


def test_resonant_pulse_is_deterministic_given_seed():
    assignment = _assignment()
    a = ResonantPulseSource(44100, seed=5)
    b = ResonantPulseSource(44100, seed=5)
    out_a = np.concatenate([a.render(1, assignment, 100.0, 512, RESONANT_PRESETS[0]) for _ in range(10)])
    out_b = np.concatenate([b.render(1, assignment, 100.0, 512, RESONANT_PRESETS[0]) for _ in range(10)])
    np.testing.assert_array_equal(out_a, out_b)


def test_resonant_pulse_voice_dropped_on_sync():
    src = ResonantPulseSource(44100, seed=3)
    assignment = _assignment()
    src.render(1, assignment, 90.0, 256, RESONANT_PRESETS[0])
    assert 1 in src._voices
    src.sync([])
    assert 1 not in src._voices

from soundscape_sources import NOISE_PRESETS, FilteredNoiseSource


def _hf_ratio(x):
    mag = np.abs(np.fft.rfft(x))
    return float(np.sum(mag[len(mag) // 2:]) / (np.sum(mag) + 1e-12))


def test_noise_has_five_presets_with_required_keys():
    assert len(NOISE_PRESETS) == 5
    for p in NOISE_PRESETS:
        assert {"id", "tilt", "gain"} <= set(p)


def test_dark_preset_is_less_bright_than_bright_preset():
    src = FilteredNoiseSource(44100, seed=4)
    timbre = calibrate_color(0.0, 0.68, 0.94)
    dark = np.concatenate([src.render(1, timbre, 2048, {"id": "d", "tilt": -0.8, "gain": 1.0}) for _ in range(10)])
    bright = np.concatenate([src.render(2, timbre, 2048, {"id": "b", "tilt": 0.8, "gain": 1.0}) for _ in range(10)])
    assert _hf_ratio(bright) > _hf_ratio(dark)


def test_noise_output_is_bounded_and_nan_free():
    src = FilteredNoiseSource(44100, seed=4)
    timbre = calibrate_color(0.03, 0.68, 0.94)
    total = np.concatenate([src.render(1, timbre, 1024, NOISE_PRESETS[i % 5]) for i in range(40)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-6


def test_noise_voice_dropped_on_sync():
    src = FilteredNoiseSource(44100, seed=4)
    timbre = calibrate_color(0.03, 0.68, 0.94)
    src.render(1, timbre, 256, NOISE_PRESETS[0])
    assert 1 in src._voices
    src.sync([])
    assert 1 not in src._voices

from soundscape_sources import TEXTURE_PRESETS, SampleTextureSource


def test_texture_has_five_presets_with_required_keys():
    assert len(TEXTURE_PRESETS) == 5
    for p in TEXTURE_PRESETS:
        assert {"id", "window_ms", "drift_ms", "freeze"} <= set(p)


def test_texture_is_audible_bounded_and_nan_free_with_placeholder():
    src = SampleTextureSource(44100, seed=6)
    total = np.concatenate([src.render(1, 1024, TEXTURE_PRESETS[0]) for _ in range(60)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-6
    assert float(np.sqrt(np.mean(total ** 2))) > 0.005


def test_freeze_preset_barely_moves_the_read_window():
    src = SampleTextureSource(44100, seed=6)
    freeze_preset = dict(TEXTURE_PRESETS[0], freeze=True)
    src.render(1, 1024, freeze_preset)
    pos_before = src._voices[1]["pos"]
    for _ in range(20):
        src.render(1, 1024, freeze_preset)
    assert src._voices[1]["pos"] == pos_before


def test_non_freeze_preset_advances_the_read_window():
    src = SampleTextureSource(44100, seed=6)
    preset = next(p for p in TEXTURE_PRESETS if not p["freeze"])
    src.render(1, 1024, preset)
    pos_before = src._voices[1]["pos"]
    for _ in range(20):
        src.render(1, 1024, preset)
    assert src._voices[1]["pos"] != pos_before


def test_load_sample_changes_the_output():
    src_a = SampleTextureSource(44100, seed=6)
    src_b = SampleTextureSource(44100, seed=6)
    src_b.load_sample(np.sin(2 * np.pi * 440 * np.arange(44100 * 3) / 44100))
    out_a = np.concatenate([src_a.render(1, 1024, TEXTURE_PRESETS[0]) for _ in range(20)])
    out_b = np.concatenate([src_b.render(1, 1024, TEXTURE_PRESETS[0]) for _ in range(20)])
    assert not np.allclose(out_a, out_b)


def test_texture_voice_dropped_on_sync():
    src = SampleTextureSource(44100, seed=6)
    src.render(1, 256, TEXTURE_PRESETS[0])
    assert 1 in src._voices
    src.sync([])
    assert 1 not in src._voices

from soundscape_sources import SOURCE_PRESETS, SourceBank


def test_source_presets_has_exactly_25_unique_ids():
    assert len(SOURCE_PRESETS) == 25
    assert len({p["id"] for p in SOURCE_PRESETS}) == 25


def test_source_bank_renders_every_preset_without_error():
    bank = SourceBank(44100, seed=7)
    assignment = _assignment()
    for preset in SOURCE_PRESETS:
        out = bank.render(1, preset["id"], assignment, 0.03, 0.68, 0.94, 90.0, 512)
        assert out.shape == (512,)
        assert not np.any(np.isnan(out))
        bank.sync([])  # reset voice state between presets sharing id 1


def test_source_bank_sync_clears_all_engines():
    bank = SourceBank(44100, seed=7)
    assignment = _assignment()
    bank.render(1, "additive_1", assignment, 0.03, 0.68, 0.94, 90.0, 256)
    bank.render(1, "granular_1", assignment, 0.03, 0.68, 0.94, 90.0, 256)
    bank.sync([])
    assert bank.additive._voices == {}
    assert bank.granular._voices == {}
    assert bank.resonant._voices == {}
    assert bank.noise._voices == {}
    assert bank.texture._voices == {}


def test_source_bank_unknown_preset_raises():
    bank = SourceBank(44100, seed=7)
    try:
        bank.preset("not_a_real_preset")
        assert False, "expected KeyError"
    except KeyError:
        pass
