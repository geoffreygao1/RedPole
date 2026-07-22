import numpy as np

from synth_source import SeedBank, WAVETABLE_LEN, DEFAULT_SEED_COUNT
import modulation as mod
from synth_source import (
    DRONE_RATIOS,
    DRONE_ROOT_HZ,
    SynthVoiceBank,
    drone_pitch_hz,
    voice_params_from_scan,
    voice_character_for_slot,
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


def test_drone_pitches_are_restrained_and_varied_not_a_chord_ladder():
    p0 = drone_pitch_hz(0)
    assert p0 == DRONE_ROOT_HZ
    assert DRONE_ROOT_HZ == 216.0
    first = [drone_pitch_hz(i) for i in range(8)]
    assert first != sorted(first)
    assert max(first) / min(first) <= 3.1
    assert any(abs(pitch - 432.0) <= 0.01 for pitch in first)
    assert min(first) >= 200.0
    assert max(first) <= 500.0

    pair_ratios = []
    for i, a in enumerate(first):
        for b in first[i + 1:]:
            pair_ratios.append(max(a, b) / min(a, b))
    assert any(1.004 <= ratio <= 1.045 for ratio in pair_ratios)
    assert any(
        abs(ratio - 1.5) <= 0.025 or abs(ratio - 2.0) <= 0.025
        for ratio in pair_ratios
    )

    second_cycle = [drone_pitch_hz(i) for i in range(8, 16)]
    assert max(second_cycle) / min(second_cycle) <= 3.1


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


def test_bpm_maps_directly_to_loop_length_and_space():
    slow = voice_params_from_scan(0.02, 0.64, 0.92, 45, "scan", "open")
    fast = voice_params_from_scan(0.02, 0.64, 0.92, 180, "scan", "open")

    assert slow["loop_seconds"] > fast["loop_seconds"]
    assert slow["event_duty"] > fast["event_duty"]
    assert slow["breath_seconds"] > fast["breath_seconds"]


def test_hue_saturation_and_value_map_to_obvious_sound_parameters():
    red = voice_params_from_scan(
        mod.FINGER_HUE_MIN, mod.FINGER_SAT_MIN, mod.FINGER_VAL_MIN, 90, "scan", "open"
    )
    orange = voice_params_from_scan(
        mod.FINGER_HUE_MAX, mod.FINGER_SAT_MAX, mod.FINGER_VAL_MAX, 90, "scan", "open"
    )

    assert "family" not in red
    assert "family" not in orange
    assert orange["spectral_focus"] > red["spectral_focus"]
    assert orange["motion"] > red["motion"]
    assert orange["brightness"] > red["brightness"]
    assert orange["attack_seconds"] <= red["attack_seconds"]


def test_25_patch_slots_have_distinct_generated_voice_characters():
    characters = [voice_character_for_slot(i) for i in range(25)]
    keys = [
        (
            c["wave_mix"],
            c["noise"],
            c["filter"],
            c["shimmer"],
            c["pulse"],
            c["halo"],
        )
        for c in characters
    ]

    assert len(set(keys)) == 25
    assert {c["role"] for c in characters} >= {
        "low_bed",
        "warm_mid",
        "air",
        "shimmer",
        "soft_pulse",
        "bell_wash",
    }
    assert max(c["noise"] for c in characters) <= 0.11
    assert max(c["shimmer"] for c in characters) <= 0.14
    assert all(0.0 <= c["halo"] <= 0.09 for c in characters)


def test_harmony_modes_do_not_repitch_generated_sound_bath_voices():
    open_pitches = [drone_pitch_hz(i, "open") for i in range(8)]
    lydian_pitches = [drone_pitch_hz(i, "lydian_add9") for i in range(8)]
    minor_pitches = [drone_pitch_hz(i, "minor9") for i in range(8)]

    np.testing.assert_allclose(open_pitches, lydian_pitches)
    np.testing.assert_allclose(open_pitches, minor_pitches)


def _layer(
    layer_id,
    hue=0.03,
    sat=0.68,
    val=0.94,
    bpm=90.0,
    engine="granules",
    row=1,
    col=0,
    output_slot=None,
):
    layer = {
        "id": layer_id,
        "hue": hue,
        "sat": sat,
        "val": val,
        "bpm": bpm,
        "engine": engine,
        "patch_row": row,
        "patch_col": col,
    }
    if output_slot is not None:
        layer["output_slot"] = output_slot
    return layer


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


def test_voice_has_slow_amplitude_motion():
    bank = SynthVoiceBank(44100, seed=5)
    bank.block([_layer(1)], 512)
    buf = bank.buffer_for(1)
    window = 4410
    rms = np.array(
        [
            np.sqrt(np.mean(buf[i : i + window] ** 2))
            for i in range(0, len(buf) - window, window)
        ]
    )
    assert float(np.max(rms) / max(1e-9, np.min(rms))) >= 1.12


def test_output_slots_render_distinct_spectral_shapes():
    first = SynthVoiceBank(44100, seed=5)
    second = SynthVoiceBank(44100, seed=5)
    first.block([_layer(1, hue=0.02, sat=0.68, val=0.94, bpm=90, row=0, col=0, output_slot=0)], 512)
    second.block([_layer(1, hue=0.02, sat=0.68, val=0.94, bpm=90, row=0, col=0, output_slot=24)], 512)

    def hf_ratio(buf):
        mag = np.abs(np.fft.rfft(buf))
        return float(np.sum(mag[len(mag) // 3 :]) / (np.sum(mag) + 1e-12))

    assert not np.isclose(hf_ratio(first.buffer_for(1)), hf_ratio(second.buffer_for(1)))


def test_same_output_keeps_pitch_and_timbre_when_effect_column_changes():
    bank = SynthVoiceBank(44100, seed=5)
    layer = _layer(3, hue=0.02, sat=0.68, val=0.94, bpm=90, row=0, col=0, output_slot=2)
    bank.block([layer], 512)
    first_voice = bank._voices[3]
    first_buffer = first_voice["buffer"].copy()

    bank.block([{**layer, "patch_col": 4}], 512)
    second_voice = bank._voices[3]

    assert second_voice["pitch_hz"] == first_voice["pitch_hz"]
    np.testing.assert_array_equal(second_voice["buffer"], first_buffer)


def test_generated_voices_use_soft_phrase_start():
    bank = SynthVoiceBank(44100, seed=5)
    bank.block(
        [_layer(1, hue=0.03, sat=0.68, val=0.94, bpm=60, row=3, col=2, output_slot=17)],
        512,
    )
    voice = bank._voices[1]

    assert voice["timbre"]["source"] == "generated"
    assert voice["timbre"]["slot_index"] == 17
    buf = voice["buffer_for_effects"]
    early_rms = float(np.sqrt(np.mean(buf[:2048] ** 2)))
    body_rms = float(np.sqrt(np.mean(buf[8192:12288] ** 2)))
    assert early_rms < body_rms * 0.65


def test_voices_use_exact_drone_pitch_without_random_detune():
    bank = SynthVoiceBank(44100, seed=5)
    layer = _layer(1, row=1, col=0, output_slot=0)
    bank.block([layer], 256)

    assert bank._voices[1]["pitch_hz"] == drone_pitch_hz(0)


def test_same_slot_voices_keep_distinct_phrase_buffers_without_pitch_detune():
    # two voices from the SAME output slot may have different rendered phrase
    # buffers, but their pitch center should not be randomized.
    bank = SynthVoiceBank(44100, seed=5)
    bank.block(
        [_layer(1, row=1, col=0, output_slot=5), _layer(2, row=1, col=0, output_slot=5)],
        256,
    )
    v1, v2 = bank.buffer_for(1), bank.buffer_for(2)

    assert bank._voices[1]["pitch_hz"] == bank._voices[2]["pitch_hz"]
    assert v1.shape != v2.shape or not np.allclose(v1[:256], v2[:256])


def test_loaded_samples_replace_generated_fallback():
    bank = SynthVoiceBank(44100, seed=5)
    sample = np.linspace(-0.6, 0.6, 44100, dtype=np.float32)

    bank.load_sample("warm-pad-C.wav", sample)
    bank.block([_layer(1, output_slot=0)], 512)
    voice = bank._voices[1]

    assert voice["timbre"]["source"] == "sample"
    assert voice["timbre"]["sample_name"] == "warm-pad-C.wav"
    assert bank.buffer_for(1).dtype == np.float64


def test_loaded_sample_voice_precomputes_bpm_envelope_for_low_cpu():
    bank = SynthVoiceBank(44100, seed=5)
    sample = np.sin(2.0 * np.pi * 216.0 * np.arange(44100) / 44100).astype(np.float32)

    bank.load_sample("warm-pad-C.wav", sample)
    bank.block([_layer(1, bpm=60, output_slot=0)], 512)
    voice = bank._voices[1]

    assert "env_buffer" in voice
    assert len(voice["env_buffer"]) == int(round(voice["env_period"] * bank.samplerate))
    assert np.max(voice["env_buffer"]) <= 1.0
    assert np.min(voice["env_buffer"]) >= 0.0


def test_output_slots_choose_distinct_loaded_samples_without_repitching():
    bank = SynthVoiceBank(44100, seed=5)
    pad = np.sin(2.0 * np.pi * 216.0 * np.arange(44100) / 44100).astype(np.float32)
    pluck = np.sin(2.0 * np.pi * 216.0 * np.arange(44100) / 44100).astype(np.float32)
    pluck[:4096] *= np.linspace(1.0, 0.1, 4096)

    bank.load_sample("pad-C.wav", pad)
    bank.load_sample("pluck-C.wav", pluck)
    bank.block([_layer(1, output_slot=0), _layer(2, output_slot=1)], 512)

    assert bank._voices[1]["timbre"]["sample_name"] == "pad-C.wav"
    assert bank._voices[2]["timbre"]["sample_name"] == "pluck-C.wav"
    assert bank._voices[1]["pitch_hz"] == bank._voices[2]["pitch_hz"] == drone_pitch_hz(0)
    assert not np.allclose(bank.buffer_for(1)[:4096], bank.buffer_for(2)[:4096])


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
