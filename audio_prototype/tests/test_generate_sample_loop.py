import soundfile as sf

import generate_sample_loop as gen


def test_generate_ambient_loop_shape_and_range():
    loop = gen.generate_ambient_loop(samplerate=44100, duration=6.0)
    assert loop.dtype.kind == "f"
    assert len(loop) == 44100 * 6
    assert loop.max() <= 1.0
    assert loop.min() >= -1.0


def test_generate_ambient_loop_is_seamless():
    loop = gen.generate_ambient_loop(samplerate=44100, duration=6.0)
    # first and last sample should be close, so looping doesn't click
    assert abs(float(loop[0]) - float(loop[-1])) < 0.01


def test_main_writes_valid_wav(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "OUTPUT_PATH", tmp_path / "sample_loop.wav")
    gen.main()
    info = sf.info(str(tmp_path / "sample_loop.wav"))
    assert info.samplerate == 44100
    assert info.duration >= 5.9
