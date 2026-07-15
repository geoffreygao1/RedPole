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


def _layer(layer_id, hue=0.0, sat=0.5, val=1.0, bpm=120.0):
    return {"id": layer_id, "hue": hue, "sat": sat, "val": val, "bpm": bpm}


def _dominant_freq(signal, sr=SR):
    mag = np.abs(np.fft.rfft(signal * np.hanning(len(signal))))
    return np.fft.rfftfreq(len(signal), 1.0 / sr)[np.argmax(mag)]


def test_process_no_layers_is_silent():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    out = proc.process(loop, 1024, [])
    np.testing.assert_allclose(out, np.zeros(1024))


def test_process_without_analysis_is_silent():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(None)
    out = proc.process(loop, 1024, [_layer(1)])
    np.testing.assert_allclose(out, np.zeros(1024))


def test_voice_reproduces_tone_pitch():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    layer = _layer(1, hue=0.0)  # red center = no pitch shift
    # run a few blocks so blur settles, then measure
    for _ in range(20):
        out = proc.process(loop, 4096, [layer])
    assert _dominant_freq(out) == pytest.approx(440.0, abs=15.0)


def test_hue_shifts_pitch_up():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    layer = _layer(1, hue=0.25)  # +3.5 semitones
    for _ in range(20):
        out = proc.process(loop, 4096, [layer])
    expected = 440.0 * 2 ** (3.5 / 12)
    assert _dominant_freq(out) == pytest.approx(expected, abs=15.0)


def test_stale_voices_are_dropped():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    proc.process(loop, 1024, [_layer(1), _layer(2)])
    assert set(proc._voices.keys()) == {1, 2}
    proc.process(loop, 1024, [_layer(2)])
    assert set(proc._voices.keys()) == {2}
