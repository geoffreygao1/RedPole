import numpy as np

from synth_source import SeedBank, WAVETABLE_LEN, DEFAULT_SEED_COUNT
import modulation as mod
from synth_source import (
    DRONE_RATIOS,
    DRONE_ROOT_HZ,
    MAX_DETUNE_CENTS,
    SynthVoiceBank,
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


def _layer(
    layer_id,
    hue=0.03,
    sat=0.68,
    val=0.94,
    bpm=90.0,
    engine="granules",
    row=1,
    col=0,
):
    return {
        "id": layer_id,
        "hue": hue,
        "sat": sat,
        "val": val,
        "bpm": bpm,
        "engine": engine,
        "patch_row": row,
        "patch_col": col,
    }


def test_voice_block_shape_and_lifecycle():
    bank = SynthVoiceBank(44100, seed=5)
    layers = [_layer(1, row=1, col=0), _layer(2, row=1, col=1)]
    blocks = bank.block(layers, 512)
    assert set(blocks) == {1, 2}
    for b in blocks.values():
        assert b.shape == (512,)
        assert b.dtype == np.float64
        assert np.max(np.abs(b)) <= 1.0 + 1e-6
    # dropping a layer tears its voice down
    bank.block([_layer(1)], 512)
    assert bank.buffer_for(2) is None
    assert bank.buffer_for(1) is not None


def test_voice_is_a_sustained_tone_not_silence():
    bank = SynthVoiceBank(44100, seed=5)
    total = np.concatenate([bank.block([_layer(1)], 1024)[1] for _ in range(40)])
    assert float(np.sqrt(np.mean(total ** 2))) > 0.05


def test_voices_are_detuned_from_each_other():
    # two voices at the SAME drone slot but different ids must not be identical
    bank = SynthVoiceBank(44100, seed=5)
    b1 = bank.buffer_for
    bank.block([_layer(1, row=1, col=0), _layer(2, row=1, col=0)], 256)
    v1, v2 = bank.buffer_for(1), bank.buffer_for(2)
    # different loop lengths (phase-drift) and/or detune => not equal
    assert v1.shape != v2.shape or not np.allclose(v1[:256], v2[:256])


def test_read_position_advances_and_wraps():
    bank = SynthVoiceBank(44100, seed=5)
    bank.block([_layer(1)], 1000)
    p1 = bank.read_pos(1)
    bank.block([_layer(1)], 1000)
    p2 = bank.read_pos(1)
    n = len(bank.buffer_for(1))
    assert p2 == (p1 + 1000) % n


def test_reset_clears_voices():
    bank = SynthVoiceBank(44100, seed=5)
    bank.block([_layer(1)], 256)
    bank.reset()
    assert bank.buffer_for(1) is None
