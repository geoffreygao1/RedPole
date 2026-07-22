import numpy as np
import pytest

from web_engine import WebEngine

SR = 44100


def test_engine_defaults_to_loop_mode():
    engine = WebEngine(samplerate=SR, seed=1)
    assert engine.mode == "loop"


def test_set_mode_rejects_unknown():
    engine = WebEngine(samplerate=SR, seed=1)
    with pytest.raises(ValueError):
        engine.set_mode("bogus")


def test_set_mode_resets_sources_and_state():
    engine = WebEngine(samplerate=SR, seed=1)
    sid = engine.registry.add_source(hue=0.03, sat=0.68, val=0.94, bpm=90)
    engine.registry.connect_source(sid, engine="granules", row=1, col=0)
    assert engine.registry.snapshot()
    engine.set_mode("synth")
    assert engine.mode == "synth"
    assert engine.registry.snapshot() == []
    assert engine.synth_tape == {}


def _connect(
    engine,
    sid_hue=0.03,
    sat=0.68,
    val=0.94,
    bpm=90,
    engine_name="granules",
    row=1,
    col=0,
):
    sid = engine.registry.add_source(hue=sid_hue, sat=sat, val=val, bpm=bpm)
    engine.registry.connect_source(sid, engine=engine_name, row=row, col=col)
    return sid


def test_synth_mode_needs_no_loop_and_is_silent_with_no_voices():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    block = engine.generate_block(1024)
    assert block.shape == (1024,)
    assert block.dtype == np.float32
    np.testing.assert_allclose(block, np.zeros(1024), atol=1e-7)


def test_synth_voice_produces_audible_dry_tone():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    engine.wet_dry = 0.0
    _connect(engine)
    total = np.concatenate([engine.generate_block(2048) for _ in range(40)])
    assert float(np.sqrt(np.mean(total**2))) > 0.02
    assert np.max(np.abs(total)) <= 1.0
    assert not np.any(np.isnan(total))
