import numpy as np
import pytest

import modulation as mod
from spectral_processor import (
    HOP_SIZE,
    N_PARTIALS,
    SpectralProcessor,
    analyze_frame,
    analyze_loop,
    apply_spectral_focus,
    source_amplitude_envelope,
    spectral_focus_controls,
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


def test_hue_controls_spectral_focus_relative_to_source():
    freqs = np.array([120.0, 240.0, 480.0, 960.0, 1920.0])
    amps = np.ones_like(freqs)

    low = spectral_focus_controls(freqs, amps, _layer(1, hue=mod.FINGER_HUE_MIN))
    center = spectral_focus_controls(
        freqs,
        amps,
        _layer(1, hue=(mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2),
    )
    high = spectral_focus_controls(freqs, amps, _layer(1, hue=mod.FINGER_HUE_MAX))

    assert low["focus_hz"] < center["focus_hz"]
    assert high["focus_hz"] > center["focus_hz"]
    assert center["focus_hz"] == pytest.approx(480.0, rel=0.05)


def test_saturation_controls_spectral_bandwidth():
    freqs = np.array([120.0, 240.0, 480.0, 960.0, 1920.0])
    amps = np.ones_like(freqs)
    wide = apply_spectral_focus(
        freqs,
        amps,
        _layer(1, hue=(mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2, sat=mod.FINGER_SAT_MIN, val=mod.FINGER_VAL_MAX),
    )
    narrow = apply_spectral_focus(
        freqs,
        amps,
        _layer(1, hue=(mod.FINGER_HUE_MIN + mod.FINGER_HUE_MAX) / 2, sat=mod.FINGER_SAT_MAX, val=mod.FINGER_VAL_MAX),
    )

    wide_ratio = wide[2] / wide[0]
    narrow_ratio = narrow[2] / narrow[0]
    assert narrow_ratio > wide_ratio


def test_value_controls_spectral_density():
    freqs = np.linspace(120.0, 3000.0, N_PARTIALS)
    amps = np.ones(N_PARTIALS)
    sparse = apply_spectral_focus(freqs, amps, _layer(1, val=mod.FINGER_VAL_MIN))
    full = apply_spectral_focus(freqs, amps, _layer(1, val=mod.FINGER_VAL_MAX))

    assert np.count_nonzero(sparse) < np.count_nonzero(full)
    assert np.count_nonzero(sparse) >= 2


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


def test_new_voice_can_start_at_current_source_frame():
    loop = _tone(440.0)
    analysis = {
        "freqs": np.zeros((8, N_PARTIALS)),
        "amps": np.zeros((8, N_PARTIALS)),
        "frame_rate": SR / HOP_SIZE,
    }
    analysis["freqs"][0, 0] = 220.0
    analysis["amps"][0, 0] = 1.0
    analysis["freqs"][5, 0] = 660.0
    analysis["amps"][5, 0] = 1.0

    proc = SpectralProcessor(SR)
    proc.set_analysis(analysis)
    out = proc.process(loop, 4096, [_layer(1, hue=0.0)], scan_start=5.0)

    assert _dominant_freq(out) == pytest.approx(660.0, abs=15.0)


def test_precomputed_scan_advances_with_source_not_bpm():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    proc.set_analysis(analyze_loop(loop, SR))
    layer = _layer(1, hue=0.0, bpm=40.0)

    proc.process(loop, HOP_SIZE, [layer], scan_start=10.0)
    first_scan = proc._voices[1]["scan"]
    proc.process(loop, HOP_SIZE, [layer], scan_start=11.0)
    second_scan = proc._voices[1]["scan"]

    assert first_scan == pytest.approx(11.0)
    assert second_scan == pytest.approx(12.0)


def test_spectral_output_follows_source_amplitude_inside_block():
    t = np.arange(4096) / SR
    loop = (0.8 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    loop[2048:] = 0.0
    analysis = {
        "freqs": np.zeros((1, N_PARTIALS)),
        "amps": np.zeros((1, N_PARTIALS)),
        "frame_rate": SR / HOP_SIZE,
    }
    analysis["freqs"][0, 0] = 440.0
    analysis["amps"][0, 0] = 1.0

    proc = SpectralProcessor(SR)
    proc.set_analysis(analysis)
    out = proc.process(loop, 4096, [_layer(1, hue=0.0, sat=0.0)], scan_start=0.0)

    early = float(np.sqrt(np.mean(out[512:1536] ** 2)))
    late = float(np.sqrt(np.mean(out[3072:] ** 2)))
    assert late < early * 0.35


def test_missing_spectral_partials_decay_quickly():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR)
    analysis = {
        "freqs": np.zeros((2, N_PARTIALS)),
        "amps": np.zeros((2, N_PARTIALS)),
        "frame_rate": SR / HOP_SIZE,
    }
    analysis["freqs"][0, 0] = 440.0
    analysis["amps"][0, 0] = 1.0
    proc.set_analysis(analysis)
    layer = _layer(1, hue=0.0, sat=1.0, val=1.0)

    proc.process(loop, HOP_SIZE, [layer], scan_start=0.0)
    active_amp = proc._voices[1]["amps"][0]
    proc.process(loop, HOP_SIZE, [layer], scan_start=1.0)
    missing_amp = proc._voices[1]["amps"][0]

    assert missing_amp < active_amp * 0.5


def test_dense_spectral_frame_stays_below_full_scale():
    loop = _tone(220.0, seconds=4096 / SR)
    analysis = {
        "freqs": np.zeros((1, N_PARTIALS)),
        "amps": np.ones((1, N_PARTIALS)),
        "frame_rate": SR / HOP_SIZE,
    }
    analysis["freqs"][0] = np.linspace(180.0, 4200.0, N_PARTIALS)

    proc = SpectralProcessor(SR)
    proc.set_analysis(analysis)
    out = proc.process(
        loop,
        4096,
        [_layer(1, hue=0.0, sat=0.0, val=1.0)],
        scan_start=0.0,
    )

    assert np.max(np.abs(out)) < 0.9


def test_spectral_partial_changes_are_ramped_across_block_boundary():
    loop = _tone(440.0)
    analysis = {
        "freqs": np.zeros((2, N_PARTIALS)),
        "amps": np.zeros((2, N_PARTIALS)),
        "frame_rate": SR / HOP_SIZE,
    }
    analysis["freqs"][:, 0] = 440.0
    analysis["amps"][0, 0] = 1.0
    analysis["amps"][1, 0] = 0.05

    proc = SpectralProcessor(SR)
    proc.set_analysis(analysis)
    layer = _layer(1, hue=0.0, sat=1.0, val=1.0)
    first = proc.process(loop, HOP_SIZE, [layer], scan_start=0.0)
    second = proc.process(loop, HOP_SIZE, [layer], scan_start=1.0)

    boundary = np.r_[first[-1], second[:64]]
    assert np.max(np.abs(np.diff(boundary))) < 0.08


def test_spectral_output_declicks_large_phase_boundary():
    loop = _tone(440.0)
    analysis = {
        "freqs": np.zeros((2, N_PARTIALS)),
        "amps": np.zeros((2, N_PARTIALS)),
        "frame_rate": SR / HOP_SIZE,
    }
    analysis["freqs"][0, 0] = 220.0
    analysis["amps"][0, 0] = 1.0
    analysis["freqs"][1, 0] = 1800.0
    analysis["amps"][1, 0] = 1.0

    proc = SpectralProcessor(SR, seed=1)
    proc.set_analysis(analysis)
    layer = _layer(1, hue=0.0, sat=0.0, val=1.0)
    first = proc.process(loop, HOP_SIZE, [layer], scan_start=0.0)
    second = proc.process(loop, HOP_SIZE, [layer], scan_start=1.0)

    boundary = np.r_[first[-1], second[:32]]
    assert np.max(np.abs(np.diff(boundary))) < 0.04


def test_spectral_haze_is_not_cycle_static():
    loop = _tone(440.0)
    proc = SpectralProcessor(SR, seed=1)
    proc.set_analysis(analyze_loop(loop, SR))
    layer = _layer(1, hue=0.0, sat=0.5, val=1.0)

    for _ in range(20):
        out = proc.process(loop, 4096, [layer])

    period = round(SR / 440.0)
    a = out[1000:1000 + period]
    b = out[1000 + period:1000 + 2 * period]
    corr = np.corrcoef(a, b)[0, 1]

    assert corr < 0.995


def test_source_amplitude_envelope_uses_loop_scale_not_block_peak():
    t = np.arange(4096) / SR
    loop = (0.8 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    loop[2048:] *= 0.1

    loud = source_amplitude_envelope(loop, 512, 512)
    quiet = source_amplitude_envelope(loop, 2560, 512)

    assert float(np.mean(quiet)) < float(np.mean(loud)) * 0.2
