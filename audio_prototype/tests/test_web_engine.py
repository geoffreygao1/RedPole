import numpy as np
import pytest

from web_engine import WebEngine

SR = 44100


def _tone(freq, seconds=1.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    return (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_generate_block_requires_loaded_loop():
    engine = WebEngine(samplerate=SR, seed=1)
    with pytest.raises(RuntimeError):
        engine.generate_block(512)


def test_load_loop_accepts_predecoded_samples():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0))
    assert engine.loop_array is not None
    assert engine.loop_array.dtype == np.float32
    assert len(engine.loop_array) == SR


def test_load_loop_truncates_to_max_seconds():
    import web_engine as we

    engine = WebEngine(samplerate=SR, seed=1)
    long_tone = _tone(220.0, seconds=we.MAX_LOOP_SECONDS + 5.0)
    engine.load_loop(long_tone)
    assert len(engine.loop_array) == int(we.MAX_LOOP_SECONDS * SR)


def test_generate_block_dry_matches_loop_with_no_layers():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0))
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)
    assert block.dtype == np.float32


def test_tape_layer_changes_output():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    dry = engine.generate_block(1024)

    engine2 = WebEngine(samplerate=SR, seed=1)
    engine2.load_loop(_tone(220.0, seconds=2.0))
    source_id = engine2.registry.add_source(hue=0.04, sat=0.68, val=0.94, bpm=120)
    engine2.registry.connect_source(source_id, engine="tape", row=0, col=1)
    wet = engine2.generate_block(1024)

    assert not np.allclose(dry, wet)


def test_tape_column_controls_reach_the_modulator():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    source_id = engine.registry.add_source(hue=0.04, sat=1.0, val=1.0, bpm=120)
    # column 1 = flutter-emphasized per tape_column_controls
    engine.registry.connect_source(source_id, engine="tape", row=0, col=1)
    for _ in range(10):
        engine.generate_block(1024)
    assert engine.modulator.last_warble_signal is not None


def test_layer_removed_continues_seamlessly_without_position_jump():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    source_id = engine.registry.add_source(hue=0.04, sat=1.0, val=1.0, bpm=120)
    engine.registry.connect_source(source_id, engine="tape", row=0, col=1)
    engine.generate_block(512)
    pos_before_removal = engine.modulator._read_pos
    engine.registry.remove_source(source_id)

    block = engine.generate_block(512)
    loop_len = len(engine.loop_array)
    positions = (pos_before_removal + np.arange(512)) % loop_len
    idx0 = np.floor(positions).astype(np.int64) % loop_len
    idx1 = (idx0 + 1) % loop_len
    frac = positions - np.floor(positions)
    expected = engine.loop_array[idx0] * (1.0 - frac) + engine.loop_array[idx1] * frac
    np.testing.assert_allclose(block, expected, atol=1e-6)
