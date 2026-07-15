import numpy as np
import pytest

from spectral_processor import (
    N_PARTIALS,
    SpectralProcessor,
    analyze_frame,
    analyze_loop,
)

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
    layer = _layer(1, hue=0.03)  # half the gamut = +3.5 semitones
    for _ in range(20):
        out = proc.process(loop, 4096, [layer])
    expected = 440.0 * 2 ** (3.5 / 12)
    assert _dominant_freq(out) == pytest.approx(expected, abs=15.0)


def test_analyze_frame_finds_tone():
    window = _tone(440.0, seconds=4096 / SR)[:4096]
    freqs, amps = analyze_frame(window, SR)
    assert freqs.shape == (N_PARTIALS,)
    assert amps.shape == (N_PARTIALS,)
    strongest = freqs[np.argmax(amps)]
    assert strongest == pytest.approx(440.0, abs=SR / 4096 * 1.5)
    # amps are TRUE amplitudes (the tone is 0.5), not normalized to 1 --
    # normalizing made quiet output re-excite feedback at full level
    assert amps.max() == pytest.approx(0.5, abs=0.1)


def test_live_feedback_decays_without_fresh_input():
    """A voice fed analysis of its own output must fade, not run away."""
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    layer = _layer(1, hue=0.0, sat=0.0, val=1.0, bpm=300.0)

    # seed the voice with a strong external partial
    freqs = np.zeros(N_PARTIALS)
    amps = np.zeros(N_PARTIALS)
    freqs[0], amps[0] = 440.0, 0.8
    out = None
    for _ in range(5):
        out = proc.process(loop, 4096, [layer], live_frame=(freqs, amps))

    # then close the loop: each block only hears its own previous output
    rms = []
    for _ in range(40):
        live = analyze_frame(out, SR)
        out = proc.process(loop, 4096, [layer], live_frame=live)
        rms.append(float(np.sqrt(np.mean(out**2))))

    assert rms[-1] < rms[0] * 0.5
    assert max(rms) < 1.0


def test_analyze_frame_silent_window_is_flat():
    freqs, amps = analyze_frame(np.zeros(4096), SR)
    assert not np.any(np.isnan(freqs))
    assert not np.any(np.isnan(amps))
    np.testing.assert_allclose(amps, np.zeros(N_PARTIALS))


def test_live_frame_tracks_external_tone():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    # live frame says the output currently contains a 660 Hz partial
    live_freqs = np.zeros(N_PARTIALS)
    live_amps = np.zeros(N_PARTIALS)
    live_freqs[0] = 660.0
    live_amps[0] = 1.0
    layer = _layer(1, hue=0.0, sat=0.0, bpm=300.0)  # fast tracking, no blur
    for _ in range(30):
        out = proc.process(loop, 4096, [layer], live_frame=(live_freqs, live_amps))
    assert _dominant_freq(out) == pytest.approx(660.0, abs=15.0)


def test_stale_voices_are_dropped():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    proc.process(loop, 1024, [_layer(1), _layer(2)])
    assert set(proc._voices.keys()) == {1, 2}
    proc.process(loop, 1024, [_layer(2)])
    assert set(proc._voices.keys()) == {2}
