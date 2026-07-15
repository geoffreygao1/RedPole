import numpy as np

from granular_processor import GranularProcessor

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


def test_bursts_follow_heartbeat_period():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    layer = _layer(1, bpm=120, sat=0.0)  # short grains, pulse every 0.5s
    seconds = 3.0
    total = np.concatenate(
        [proc.process(loop, 1024, [layer])
         for _ in range(int(seconds * SR / 1024) + 1)]
    )
    # energy envelope in 50ms windows: bursts every ~0.5s -> at least 5
    # distinct peaks separated by quiet gaps in 3 seconds
    win = int(0.05 * SR)
    n_win = len(total) // win
    env = np.array([np.abs(total[i * win:(i + 1) * win]).max() for i in range(n_win)])
    threshold = env.max() * 0.2
    loud = env > threshold
    onsets = np.sum(loud[1:] & ~loud[:-1])
    assert onsets >= 4


def test_stale_voices_are_dropped():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    proc.process(loop, 1024, [_layer(1), _layer(2)])
    assert set(proc._voices.keys()) == {1, 2}
    proc.process(loop, 1024, [_layer(2)])
    assert set(proc._voices.keys()) == {2}


def test_output_length_and_state_persist():
    proc = GranularProcessor(SR, seed=1)
    loop = _tone(220.0)
    a = proc.process(loop, 700, [_layer(1)])
    b = proc.process(loop, 700, [_layer(1)])
    assert a.shape == (700,)
    assert b.shape == (700,)
