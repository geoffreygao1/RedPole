import numpy as np
import pytest

import modulation as mod
from granular_processor import (
    GranularProcessor,
    granular_focus_controls,
    granular_octave_ratio,
    granular_pitch_weights,
    granular_pitch_ratios,
)

SR = 44100


def _tone(freq, seconds=2.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _layer(layer_id, hue=0.0, sat=0.5, val=1.0, bpm=120.0):
    return {"id": layer_id, "hue": hue, "sat": sat, "val": val, "bpm": bpm}


def test_no_layers_is_silent():
    proc = GranularProcessor(SR, seed=1)
    out = proc.process(_tone(220.0), 1024, [])
    np.testing.assert_allclose(out, np.zeros(1024))
    assert out.dtype == np.float32


def test_layer_produces_grains():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    total = np.concatenate(
        [proc.process(loop, 1024, [_layer(1, bpm=120)]) for _ in range(50)]
    )
    assert np.max(np.abs(total)) > 0.01


def test_grain_cloud_avoids_heartbeat_sized_quiet_gaps():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    layer = _layer(1, bpm=120, sat=0.0, val=1.0)
    seconds = 3.0
    total = np.concatenate(
        [
            proc.process(loop, 1024, [layer], source_pos=i * 1024)
            for i in range(int(seconds * SR / 1024) + 1)
        ]
    )
    # The cloud should not collapse into delay-like half-second taps with
    # long gaps between them. Most 50 ms windows should carry some energy.
    win = int(0.05 * SR)
    n_win = len(total) // win
    env = np.array(
        [np.abs(total[i * win:(i + 1) * win]).max() for i in range(n_win)]
    )
    active = env > env.max() * 0.05
    assert active.mean() > 0.45
    assert active.mean() < 0.95


def test_grain_cloud_breathes_with_many_layers():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0) + 0.2 * _tone(660.0)
    layers = [
        _layer(i + 1, hue=(i % 5) * 0.015, sat=0.35 + 0.1 * (i % 4), bpm=60 + 9 * i)
        for i in range(12)
    ]
    total = np.concatenate(
        [
            proc.process(loop, 1024, layers, source_pos=i * 1024)
            for i in range(int(4.0 * SR / 1024) + 1)
        ]
    )

    win = int(0.05 * SR)
    n_win = len(total) // win
    env = np.array(
        [np.sqrt(np.mean(total[i * win:(i + 1) * win] ** 2)) for i in range(n_win)]
    )
    active = env > max(1e-9, env.max() * 0.08)
    assert active.mean() < 0.82


def test_grain_events_use_jittered_intervals():
    class RecordingGranularProcessor(GranularProcessor):
        def __init__(self, samplerate, seed=None):
            super().__init__(samplerate, seed=seed)
            self.offsets = []

        def _emit_grain(
            self, voice, loop_array, offset, grain_len, ratio, level, source_pos, controls
        ):
            self.offsets.append(source_pos)

    proc = RecordingGranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    layer = _layer(1, bpm=120, sat=0.5, val=1.0)

    for i in range(120):
        proc.process(loop, 1024, [layer], source_pos=i * 1024)

    intervals = np.diff(proc.offsets[:12])
    assert len(intervals) > 6
    assert np.std(intervals) > SR * 0.01


def test_stale_voices_are_dropped():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    proc.process(loop, 1024, [_layer(1), _layer(2)])
    assert set(proc._voices.keys()) == {1, 2}
    proc.process(loop, 1024, [_layer(2)])
    assert set(proc._voices.keys()) == {2}


def _dominant_freq(signal, sr=SR):
    mag = np.abs(np.fft.rfft(signal * np.hanning(len(signal))))
    return np.fft.rfftfreq(len(signal), 1.0 / sr)[np.argmax(mag)]


