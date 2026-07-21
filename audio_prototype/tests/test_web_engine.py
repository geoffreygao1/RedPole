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


def _granules_layer(engine, hue=0.04, sat=0.8, val=1.0, bpm=150.0, col=0):
    source_id = engine.registry.add_source(hue=hue, sat=sat, val=val, bpm=bpm)
    engine.registry.connect_source(source_id, engine="granules", row=1, col=col)
    return source_id


def _reverb_layer(engine, hue=0.04, sat=0.6, val=0.9, bpm=90.0):
    source_id = engine.registry.add_source(hue=hue, sat=sat, val=val, bpm=bpm)
    engine.registry.connect_source(source_id, engine="reverb", row=0, col=4)
    return source_id


def test_generate_block_unchanged_with_no_layers_after_task_2():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0))
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)


def test_granules_layer_produces_wet_signal():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    _granules_layer(engine)

    dry_engine = WebEngine(samplerate=SR, seed=1)
    dry_engine.load_loop(_tone(220.0, seconds=2.0))

    blocks = []
    dry_blocks = []
    for _ in range(30):
        blocks.append(engine.generate_block(1024))
        dry_blocks.append(dry_engine.generate_block(1024))
    assert all(b.shape == (1024,) for b in blocks)
    assert all(not np.any(np.isnan(b)) for b in blocks)
    # granules must audibly differ from an identical dry-only engine --
    # a test that only checks "some nonzero signal" would pass even with
    # granules completely unwired, since the dry loop itself is nonzero.
    assert any(
        not np.allclose(b, d, atol=1e-6) for b, d in zip(blocks, dry_blocks)
    )


def test_reverb_only_layer_is_silent_without_another_effect():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    _reverb_layer(engine)

    dry_engine = WebEngine(samplerate=SR, seed=1)
    dry_engine.load_loop(_tone(220.0, seconds=2.0))

    block = None
    dry_block = None
    for _ in range(20):
        block = engine.generate_block(1024)
        dry_block = dry_engine.generate_block(1024)
    assert np.max(np.abs(block)) <= 1.0
    assert not np.any(np.isnan(block))
    # a reverb-only layer adds no source of its own, so output should stay
    # close to the plain dry/tape base -- not just "bounded and finite",
    # which a fully-wired reverb send would also satisfy.
    np.testing.assert_allclose(block, dry_block, atol=1e-3)


def test_reverb_layer_adds_tail_when_paired_with_granules():
    granules_only = WebEngine(samplerate=SR, seed=1)
    granules_only.load_loop(_tone(220.0, seconds=2.0))
    _granules_layer(granules_only)

    granules_and_reverb = WebEngine(samplerate=SR, seed=1)
    granules_and_reverb.load_loop(_tone(220.0, seconds=2.0))
    _granules_layer(granules_and_reverb)
    _reverb_layer(granules_and_reverb)

    granules_only_blocks = []
    granules_and_reverb_blocks = []
    for _ in range(40):
        granules_only_blocks.append(granules_only.generate_block(1024))
        granules_and_reverb_blocks.append(granules_and_reverb.generate_block(1024))
        assert not np.any(np.isnan(granules_and_reverb_blocks[-1]))
        assert np.max(np.abs(granules_and_reverb_blocks[-1])) <= 1.0

    # adding a reverb layer on top of an identical granules layer must
    # audibly change the output (the reverb tail) -- otherwise this test
    # would pass even if reverb layers were never wired into the wet sum.
    assert any(
        not np.allclose(a, b, atol=1e-6)
        for a, b in zip(granules_only_blocks, granules_and_reverb_blocks)
    )


def test_wet_dry_zero_is_pure_base():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.load_loop(_tone(220.0, seconds=2.0))
    engine.wet_dry = 0.0
    _granules_layer(engine)

    dry_engine = WebEngine(samplerate=SR, seed=1)
    dry_engine.load_loop(_tone(220.0, seconds=2.0))

    block = None
    dry_block = None
    for _ in range(20):
        block = engine.generate_block(1024)
        dry_block = dry_engine.generate_block(1024)
    np.testing.assert_allclose(block, dry_block, atol=1e-4)
