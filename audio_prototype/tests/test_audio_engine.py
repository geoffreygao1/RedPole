from pathlib import Path

import numpy as np
import pytest

from audio_engine import AudioEngine

SAMPLE_LOOP = Path(__file__).parent.parent / "assets" / "sample_loop.wav"


def test_load_loop_reads_bundled_sample():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    assert engine.loop_array is not None
    assert engine.loop_array.dtype == np.float32
    assert len(engine.loop_array) > 44100  # more than one second


def test_load_loop_rejects_mismatched_samplerate(tmp_path):
    import soundfile as sf

    bad_path = tmp_path / "wrong_rate.wav"
    sf.write(str(bad_path), np.zeros(1000, dtype=np.float32), 22050)
    engine = AudioEngine(samplerate=44100, seed=1)
    with pytest.raises(ValueError):
        engine.load_loop(str(bad_path))


def test_load_loop_reads_mp3(tmp_path):
    import soundfile as sf

    mp3_path = tmp_path / "loop.mp3"
    tone = 0.5 * np.sin(2 * np.pi * 220 * np.arange(44100) / 44100).astype(np.float32)
    sf.write(str(mp3_path), tone, 44100)
    engine = AudioEngine(seed=1)
    engine.load_loop(str(mp3_path))
    assert engine.loop_array is not None
    assert len(engine.loop_array) > 40000


def test_generate_block_requires_loaded_loop():
    engine = AudioEngine(seed=1)
    with pytest.raises(RuntimeError):
        engine.generate_block(512)


def test_generate_block_dry_matches_loop_with_no_layers():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)


def test_generate_block_changes_with_active_layer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    dry = engine.generate_block(1024)

    engine2 = AudioEngine(seed=1)
    engine2.load_loop(str(SAMPLE_LOOP))
    engine2.registry.add(hue=1.0, sat=1.0, val=1.0, bpm=120)
    wet = engine2.generate_block(1024)

    assert not np.allclose(dry, wet)


def test_generate_block_writes_to_visual_buffer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.generate_block(512)
    latest = engine.visual_buffer.read_latest(512)
    assert not np.allclose(latest, np.zeros(512))


def test_generate_block_writes_modulation_buffers():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.registry.add(hue=1.0, sat=1.0, val=1.0, bpm=120)
    engine.generate_block(512)
    warble = engine.warble_buffer.read_latest(512)
    bloom = engine.bloom_buffer.read_latest(512)
    assert not np.allclose(warble, np.zeros(512))
    assert not np.allclose(bloom, np.zeros(512))


def test_modulation_buffers_flat_with_no_layers():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.generate_block(512)
    np.testing.assert_allclose(engine.warble_buffer.read_latest(512), np.zeros(512), atol=1e-9)
    # bloom buffer stores gain - 1.0, so it's zero when dry
    np.testing.assert_allclose(engine.bloom_buffer.read_latest(512), np.zeros(512), atol=1e-9)


def test_default_mode_is_tape():
    engine = AudioEngine(seed=1)
    assert engine.mode == "tape"


def test_set_mode_validates():
    engine = AudioEngine(seed=1)
    engine.set_mode("spectral")
    assert engine.mode == "spectral"
    with pytest.raises(ValueError):
        engine.set_mode("reverb")


def test_spectral_mode_zero_layers_is_dry():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("spectral")
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)


def test_spectral_mode_layer_changes_output_and_wet_buffer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("spectral")
    engine.registry.add(hue=0.25, sat=0.5, val=1.0, bpm=120)
    block = engine.generate_block(2048)
    dry = engine.loop_array[np.arange(2048) % len(engine.loop_array)]
    assert not np.allclose(block, dry)
    wet = engine.wet_buffer.read_latest(2048)
    assert not np.allclose(wet, np.zeros(2048))


