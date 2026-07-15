import numpy as np

import modulation as mod
from frequency_mod_processor import FrequencyModProcessor, fm_layer_controls

SR = 44100


def _tone(freq, seconds=2.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _layer(layer_id, hue=0.0, sat=0.5, val=1.0, bpm=120.0):
    return {"id": layer_id, "hue": hue, "sat": sat, "val": val, "bpm": bpm}


def test_no_layers_is_silent():
    proc = FrequencyModProcessor(SR, seed=1)
    out = proc.process(_tone(220.0), 1024, [])
    np.testing.assert_allclose(out, np.zeros(1024))
    assert out.dtype == np.float32


def test_silent_source_stays_silent():
    proc = FrequencyModProcessor(SR, seed=1)
    out = proc.process(np.zeros(SR, dtype=np.float32), 4096, [_layer(1)])
    np.testing.assert_allclose(out, np.zeros(4096), atol=1e-7)


def test_layer_adds_source_derived_frequency_color():
    loop = _tone(220.0) + 0.25 * _tone(440.0)
    proc = FrequencyModProcessor(SR, seed=1)

    out = proc.process(
        loop,
        4096,
        [_layer(1, hue=mod.FINGER_HUE_MAX, sat=mod.FINGER_SAT_MAX, val=mod.FINGER_VAL_MAX)],
    )

    assert float(np.sqrt(np.mean(out**2))) > 0.001
    assert np.max(np.abs(out)) < 0.5


def test_bpm_changes_fm_motion_rate():
    slow = fm_layer_controls(_layer(1, bpm=45.0))
    fast = fm_layer_controls(_layer(1, bpm=180.0))

    assert fast["rate_hz"] > slow["rate_hz"]


def test_many_layers_stay_bounded_but_more_complex():
    loop = _tone(220.0) + 0.2 * _tone(660.0)
    sparse = FrequencyModProcessor(SR, seed=1)
    dense = FrequencyModProcessor(SR, seed=1)

    sparse_out = sparse.process(loop, 8192, [_layer(1, hue=0.0, bpm=90.0)])
    layers = [
        _layer(
            i + 1,
            hue=mod.FINGER_HUE_MIN + (mod.FINGER_HUE_MAX - mod.FINGER_HUE_MIN) * ((i % 5) / 4),
            sat=mod.FINGER_SAT_MIN + (mod.FINGER_SAT_MAX - mod.FINGER_SAT_MIN) * ((i % 4) / 3),
            val=mod.FINGER_VAL_MAX,
            bpm=60 + 9 * i,
        )
        for i in range(12)
    ]
    dense_out = dense.process(loop, 8192, layers)

    def active_bins(x):
        mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        return int(np.count_nonzero(mag > mag.max() * 0.03))

    assert np.max(np.abs(dense_out)) < 0.7
    assert active_bins(dense_out) > active_bins(sparse_out)


def test_many_layers_are_sparse_not_continuous():
    loop = _tone(220.0) + 0.2 * _tone(660.0)
    proc = FrequencyModProcessor(SR, seed=1)
    layers = [
        _layer(
            i + 1,
            hue=mod.FINGER_HUE_MIN + (mod.FINGER_HUE_MAX - mod.FINGER_HUE_MIN) * ((i % 5) / 4),
            sat=(mod.FINGER_SAT_MIN + mod.FINGER_SAT_MAX) / 2,
            val=mod.FINGER_VAL_MAX,
            bpm=75 + 7 * i,
        )
        for i in range(16)
    ]

    total = np.concatenate(
        [proc.process(loop, 1024, layers, scan_start=i) for i in range(160)]
    )
    win = int(0.05 * SR)
    n_win = len(total) // win
    env = np.array(
        [np.sqrt(np.mean(total[i * win:(i + 1) * win] ** 2)) for i in range(n_win)]
    )
    active = env > max(1e-9, env.max() * 0.08)

    assert active.mean() < 0.7
    assert float(np.sqrt(np.mean(total**2))) < 0.08


def test_fm_output_has_no_large_sample_jumps():
    loop = _tone(220.0) + 0.2 * _tone(660.0)
    proc = FrequencyModProcessor(SR, seed=1)
    layers = [_layer(1, hue=0.06, sat=1.0, val=1.0, bpm=180.0)]

    out = np.concatenate(
        [proc.process(loop, 1024, layers, scan_start=i) for i in range(40)]
    )

    assert np.max(np.abs(np.diff(out))) < 0.25
