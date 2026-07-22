import numpy as np
import pytest

from web_engine import SAMPLE_SYNTH_WET_VOICE_BUDGET, WebEngine

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


def test_ensure_mode_switches_without_clearing_sources():
    engine = WebEngine(samplerate=SR, seed=1)
    sid = engine.registry.add_source(hue=0.03, sat=0.68, val=0.94, bpm=90)
    engine.registry.connect_source(sid, engine="granules", row=1, col=0)
    engine.ensure_mode("synth")

    assert engine.mode == "synth"
    assert len(engine.registry.snapshot()) == 1
    block = engine.generate_block(1024)
    assert float(np.sqrt(np.mean(block.astype(np.float64) ** 2))) > 0.0


def test_set_synth_options_is_compatibility_noop_without_clearing_sources():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    sid = engine.registry.add_source(hue=0.03, sat=0.68, val=0.94, bpm=90)
    engine.registry.connect_source(sid, engine="granules", row=1, col=0)
    engine.generate_block(1024)
    before = engine.synth.buffer_for(sid).copy()

    engine.set_synth_options(tone_mode="rhodes", harmony_mode="lydian_add9")
    assert len(engine.registry.snapshot()) == 1
    engine.generate_block(1024)
    after = engine.synth.buffer_for(sid)

    assert engine.tone_mode == "rhodes"
    assert engine.harmony_mode == "lydian_add9"
    np.testing.assert_array_equal(before, after)


def test_synth_wet_layers_are_budgeted_and_rotated_for_dense_patches():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    assert engine.synth_wet_voice_budget == 5
    for i in range(18):
        _connect(
            engine,
            sid_hue=0.03 + (i % 5) * 0.01,
            engine_name=("granules", "glitch", "multidelay", "microloop")[i % 4],
            row=i % 4,
            col=i % 5,
        )

    layers = engine.registry.snapshot()
    first = engine._budget_synth_wet_layers(layers)
    second = engine._budget_synth_wet_layers(layers)

    assert len(first) == engine.synth_wet_voice_budget
    assert len(second) == engine.synth_wet_voice_budget
    assert {layer["id"] for layer in first} != {layer["id"] for layer in second}


def test_sample_backed_synth_uses_smaller_rotating_wet_budget():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    sample = np.sin(2.0 * np.pi * 216.0 * np.arange(SR) / SR).astype(np.float32)
    engine.load_synth_sample("local-pad-C.wav", sample)
    for i in range(18):
        _connect(
            engine,
            sid_hue=0.03 + (i % 5) * 0.01,
            engine_name=("granules", "glitch", "multidelay", "microloop")[i % 4],
            row=i % 4,
            col=i % 5,
            output_slot=i,
        )

    first = engine._budget_synth_wet_layers(engine.registry.snapshot())
    second = engine._budget_synth_wet_layers(engine.registry.snapshot())

    assert SAMPLE_SYNTH_WET_VOICE_BUDGET == 1
    assert len(first) == SAMPLE_SYNTH_WET_VOICE_BUDGET
    assert len(second) == SAMPLE_SYNTH_WET_VOICE_BUDGET
    assert {layer["id"] for layer in first} != {layer["id"] for layer in second}


def _connect(
    engine,
    sid_hue=0.03,
    sat=0.68,
    val=0.94,
    bpm=90,
    engine_name="granules",
    row=1,
    col=0,
    output_slot=None,
):
    sid = engine.registry.add_source(hue=sid_hue, sat=sat, val=val, bpm=bpm)
    engine.registry.connect_source(
        sid, engine=engine_name, row=row, col=col, output_slot=output_slot
    )
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


def test_web_engine_accepts_loaded_synth_samples_from_worker():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    engine.wet_dry = 0.0
    sample = np.sin(2.0 * np.pi * 216.0 * np.arange(SR) / SR).astype(np.float32)

    engine.load_synth_sample("local-pad-C.wav", sample)
    sid = _connect(engine, row=0, col=0)
    out = np.concatenate([engine.generate_block(1024) for _ in range(20)])

    assert engine.synth._voices[sid]["timbre"]["source"] == "sample"
    assert engine.synth._voices[sid]["timbre"]["sample_name"] == "local-pad-C.wav"
    assert float(np.sqrt(np.mean(out.astype(np.float64) ** 2))) > 0.01
    assert np.max(np.abs(out)) <= 1.0


def test_sample_backed_synth_skips_global_spectral_smear():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    engine.wet_dry = 1.0
    sample = np.sin(2.0 * np.pi * 216.0 * np.arange(SR) / SR).astype(np.float32)
    engine.load_synth_sample("local-pad-C.wav", sample)
    _connect(engine, engine_name="granules", row=1, col=0, output_slot=0)

    def fail_if_smear_is_used(*args, **kwargs):
        raise AssertionError("sample-backed synth should skip global spectral smear")

    engine.spectral_smear.process = fail_if_smear_is_used
    out = engine.generate_block(1024)

    assert float(np.sqrt(np.mean(out.astype(np.float64) ** 2))) > 0.0


def test_sample_backed_synth_skips_global_reverb_processor():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    engine.wet_dry = 1.0
    sample = np.sin(2.0 * np.pi * 216.0 * np.arange(SR) / SR).astype(np.float32)
    engine.load_synth_sample("local-pad-C.wav", sample)
    _connect(engine, engine_name="granules", row=1, col=0, output_slot=0)

    def fail_if_reverb_is_used(*args, **kwargs):
        raise AssertionError("sample-backed synth should use lightweight row effects only")

    engine.reverb.process = fail_if_reverb_is_used
    out = engine.generate_block(1024)

    assert float(np.sqrt(np.mean(out.astype(np.float64) ** 2))) > 0.0


