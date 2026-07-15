import numpy as np

from reverb import SchroederReverb

SR = 44100


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
