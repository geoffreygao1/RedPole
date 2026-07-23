import numpy as np
import soundfile as sf

from audio_io import read_mono_audio, resample_linear


def test_resample_linear_is_identity_when_rates_match():
    data = np.linspace(-1.0, 1.0, 100, dtype=np.float32)
    out = resample_linear(data, 44100, 44100)
    np.testing.assert_array_equal(out, data)


def test_resample_linear_changes_length_on_rate_change():
    data = np.zeros(1000, dtype=np.float32)
    out = resample_linear(data, 44100, 22050)
    assert abs(len(out) - 500) <= 1
    assert out.dtype == np.float32


def test_read_mono_audio_downmixes_stereo(tmp_path):
    path = tmp_path / "stereo.wav"
    stereo = np.stack([
        np.ones(2048, dtype=np.float32),
        -np.ones(2048, dtype=np.float32),
    ], axis=1)
    sf.write(str(path), stereo, 44100)
    mono, rate = read_mono_audio(str(path))
    assert rate == 44100
    assert mono.ndim == 1
    assert mono.dtype == np.float32
    # +1 and -1 average to ~0
    assert float(np.max(np.abs(mono))) < 1e-3


def test_read_mono_audio_respects_max_seconds(tmp_path):
    path = tmp_path / "long.wav"
    sf.write(str(path), np.zeros(44100 * 3, dtype=np.float32), 44100)
    mono, _rate = read_mono_audio(str(path), max_seconds=1.0)
    assert len(mono) <= 44100 + 1


def test_audio_engine_still_reexports_helpers():
    import audio_engine
    assert audio_engine.read_mono_audio is read_mono_audio
    assert audio_engine.resample_linear is resample_linear
