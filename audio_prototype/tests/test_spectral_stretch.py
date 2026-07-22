import numpy as np

from spectral_stretch import SpectralSmear, FFT_SIZE, HOP

SR = 44100


def _sine(freq, n, sr=SR):
    return (0.5 * np.sin(2 * np.pi * freq * np.arange(n) / sr)).astype(np.float64)


def test_process_returns_same_length_each_block():
    smear = SpectralSmear(SR, seed=1)
    for _ in range(20):
        out = smear.process(_sine(220.0, 512))
        assert out.shape == (512,)
        assert out.dtype == np.float32


def test_identity_passthrough_when_no_suspension_or_smear():
    # feed a steady sine; after priming, output should track the input
    # (delayed), since sqrt-Hann @ 75% overlap reconstructs unity gain and
    # phase is untouched at smear=0.
    smear = SpectralSmear(SR, seed=1)
    x = _sine(220.0, FFT_SIZE * 8)
    out = np.concatenate(
        [
            smear.process(x[i : i + 512], suspension=0.0, smear=0.0)
            for i in range(0, len(x), 512)
        ]
    )
    # compare steady-state region, allowing for the FFT_SIZE priming latency
    a = out[FFT_SIZE * 2 : FFT_SIZE * 6].astype(np.float64)
    b = x[FFT_SIZE * 2 - FFT_SIZE : FFT_SIZE * 6 - FFT_SIZE]
    corr = np.corrcoef(a, b)[0, 1]
    assert corr > 0.95


def test_smear_randomizes_phase_but_bounds_energy():
    smear = SpectralSmear(SR, seed=1)
    x = _sine(220.0, FFT_SIZE * 8)
    out = np.concatenate(
        [
            smear.process(x[i : i + 512], suspension=0.8, smear=1.0)
            for i in range(0, len(x), 512)
        ]
    )
    steady = out[FFT_SIZE * 2 :]
    assert np.max(np.abs(steady)) < 2.0
    assert float(np.sqrt(np.mean(steady ** 2))) > 0.01
    assert not np.any(np.isnan(out))


def test_deterministic_given_seed():
    a = SpectralSmear(SR, seed=9)
    b = SpectralSmear(SR, seed=9)
    x = _sine(330.0, 4096)
    oa = a.process(x, suspension=0.5, smear=1.0)
    ob = b.process(x, suspension=0.5, smear=1.0)
    np.testing.assert_array_equal(oa, ob)
