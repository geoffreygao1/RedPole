import pytest
import numpy as np

import modulation as mod
from microcosm_processor import (
    FAMILY_VARIANTS,
    MicrocosmProcessor,
    microcosm_controls,
    microcosm_variant,
)

SR = 44100


def _tone(freq, seconds=2.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _layer(layer_id, engine="granules", hue=0.0, sat=0.5, val=1.0, bpm=120.0):
    return {
        "id": layer_id,
        "engine": engine,
        "hue": hue,
        "sat": sat,
        "val": val,
        "bpm": bpm,
    }


def test_no_layers_is_silent():
    proc = MicrocosmProcessor(SR, seed=1)
    out = proc.process(_tone(220.0), 1024, [], source_pos=0)
    np.testing.assert_allclose(out, np.zeros(1024))
    assert out.dtype == np.float32


def test_each_microcosm_family_produces_source_derived_events():
    loop = _tone(220.0) + 0.25 * _tone(440.0)
    for i, engine in enumerate(("microloop", "granules", "glitch", "multidelay")):
        proc = MicrocosmProcessor(SR, seed=1)
        total = np.concatenate(
            [
                proc.process(loop, 1024, [_layer(i + 1, engine=engine)], source_pos=n * 1024)
                for n in range(80)
            ]
        )
        assert float(np.sqrt(np.mean(total**2))) > 0.0005
        assert np.max(np.abs(total)) < 0.7


def test_bpm_controls_event_spacing():
    slow = microcosm_controls(_layer(1, bpm=50.0))
    fast = microcosm_controls(_layer(1, bpm=180.0))

    assert fast["interval_seconds"] < slow["interval_seconds"]


def test_family_controls_separate_loop_delay_and_grain_timing():
    base = {
        "id": 1,
        "hue": (mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2,
        "sat": (mod.FINGER_SAT_MIN + mod.FINGER_SAT_MAX) / 2,
        "val": mod.FINGER_VAL_MAX,
        "bpm": 100.0,
    }
    microloop = microcosm_controls({**base, "engine": "microloop"})
    granules = microcosm_controls({**base, "engine": "granules"})
    glitch = microcosm_controls({**base, "engine": "glitch"})
    multidelay = microcosm_controls({**base, "engine": "multidelay"})

    assert microloop["interval_seconds"] > granules["interval_seconds"] * 1.8
    assert microloop["event_seconds"] > granules["event_seconds"] * 1.5
    assert glitch["event_seconds"] < granules["event_seconds"]
    assert multidelay["interval_seconds"] > granules["interval_seconds"] * 2.2
    assert multidelay["delay_base_seconds"] > granules["event_seconds"] * 5.0


def test_microloop_controls_are_slow_loops_not_glitch_stutters():
    base = {
        "id": 1,
        "hue": (mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2,
        "sat": mod.FINGER_SAT_MAX,
        "val": mod.FINGER_VAL_MAX,
        "bpm": 120.0,
    }
    microloop = microcosm_controls({**base, "engine": "microloop"})
    glitch = microcosm_controls({**base, "engine": "glitch"})

    assert microloop["interval_seconds"] >= glitch["interval_seconds"] * 3.5
    assert microloop["event_seconds"] >= glitch["event_seconds"] * 4.5
    assert microloop["event_seconds"] >= 0.6


def test_microloop_patch_column_controls_octave_spread():
    base = {"id": 1, "engine": "microloop", "hue": 0.0, "sat": 0.8, "val": 1.0, "bpm": 120.0}
    gentle = microcosm_controls({**base, "patch_col": 0})
    dramatic = microcosm_controls({**base, "patch_col": 4})

    assert gentle["pitch_ratios"] == (0.5, 1.0)
    assert dramatic["pitch_ratios"] == (0.5, 1.0, 2.0, 4.0)
    assert set(dramatic["pitch_ratios"]).issubset({0.5, 1.0, 2.0, 4.0})


def test_microloop_patch_column_five_emphasizes_octave_down():
    base = {"id": 1, "engine": "microloop", "hue": 0.0, "sat": 0.8, "val": 1.0, "bpm": 120.0}
    controls = microcosm_controls({**base, "patch_col": 4})
    weights = dict(zip(controls["pitch_ratios"], controls["pitch_weights"]))

    assert weights[0.5] > weights[1.0]
    assert weights[0.5] > weights[2.0]
    assert controls["octave_down_gain"] > 1.0


def test_pitch_modifying_microcosm_families_emphasize_lower_octaves():
    for engine in ("microloop", "granules", "glitch", "multidelay"):
        controls = microcosm_controls(
            _layer(1, engine=engine, hue=0.0, sat=0.8, val=1.0, bpm=120.0)
            | {"patch_col": 4}
        )
        weights = dict(zip(controls["pitch_ratios"], controls["pitch_weights"]))

        if 0.5 in weights and 2.0 in weights:
            assert weights[0.5] > weights[2.0]
        assert controls["octave_down_gain"] > 1.0


def test_microloop_pitch_ratios_and_weights_match_for_all_patch_columns():
    base = {"id": 1, "engine": "microloop", "hue": 0.0, "sat": 0.8, "val": 1.0, "bpm": 120.0}

    for col in range(5):
        controls = microcosm_controls({**base, "patch_col": col})
        assert len(controls["pitch_ratios"]) == len(controls["pitch_weights"])


def test_microloop_uses_octave_ratios_only():
    base = {"id": 1, "engine": "microloop", "hue": 0.0, "sat": 0.8, "val": 1.0, "bpm": 120.0}

    for col in range(5):
        controls = microcosm_controls({**base, "patch_col": col})
        assert set(controls["pitch_ratios"]).issubset({0.5, 1.0, 2.0, 4.0})


def test_glitch_controls_emphasize_octave_pitch_variation():
    layer = _layer(1, engine="glitch", hue=0.99, sat=0.8, val=1.0, bpm=120.0)
    controls = microcosm_controls(layer)

    assert controls["pitch_ratios"] == (0.5, 1.0, 2.0, 4.0)


def test_granules_use_longer_grain_windows_than_glitch():
    base = {"id": 1, "hue": 0.2, "sat": 0.85, "val": 1.0, "bpm": 100.0}
    granules = microcosm_controls({**base, "engine": "granules"})
    glitch = microcosm_controls({**base, "engine": "glitch"})

    assert granules["grain_seconds"] >= 0.18
    assert granules["grain_seconds"] > glitch["grain_seconds"] * 2.0


def test_manual_variant_names_are_available_by_family():
    assert FAMILY_VARIANTS == {
        "microloop": ("mosaic", "seq", "jump"),
        "granules": ("haze", "tunnel", "strum"),
        "glitch": ("blocks", "interrupt", "arp"),
        "multidelay": ("pattern", "warp"),
    }


@pytest.mark.parametrize(
    ("engine", "hues", "expected"),
    [
        ("microloop", (mod.FINGER_HUE_MIN, (mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2, mod.FINGER_HUE_MAX), ("mosaic", "seq", "jump")),
        ("granules", (mod.FINGER_HUE_MIN, (mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2, mod.FINGER_HUE_MAX), ("haze", "tunnel", "strum")),
        ("glitch", (mod.FINGER_HUE_MIN, (mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2, mod.FINGER_HUE_MAX), ("blocks", "interrupt", "arp")),
        ("multidelay", (mod.FINGER_HUE_MIN, mod.FINGER_HUE_MAX), ("pattern", "warp")),
    ],
)
def test_hue_selects_manual_variant_within_family(engine, hues, expected):
    selected = tuple(
        microcosm_variant(_layer(i + 1, engine=engine, hue=hue))
        for i, hue in enumerate(hues)
    )

    assert selected == expected


def test_patch_column_selects_manual_variant_before_hue():
    layer = _layer(1, engine="granules", hue=0.0)

    assert microcosm_variant({**layer, "patch_col": 0}) == "haze"
    assert microcosm_variant({**layer, "patch_col": 2}) == "tunnel"
    assert microcosm_variant({**layer, "patch_col": 4}) == "strum"


def test_microloop_patch_column_five_selects_jump_not_glide():
    layer = _layer(1, engine="microloop", hue=0.0)

    assert microcosm_variant({**layer, "patch_col": 4}) == "jump"


def test_microloop_jump_uses_discrete_octave_reads_not_ratio_glide():
    class SpyProcessor(MicrocosmProcessor):
        def __init__(self):
            super().__init__(SR, seed=1)
            self.ratio_reads = []
            self.curve_reads = 0

        def _read_ratio(self, loop, start, length, ratio):
            self.ratio_reads.append(ratio)
            return np.ones(length, dtype=np.float64) * 0.1

        def _read(self, loop, positions):
            self.curve_reads += 1
            return np.ones(len(positions), dtype=np.float64) * 0.1

    proc = SpyProcessor()
    voice = {"rng": np.random.default_rng(1), "buffer": np.zeros(SR * 3)}
    controls = microcosm_controls(
        _layer(1, engine="microloop", hue=0.99, sat=0.8, val=1.0, bpm=120.0)
        | {"patch_col": 4}
    )

    proc._emit_jump(voice, _tone(220.0), 0, 0, controls)

    assert proc.curve_reads == 0
    assert proc.ratio_reads
    assert set(proc.ratio_reads).issubset({0.5, 1.0, 2.0, 4.0})


def test_variants_within_family_have_distinct_source_rearrangements():
    loop = _tone(165.0, seconds=3.0) + 0.25 * _tone(330.0, seconds=3.0)
    families = {
        "microloop": (0.0, 0.5, 0.99),
        "granules": (0.0, 0.5, 0.99),
        "glitch": (0.0, 0.5, 0.99),
        "multidelay": (0.0, 0.99),
    }

    for engine, hues in families.items():
        rendered = []
        for i, hue in enumerate(hues):
            proc = MicrocosmProcessor(SR, seed=3)
            layer = _layer(i + 1, engine=engine, hue=hue, sat=0.8, bpm=95.0)
            rendered.append(
                np.concatenate(
                    [
                        proc.process(loop, 1024, [layer], source_pos=n * 1024)
                        for n in range(120)
                    ]
                )
            )

        for a, b in zip(rendered, rendered[1:]):
            assert not np.allclose(a, b)


def test_single_family_layers_are_audible_and_sustained_not_tiny_stutters():
    loop = _tone(165.0, seconds=3.0) + 0.25 * _tone(330.0, seconds=3.0)

    for i, engine in enumerate(("microloop", "granules", "glitch", "multidelay")):
        proc = MicrocosmProcessor(SR, seed=4)
        layer = _layer(i + 1, engine=engine, hue=0.66, sat=0.85, val=1.0, bpm=95.0)
        total = np.concatenate(
            [
                proc.process(loop, 1024, [layer], source_pos=n * 1024)
                for n in range(140)
            ]
        )
        win = int(0.05 * SR)
        env = np.array(
            [
                np.sqrt(np.mean(total[j * win:(j + 1) * win] ** 2))
                for j in range(len(total) // win)
            ]
        )
        active = env > max(1e-9, env.max() * 0.08)

        assert float(np.sqrt(np.mean(total**2))) > 0.035
        if engine == "granules":
            assert 0.55 < active.mean() < 0.98
        else:
            assert 0.22 < active.mean() < 0.75
        assert np.max(np.abs(total)) < 0.85


def test_many_layers_are_sparse_and_bounded():
    loop = _tone(220.0) + 0.2 * _tone(660.0)
    proc = MicrocosmProcessor(SR, seed=1)
    engines = ("microloop", "granules", "glitch", "multidelay")
    layers = [
        _layer(i + 1, engine=engines[i % len(engines)], hue=(i % 5) * 0.015, bpm=70 + 5 * i)
        for i in range(20)
    ]

    total = np.concatenate(
        [proc.process(loop, 1024, layers, source_pos=i * 1024) for i in range(160)]
    )
    win = int(0.05 * SR)
    n_win = len(total) // win
    env = np.array(
        [np.sqrt(np.mean(total[i * win:(i + 1) * win] ** 2)) for i in range(n_win)]
    )
    active = env > max(1e-9, env.max() * 0.08)

    assert active.mean() < 0.78
    assert float(np.sqrt(np.mean(total**2))) < 0.12
    assert np.max(np.abs(total)) < 0.8
