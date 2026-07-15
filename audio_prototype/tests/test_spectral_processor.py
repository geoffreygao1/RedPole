import numpy as np
import pytest

from spectral_processor import N_PARTIALS, SpectralProcessor, analyze_loop

SR = 44100


def _tone(freq, seconds=2.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_analyze_loop_shapes():
    loop = _tone(440.0)
    analysis = analyze_loop(loop, SR)
    n_frames = analysis["freqs"].shape[0]
    assert n_frames > 10
    assert analysis["freqs"].shape == (n_frames, N_PARTIALS)
    assert analysis["amps"].shape == (n_frames, N_PARTIALS)
    assert analysis["frame_rate"] == pytest.approx(SR / 1024)


def test_analyze_loop_finds_test_tone():
    loop = _tone(440.0)
    analysis = analyze_loop(loop, SR)
    # strongest partial of a mid frame should be ~440 Hz
    mid = analysis["freqs"].shape[0] // 2
    strongest = analysis["freqs"][mid][np.argmax(analysis["amps"][mid])]
    assert strongest == pytest.approx(440.0, abs=SR / 4096 * 1.5)


def test_analyze_loop_amps_normalized():
    loop = _tone(440.0)
    analysis = analyze_loop(loop, SR)
    assert analysis["amps"].max() == pytest.approx(1.0)


def test_analyze_loop_handles_short_input():
    loop = _tone(440.0, seconds=0.05)  # shorter than one FFT window
    analysis = analyze_loop(loop, SR)
    assert analysis["freqs"].shape[0] >= 1
