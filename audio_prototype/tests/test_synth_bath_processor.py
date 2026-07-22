import numpy as np

from synth_bath_processor import SynthBathProcessor, synth_bath_role


SR = 44100


def _tone(freq=216.0, seconds=3.0):
    t = np.arange(int(SR * seconds), dtype=np.float64) / SR
    return (0.45 * np.sin(2.0 * np.pi * freq * t)).astype(np.float64)


def _layer(layer_id, engine="granules", row=1, col=0, bpm=72.0):
    return {
        "id": layer_id,
        "hue": 0.03,
        "sat": 0.68,
        "val": 0.94,
        "bpm": bpm,
        "engine": engine,
        "patch_row": row,
        "patch_col": col,
    }


def test_synth_bath_roles_map_patch_rows_to_ambient_functions():
    assert synth_bath_role(_layer(1, engine="microloop", row=0)) == "stretch"
    assert synth_bath_role(_layer(1, engine="granules", row=1)) == "delay"
    assert synth_bath_role(_layer(1, engine="glitch", row=2)) == "reverb"
    assert synth_bath_role(_layer(1, engine="multidelay", row=3)) == "stereo"
    assert synth_bath_role(_layer(1, engine="tape", row=4)) == "shape"


def test_synth_bath_processor_produces_audible_bounded_wet_signal():
    proc = SynthBathProcessor(SR, seed=3)
    layer = _layer(1, engine="granules", row=1, col=2)
    source = _tone()

    out = np.concatenate(
        [
            proc.process(
                1024,
                [layer],
                source_arrays={1: source},
                source_positions={1: i * 1024},
            )
            for i in range(50)
        ]
    )

    assert out.dtype == np.float32
    assert float(np.sqrt(np.mean(out.astype(np.float64) ** 2))) > 0.004
    assert np.max(np.abs(out)) <= 1.0
    assert not np.any(np.isnan(out))


def test_synth_bath_rows_have_distinct_ambient_outputs_without_pitch_reads():
    source = _tone()
    rendered = []
    for row, engine in enumerate(("microloop", "granules", "glitch", "multidelay", "tape")):
        proc = SynthBathProcessor(SR, seed=4)
        layer = _layer(1, engine=engine, row=row, col=2)
        rendered.append(
            np.concatenate(
                [
                    proc.process(
                        1024,
                        [layer],
                        source_arrays={1: source},
                        source_positions={1: i * 1024},
                    )
                    for i in range(25)
                ]
            )
        )

    rms = [float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) for x in rendered]
    assert max(rms) - min(rms) > 0.002
    assert len({round(v, 4) for v in rms}) >= 3


def test_synth_bath_processor_uses_unison_source_reads_only():
    proc = SynthBathProcessor(SR, seed=5)
    source = _tone()
    layer = _layer(1, engine="multidelay", row=3, col=4)

    proc.process(2048, [layer], source_arrays={1: source}, source_positions={1: 0})

    assert proc.debug_read_ratios == [1.0]


def test_sample_backed_low_cpu_path_avoids_python_loop_effect_primitives():
    proc = SynthBathProcessor(SR, seed=5)
    source = _tone()
    layer = _layer(1, engine="multidelay", row=3, col=4)

    def fail_if_slow_delay_is_used(*args, **kwargs):
        raise AssertionError("low CPU sample-backed path should avoid feedback delay loops")

    def fail_if_slow_filter_is_used(*args, **kwargs):
        raise AssertionError("low CPU sample-backed path should avoid one-pole loops")

    proc._delay = fail_if_slow_delay_is_used
    proc._one_pole = fail_if_slow_filter_is_used
    out = proc.process(
        2048,
        [layer],
        source_arrays={1: source},
        source_positions={1: 0},
        low_cpu=True,
    )

    assert float(np.sqrt(np.mean(out.astype(np.float64) ** 2))) > 0.0
    assert proc.debug_read_ratios == [1.0]


def test_dense_synth_bath_layers_stay_bounded():
    proc = SynthBathProcessor(SR, seed=7)
    layers = [
        _layer(
            i + 1,
            engine=("microloop", "granules", "glitch", "multidelay", "tape")[i % 5],
            row=i % 5,
            col=i % 5,
            bpm=55 + i * 4,
        )
        for i in range(20)
    ]
    source_arrays = {layer["id"]: _tone(216.0 + (i % 5) * 54.0) for i, layer in enumerate(layers)}

    out = np.concatenate(
        [
            proc.process(
                1024,
                layers,
                source_arrays=source_arrays,
                source_positions={layer["id"]: i * 1024 for layer in layers},
            )
            for i in range(60)
        ]
    )

    assert float(np.sqrt(np.mean(out.astype(np.float64) ** 2))) > 0.008
    assert np.max(np.abs(out)) <= 1.0
    assert not np.any(np.isnan(out))
