import numpy as np

from synth_source import SeedBank, WAVETABLE_LEN, DEFAULT_SEED_COUNT


def test_seed_bank_is_deterministic_and_shaped():
    a = SeedBank(seed=7)
    b = SeedBank(seed=7)
    assert len(a) == DEFAULT_SEED_COUNT
    for i in range(len(a)):
        assert a.table(i).shape == (WAVETABLE_LEN,)
        assert a.table(i).dtype == np.float64
        assert np.max(np.abs(a.table(i))) <= 1.0 + 1e-9
        np.testing.assert_array_equal(a.table(i), b.table(i))


def test_seed_bank_index_wraps():
    bank = SeedBank(seed=1)
    np.testing.assert_array_equal(bank.table(0), bank.table(len(bank)))


def test_higher_seeds_are_brighter():
    # brightness ~ high-frequency energy; compare the top half of the rFFT
    bank = SeedBank(seed=3)

    def hf_ratio(tbl):
        mag = np.abs(np.fft.rfft(tbl))
        return float(np.sum(mag[len(mag) // 2:]) / (np.sum(mag) + 1e-12))

    assert hf_ratio(bank.table(len(bank) - 1)) > hf_ratio(bank.table(0))
