import numpy as np

from soundscape_conductor import VoiceConductor
from soundscape_density import ROLE_GAIN


def test_gains_are_bounded_and_present_for_active_ids():
    c = VoiceConductor(samplerate=44100, seed=1)
    gains = c.update([1, 2, 3], 1024)
    assert set(gains) == {1, 2, 3}
    hi = max(ROLE_GAIN.values())
    for g in gains.values():
        assert 0.0 <= g <= hi + 1e-9


def test_state_is_garbage_collected_for_absent_ids():
    c = VoiceConductor(samplerate=44100, seed=1)
    c.update([1, 2], 1024)
    gains = c.update([2], 1024)
    assert set(gains) == {2}
    assert 1 not in c._gain


def test_gains_evolve_over_time():
    c = VoiceConductor(samplerate=44100, seed=1)
    first = c.update([1, 2, 3, 4, 5, 6, 7, 8], 1024)[1]
    last = first
    biggest_move = 0.0
    for _ in range(2000):                     # ~46 s at 1024/44100 per block
        last = c.update([1, 2, 3, 4, 5, 6, 7, 8], 1024)[1]
        biggest_move = max(biggest_move, abs(last - first))
    assert biggest_move > 0.05                # the voice's gain has clearly moved


def test_per_block_gain_change_is_smoothed():
    c = VoiceConductor(samplerate=44100, seed=1)
    ids = list(range(1, 13))
    prev = c.update(ids, 1024)
    for _ in range(500):
        cur = c.update(ids, 1024)
        for vid in ids:
            assert abs(cur[vid] - prev[vid]) < 0.1   # no click-inducing jumps
        prev = cur


def test_deterministic_under_seed():
    a = VoiceConductor(samplerate=44100, seed=7)
    b = VoiceConductor(samplerate=44100, seed=7)
    for _ in range(50):
        assert a.update([1, 2, 3], 1024) == b.update([1, 2, 3], 1024)