def test_hue_does_not_shift_grain_pitch_center():
    assert granular_octave_ratio(_layer(1, hue=mod.FINGER_HUE_MIN)) == pytest.approx(1.0)
    assert granular_octave_ratio(_layer(1, hue=(mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2)) == pytest.approx(1.0)
    assert granular_octave_ratio(_layer(1, hue=mod.FINGER_HUE_MAX)) == pytest.approx(1.0)


def test_granular_pitch_ratios_are_unison_only():
    assert granular_pitch_ratios(_layer(1, hue=mod.FINGER_HUE_MIN)) == pytest.approx((1.0,))
    assert granular_pitch_ratios(_layer(1, hue=(mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2)) == pytest.approx((1.0,))
    assert granular_pitch_ratios(_layer(1, hue=mod.FINGER_HUE_MAX)) == pytest.approx((1.0,))


def test_granular_pitch_weights_use_only_unison():
    low = dict(zip(granular_pitch_ratios(_layer(1, hue=mod.FINGER_HUE_MIN)), granular_pitch_weights(_layer(1, hue=mod.FINGER_HUE_MIN))))
    center_hue = (mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2
    center = dict(zip(granular_pitch_ratios(_layer(1, hue=center_hue)), granular_pitch_weights(_layer(1, hue=center_hue))))
    high = dict(zip(granular_pitch_ratios(_layer(1, hue=mod.FINGER_HUE_MAX)), granular_pitch_weights(_layer(1, hue=mod.FINGER_HUE_MAX))))

    assert low == {1.0: 1.0}
    assert center == {1.0: 1.0}
    assert high == {1.0: 1.0}


def test_granular_events_do_not_repitch():
    class RecordingGranularProcessor(GranularProcessor):
        def __init__(self, samplerate, seed=None):
            super().__init__(samplerate, seed=seed)
            self.ratios = []

        def _emit_grain(
            self, voice, loop_array, offset, grain_len, ratio, level, source_pos, controls
        ):
            self.ratios.append(ratio)

    proc = RecordingGranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    layer = _layer(1, hue=mod.FINGER_HUE_MAX)
    for i in range(30):
        proc.process(loop, 1024, [layer], source_pos=i * 1024)

    assert set(proc.ratios) == {1.0}


def test_output_length_and_state_persist():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    a = proc.process(loop, 700, [_layer(1)])
    b = proc.process(loop, 700, [_layer(1)])
    assert a.shape == (700,)
    assert b.shape == (700,)


def test_grains_are_anchored_to_source_position():
    loop = np.zeros(SR, dtype=np.float32)
    source_pos = 12000
    loop[source_pos] = 1.0
    proc = GranularProcessor(SR, seed=1)

    anchored = proc.process(
        loop,
        4096,
        [_layer(1, hue=0.0, sat=0.0, val=1.0, bpm=300.0)],
        source_pos=source_pos,
    )

    assert np.max(np.abs(anchored)) > 0.01


def test_hue_controls_granular_source_focus():
    low = granular_focus_controls(_layer(1, hue=mod.FINGER_HUE_MIN, sat=0.5, bpm=120.0))
    center = granular_focus_controls(_layer(1, hue=(mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2, sat=0.5, bpm=120.0))
    high = granular_focus_controls(_layer(1, hue=mod.FINGER_HUE_MAX, sat=0.5, bpm=120.0))

    assert low["centroid_target"] < center["centroid_target"]
    assert high["centroid_target"] > center["centroid_target"]


def test_saturation_controls_granular_source_bandwidth():
    wide = granular_focus_controls(_layer(1, sat=0.0, bpm=120.0))
    narrow = granular_focus_controls(_layer(1, sat=1.0, bpm=120.0))

    assert narrow["search_radius"] < wide["search_radius"]


def test_bpm_controls_granular_motion_not_heartbeat_period():
    slow = granular_focus_controls(_layer(1, sat=0.5, bpm=40.0))
    fast = granular_focus_controls(_layer(1, sat=0.5, bpm=180.0))

    assert slow["source_smear"] > fast["source_smear"]
    assert slow["grain_interval"] == fast["grain_interval"]


def test_value_controls_grain_spacing_over_wider_range():
    quiet = granular_focus_controls(_layer(1, val=0.2))
    bright = granular_focus_controls(_layer(1, val=1.0))

    assert quiet["grain_interval"] > bright["grain_interval"]
    assert bright["grain_interval"] >= 0.18
    assert quiet["grain_interval"] >= 0.34
