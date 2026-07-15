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
