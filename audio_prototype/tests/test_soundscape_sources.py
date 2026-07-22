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