def test_synth_micro_voice_adds_wet_distinct_from_dry():
    wet_engine = WebEngine(samplerate=SR, seed=1)
    wet_engine.set_mode("synth")
    wet_engine.wet_dry = 1.0
    _connect(wet_engine, engine_name="granules", row=1, col=0)

    dry_engine = WebEngine(samplerate=SR, seed=1)
    dry_engine.set_mode("synth")
    dry_engine.wet_dry = 0.0
    _connect(dry_engine, engine_name="granules", row=1, col=0)

    wet_blocks, dry_blocks = [], []
    for _ in range(40):
        w = wet_engine.generate_block(1024)
        d = dry_engine.generate_block(1024)
        wet_blocks.append(w)
        dry_blocks.append(d)
        assert not np.any(np.isnan(w))
        assert np.max(np.abs(w)) <= 1.0
    assert float(np.sqrt(np.mean(np.concatenate(wet_blocks) ** 2))) > 0.005
    assert any(
        not np.allclose(w, d, atol=1e-6) for w, d in zip(wet_blocks, dry_blocks)
    )


def test_synth_mode_uses_bath_processor_not_loop_microcosm():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    engine.wet_dry = 1.0
    _connect(engine, engine_name="granules", row=1, col=0)

    def fail_if_loop_processor_is_used(*args, **kwargs):
        raise AssertionError("synth mode should not use loop microcosm effects")

    engine.microcosm.process = fail_if_loop_processor_is_used
    out = np.concatenate([engine.generate_block(1024) for _ in range(40)])

    assert float(np.sqrt(np.mean(out.astype(np.float64) ** 2))) > 0.003
    assert np.max(np.abs(out)) <= 1.0


def test_two_micro_voices_are_bounded():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    _connect(engine, engine_name="granules", row=1, col=0)
    _connect(engine, engine_name="glitch", row=2, col=2)
    for _ in range(60):
        block = engine.generate_block(2048)
        assert np.max(np.abs(block)) <= 1.0
        assert not np.any(np.isnan(block))


def test_shape_row_voice_is_a_tape_toned_drone():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    engine.wet_dry = 1.0
    _connect(engine, engine_name="tape", row=4, col=0)
    total = np.concatenate([engine.generate_block(2048) for _ in range(50)])
    assert float(np.sqrt(np.mean(total**2))) > 0.01
    assert np.max(np.abs(total)) <= 1.0
    assert not np.any(np.isnan(total))


def test_density_deepens_the_smear_and_reverb():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    for i in range(6):
        _connect(engine, engine_name="granules", row=1, col=i % 5)
    for _ in range(20):
        engine.generate_block(2048)
    assert engine.reverb.space_style == "wash"
    assert engine.reverb.space_size > 0.35
    assert not np.any(np.isnan(engine.generate_block(2048)))


def test_full_room_output_stays_bounded():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    engines = ("granules", "glitch", "multidelay", "microloop", "tape")
    for i in range(20):
        _connect(
            engine,
            engine_name=engines[i % 5],
            row=i % 5,
            col=i % 5,
            bpm=60 + 4 * i,
        )
    for _ in range(60):
        block = engine.generate_block(2048)
        assert np.max(np.abs(block)) <= 1.0
        assert not np.any(np.isnan(block))


def test_dense_synth_dry_bed_is_trimmed_below_single_voice():
    def connect_numbered(engine, index):
        engines = ("granules", "glitch", "multidelay", "microloop", "tape")
        sid = engine.registry.add_source(
            hue=0.03 + (index % 5) * 0.01,
            sat=0.68,
            val=0.94,
            bpm=80 + index * 3,
        )
        engine.registry.connect_source(
            sid, engine=engines[index % 5], row=index % 5, col=index % 5
        )

    single = WebEngine(samplerate=SR, seed=1)
    single.set_mode("synth")
    single.wet_dry = 0.0
    connect_numbered(single, 0)

    dense = WebEngine(samplerate=SR, seed=1)
    dense.set_mode("synth")
    dense.wet_dry = 0.0
    for i in range(20):
        connect_numbered(dense, i)

    single_out = np.concatenate([single.generate_block(2048) for _ in range(60)])
    dense_out = np.concatenate([dense.generate_block(2048) for _ in range(60)])
    single_rms = float(np.sqrt(np.mean(single_out.astype(np.float64) ** 2)))
    dense_rms = float(np.sqrt(np.mean(dense_out.astype(np.float64) ** 2)))
    assert dense_rms <= single_rms * 0.85


def test_dense_generated_synth_keeps_final_headroom():
    engine = WebEngine(samplerate=SR, seed=1)
    engine.set_mode("synth")
    engine.wet_dry = 0.5
    for i in range(20):
        sid = engine.registry.add_source(
            hue=0.03 + (i % 5) * 0.01,
            sat=0.72,
            val=0.98,
            bpm=70 + i,
        )
        engine.registry.connect_source(
            sid,
            engine=("granules", "glitch", "multidelay", "microloop", "tape")[i % 5],
            row=i % 5,
            col=i % 5,
        )

    out = np.concatenate([engine.generate_block(2048) for _ in range(80)])
    peak = float(np.max(np.abs(out)))
    rms = float(np.sqrt(np.mean(out.astype(np.float64) ** 2)))

    assert peak <= 0.88
    assert rms <= 0.34
