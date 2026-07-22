import numpy as np

from synth_source import SeedBank, WAVETABLE_LEN, DEFAULT_SEED_COUNT
import modulation as mod
from synth_source import (
    DRONE_RATIOS,
    DRONE_ROOT_HZ,
    drone_pitch_hz,
    voice_timbre_from_color,
)


def test_seed_bank_is_deterministic_and_shaped():
    a = SeedBank(seed=7)
    b = SeedBank(seed=7)
    assert len(a) == DEFAULT_SEED_COUNT
    for i in range(len(a)):
        assert a.table(i).shape == (WAVETABLE_LEN,)
        assert a.table(i).dtype == np.float64
        assert np.max(np.abs(a.table(i))) <= 1.0 + 1e-9
        np.testing.assert_array_equal(a.table(i), b.table(i))


def test_seed_bank_index_wraps():
    bank = SeedBank(seed=1)
    np.testing.assert_array_equal(bank.table(0), bank.table(len(bank)))


def test_higher_seeds_are_brighter():
    # brightness ~ high-frequency energy; compare the top half of the rFFT
    bank = SeedBank(seed=3)

    def hf_ratio(tbl):
        mag = np.abs(np.fft.rfft(tbl))
        return float(np.sum(mag[len(mag) // 2:]) / (np.sum(mag) + 1e-12))

    assert hf_ratio(bank.table(len(bank) - 1)) > hf_ratio(bank.table(0))


def test_drone_pitches_are_consonant_and_spread_upward():
    p0 = drone_pitch_hz(0)
    assert p0 == DRONE_ROOT_HZ
    # every pitch is the root times a rational-consonant factor (ratio * 2**octave)
    for i in range(24):
        factor = drone_pitch_hz(i) / DRONE_ROOT_HZ
        octave = i // len(DRONE_RATIOS)
        ratio = DRONE_RATIOS[i % len(DRONE_RATIOS)]
        assert abs(factor - ratio * (2.0 ** octave)) < 1e-9
    # higher order indices trend higher in pitch
    assert drone_pitch_hz(12) > drone_pitch_hz(0)


def test_color_maps_to_timbre_in_one_place():
    seed_count = 6
    dark = voice_timbre_from_color(
        mod.FINGER_HUE_MIN, mod.FINGER_SAT_MIN, mod.FINGER_VAL_MIN, seed_count
    )
    bright = voice_timbre_from_color(
        mod.FINGER_HUE_MAX, mod.FINGER_SAT_MAX, mod.FINGER_VAL_MAX, seed_count
    )
    assert 0 <= dark["seed_index"] < seed_count
    assert 0 <= bright["seed_index"] < seed_count
    assert bright["seed_index"] >= dark["seed_index"]
    assert bright["brightness"] > dark["brightness"]
    assert 0.0 <= dark["spread"] <= 1.0
    assert 0.0 <= bright["spread"] <= 1.0
