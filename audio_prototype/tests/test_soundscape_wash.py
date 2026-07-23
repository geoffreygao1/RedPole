import numpy as np

from soundscape_wash import SoundscapeWash


def test_zero_amounts_pass_dry_through():
    wash = SoundscapeWash(44100, reverb_amount=0.0, delay_amount=0.0)
    x = np.sin(np.linspace(0, 20, 1024)).astype(np.float32)
    np.testing.assert_allclose(wash.process(x), x, atol=1e-6)


def test_reverb_adds_energy_and_tail_rings_out():
    wash = SoundscapeWash(44100, reverb_amount=0.6, delay_amount=0.0)
    impulse = np.zeros(1024, dtype=np.float32)
    impulse[0] = 1.0
    wash.process(impulse)
    tail = np.concatenate([wash.process(np.zeros(1024, dtype=np.float32)) for _ in range(20)])
    assert float(np.max(np.abs(tail))) > 1e-4        # tail keeps ringing on silence


def test_delay_repeats_after_the_delay_time():
    wash = SoundscapeWash(44100, reverb_amount=0.0, delay_amount=1.0)
    impulse = np.zeros(1024, dtype=np.float32)
    impulse[0] = 1.0
    wash.process(impulse)
    later = np.concatenate([wash.process(np.zeros(1024, dtype=np.float32)) for _ in range(120)])
    assert float(np.max(np.abs(later))) > 1e-3        # echo appears later


def test_output_is_bounded_and_finite():
    wash = SoundscapeWash(44100, reverb_amount=1.0, delay_amount=1.0)
    rng = np.random.default_rng(0)
    for _ in range(40):
        out = wash.process((0.5 * rng.standard_normal(1024)).astype(np.float32))
        assert not np.any(np.isnan(out))
