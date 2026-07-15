import numpy as np

from reverb import OnePoleLowpass, SchroederReverb

SR = 44100


def _tone(freq, n=8192, sr=SR):
    return np.sin(2 * np.pi * freq * np.arange(n) / sr)


def test_lowpass_attenuates_highs_more_than_lows():
    lp_low = OnePoleLowpass(SR, cutoff_hz=1000.0)
    lp_high = OnePoleLowpass(SR, cutoff_hz=1000.0)
    low_out = lp_low.process(_tone(100.0))
    high_out = lp_high.process(_tone(8000.0))
    # skip the settle-in region
    assert np.abs(high_out[4000:]).max() < np.abs(low_out[4000:]).max() * 0.5


def test_lowpass_cutoff_is_adjustable():
    lp = OnePoleLowpass(SR, cutoff_hz=500.0)
    dark = lp.process(_tone(4000.0))
    lp2 = OnePoleLowpass(SR, cutoff_hz=8000.0)
    bright = lp2.process(_tone(4000.0))
    assert np.abs(dark[4000:]).max() < np.abs(bright[4000:]).max()


def test_reverb_feedback_and_cutoff_setters():
    rv = SchroederReverb(SR)
    rv.set_feedback(0.9)
    assert all(c.feedback == 0.9 for c in rv._combs)
    rv.set_cutoff(1200.0)
    assert rv._lowpass.cutoff_hz == 1200.0


def test_lower_feedback_decays_faster():
    def tail_energy(feedback):
        rv = SchroederReverb(SR)
        rv.set_feedback(feedback)
        impulse = np.zeros(1024, dtype=np.float32)
        impulse[0] = 1.0
        rv.process(impulse)
        silent = np.zeros(1024, dtype=np.float32)
        return sum(
            float(np.sum(rv.process(silent) ** 2)) for _ in range(40)
        )

    assert tail_energy(0.72) < tail_energy(0.92) * 0.5


def test_silence_in_silence_out_from_clean_state():
    rv = SchroederReverb(SR)
    out = rv.process(np.zeros(1024, dtype=np.float32))
    np.testing.assert_allclose(out, np.zeros(1024))
    assert out.dtype == np.float32


def test_output_length_matches_input():
    rv = SchroederReverb(SR)
    assert rv.process(np.zeros(300, dtype=np.float32)).shape == (300,)
    assert rv.process(np.zeros(5000, dtype=np.float32)).shape == (5000,)


def test_impulse_produces_decaying_tail():
    rv = SchroederReverb(SR)
    impulse = np.zeros(1024, dtype=np.float32)
    impulse[0] = 1.0
    rv.process(impulse)

    silent = np.zeros(1024, dtype=np.float32)
    # tail energy per block over the next ~1.4 seconds
    energies = []
    for _ in range(60):
        out = rv.process(silent)
        energies.append(float(np.sum(out**2)))

    # tail exists well past 0.5s (block 22 is ~0.51-0.53s after impulse)
    assert energies[22] > 0.0
    # and decays: late tail is much quieter than early tail
    early = sum(energies[:10])
    late = sum(energies[50:60])
    assert late < early * 0.5
    assert early > 0.0


def test_state_persists_across_odd_block_sizes():
    rv = SchroederReverb(SR)
    impulse = np.zeros(300, dtype=np.float32)
    impulse[0] = 1.0
    rv.process(impulse)
    total = np.concatenate([rv.process(np.zeros(300, dtype=np.float32)) for _ in range(300)])
    assert np.max(np.abs(total)) > 0.0