def test_granular_mode_layer_changes_output():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("granular")
    engine.registry.add(hue=0.25, sat=0.5, val=1.0, bpm=180)
    blocks = [engine.generate_block(1024) for _ in range(30)]
    total_wet = engine.wet_buffer.read_latest(1024 * 20)
    assert not np.allclose(total_wet, np.zeros_like(total_wet))
    assert all(b.shape == (1024,) for b in blocks)


def test_tape_mode_writes_zero_wet_buffer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.registry.add(hue=1.0, sat=1.0, val=1.0, bpm=120)
    engine.generate_block(512)
    np.testing.assert_allclose(engine.wet_buffer.read_latest(512), np.zeros(512))


def test_mixed_mode_in_modes():
    assert "mixed" in AudioEngine.MODES


def test_mixed_mode_zero_layers_is_dry():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("mixed")
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)


def test_mixed_mode_routes_layers_by_engine():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("mixed")
    engine.registry.add(hue=0.03, sat=0.5, val=1.0, bpm=120, engine="spectral")
    engine.registry.add(hue=0.03, sat=0.5, val=1.0, bpm=180, engine="granular")
    for _ in range(30):
        engine.generate_block(1024)
    # both processors should hold exactly one voice each
    assert len(engine.spectral._voices) == 1
    assert len(engine.granular._voices) == 1
    wet = engine.wet_buffer.read_latest(1024 * 20)
    assert not np.allclose(wet, np.zeros_like(wet))


def test_mixed_mode_tape_layer_modulates_base():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("mixed")
    engine.registry.add(hue=0.06, sat=1.0, val=1.0, bpm=120, engine="tape")
    block = engine.generate_block(2048)
    dry = engine.loop_array[np.arange(2048) % len(engine.loop_array)]
    assert not np.allclose(block, dry)
    # no spectral/granular layers -> wet stays silent
    np.testing.assert_allclose(engine.wet_buffer.read_latest(2048), np.zeros(2048))


def test_dry_is_ducked_with_wet_layers():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("granular")
    for _ in range(4):
        engine.registry.add(hue=0.0, sat=0.5, val=0.0, bpm=1.0, engine="granular")
    # val=0 silences grains; bpm=1 nearly never pulses -> block is just
    # the ducked dry signal
    block = engine.generate_block(512)
    dry = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    expected_duck = max(0.5, 1.0 / (1.0 + 0.12 * 4))
    np.testing.assert_allclose(block, dry * expected_duck, atol=1e-3)


def test_reverb_adds_tail_to_wet():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("granular")
    engine.reverb_mix = 1.0
    layer_id = engine.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=180, engine="granular")
    for _ in range(40):
        engine.generate_block(1024)
    engine.registry.remove(layer_id)
    # with the layer gone the raw wet is silent, but the reverb tail rings on
    tail = np.concatenate([engine.generate_block(1024) for _ in range(3)])
    dry = None  # tail block includes dry loop; compare against wet buffer instead
    wet_tail = engine.wet_buffer.read_latest(1024 * 3)
    assert not np.allclose(wet_tail, np.zeros_like(wet_tail))


def test_pause_resume_state_without_stream():
    engine = AudioEngine(seed=1)
    assert engine.paused is False
    engine.pause()
    assert engine.paused is True
    engine.resume()
    assert engine.paused is False


def test_live_analysis_flag_changes_spectral_behavior():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("spectral")
    engine.registry.add(hue=0.0, sat=0.0, val=1.0, bpm=120, engine="spectral")

    engine.live_analysis = False
    for _ in range(10):
        engine.generate_block(1024)
    precomputed = engine.generate_block(4096)

    engine2 = AudioEngine(seed=1)
    engine2.load_loop(str(SAMPLE_LOOP))
    engine2.set_mode("spectral")
    engine2.registry.add(hue=0.0, sat=0.0, val=1.0, bpm=120, engine="spectral")
    engine2.live_analysis = True
    for _ in range(10):
        engine2.generate_block(1024)
    live = engine2.generate_block(4096)

    assert not np.allclose(precomputed, live)
