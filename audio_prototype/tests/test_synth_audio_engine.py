import numpy as np

from synth_audio_engine import SynthAudioEngine


def test_connect_patch_returns_increasing_ids():
    eng = SynthAudioEngine(seed=1)
    a = eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    b = eng.connect_patch(0.03, 0.68, 0.94, 90.0, "granular_1")
    assert b > a


def test_no_patches_is_silence():
    eng = SynthAudioEngine(seed=1)
    block = eng.generate_block(1024)
    assert block.shape == (1024,)
    assert block.dtype == np.float32
    np.testing.assert_allclose(block, np.zeros(1024))


def test_one_patch_is_audible_bounded_nan_free():
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    total = np.concatenate([eng.generate_block(1024) for _ in range(80)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-3
    assert float(np.sqrt(np.mean(total[-8192:] ** 2))) > 0.01


def test_disconnect_last_patch_returns_to_silence():
    eng = SynthAudioEngine(seed=1)
    pid = eng.connect_patch(0.03, 0.68, 0.94, 90.0, "noise_2")
    eng.generate_block(512)
    eng.disconnect_patch(pid)
    np.testing.assert_allclose(eng.generate_block(512), np.zeros(512))


def test_active_patches_snapshot_shape():
    eng = SynthAudioEngine(seed=1)
    pid = eng.connect_patch(0.02, 0.7, 0.9, 88.0, "resonant_1", "spatial_1")
    patches = eng.active_patches()
    assert len(patches) == 1
    p = patches[0]
    assert p["id"] == pid
    assert p["source_preset"] == "resonant_1"
    assert p["transform_preset"] == "spatial_1"
    assert p["bpm"] == 88.0


def test_stereo_block_duplicates_mono():
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    stereo = eng.generate_stereo_block(256)
    assert stereo.shape == (256, 2)
    np.testing.assert_array_equal(stereo[:, 0], stereo[:, 1])


def test_generate_block_writes_visual_buffer():
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    for _ in range(20):
        eng.generate_block(1024)
    latest = eng.visual_buffer.read_latest(1024)
    assert float(np.max(np.abs(latest))) > 0.0


def test_render_exception_yields_silent_block(monkeypatch):
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")

    def boom(frames):
        raise RuntimeError("render failed")

    monkeypatch.setattr(eng.engine, "generate_block", boom)
    block = eng.generate_block(512)
    np.testing.assert_allclose(block, np.zeros(512))


def _fake_stream_factory(events):
    class FakeStream:
        def __init__(self, **kwargs):
            events.append(("init", kwargs["channels"]))
            self.callback = kwargs["callback"]

        def start(self):
            events.append(("start",))

        def stop(self):
            events.append(("stop",))

        def close(self):
            events.append(("close",))

    return FakeStream


def test_starts_paused_and_opens_no_stream(monkeypatch):
    events = []
    monkeypatch.setattr(
        "synth_audio_engine.sd.OutputStream", _fake_stream_factory(events)
    )
    eng = SynthAudioEngine(seed=1)
    assert eng.paused is True
    eng.start()  # start() while paused should not begin playback
    assert ("start",) not in events


def test_resume_opens_and_starts_stream(monkeypatch):
    events = []
    monkeypatch.setattr(
        "synth_audio_engine.sd.OutputStream", _fake_stream_factory(events)
    )
    eng = SynthAudioEngine(seed=1)
    eng.resume()
    assert eng.paused is False
    assert ("init", 2) in events
    assert events.count(("start",)) == 1


def test_pause_stops_without_closing(monkeypatch):
    events = []
    monkeypatch.setattr(
        "synth_audio_engine.sd.OutputStream", _fake_stream_factory(events)
    )
    eng = SynthAudioEngine(seed=1)
    eng.resume()
    eng.pause()
    assert eng.paused is True
    assert ("stop",) in events
    assert ("close",) not in events


def test_stop_closes_stream(monkeypatch):
    events = []
    monkeypatch.setattr(
        "synth_audio_engine.sd.OutputStream", _fake_stream_factory(events)
    )
    eng = SynthAudioEngine(seed=1)
    eng.resume()
    eng.stop()
    assert ("close",) in events


def test_callback_fills_outdata_stereo(monkeypatch):
    events = []
    monkeypatch.setattr(
        "synth_audio_engine.sd.OutputStream", _fake_stream_factory(events)
    )
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    out = np.zeros((256, 2), dtype=np.float32)
    eng._callback(out, 256, None, None)
    assert out.shape == (256, 2)
    np.testing.assert_array_equal(out[:, 0], out[:, 1])


def test_load_sample_array_changes_texture_output():
    a = SynthAudioEngine(seed=6)
    b = SynthAudioEngine(seed=6)
    b.load_sample_array(np.sin(2 * np.pi * 440 * np.arange(44100 * 3) / 44100))
    a.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    b.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    out_a = np.concatenate([a.generate_block(1024) for _ in range(20)])
    out_b = np.concatenate([b.generate_block(1024) for _ in range(20)])
    assert not np.allclose(out_a, out_b)


def test_load_sample_reads_file(tmp_path):
    import soundfile as sf

    path = tmp_path / "tex.wav"
    sf.write(str(path), np.sin(2 * np.pi * 330 * np.arange(44100) / 44100), 44100)
    eng = SynthAudioEngine(seed=6)
    eng.load_sample(str(path))  # should not raise
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    out = np.concatenate([eng.generate_block(1024) for _ in range(10)])
    assert not np.any(np.isnan(out))


def test_set_root_midi_rebuilds_and_clears_patches():
    eng = SynthAudioEngine(seed=1, root_midi=62)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    assert len(eng.active_patches()) == 1
    eng.set_root_midi(60)
    assert eng.root_midi == 60
    assert eng.active_patches() == []


def test_set_root_midi_reapplies_loaded_sample():
    eng = SynthAudioEngine(seed=6)
    eng.load_sample_array(np.sin(2 * np.pi * 440 * np.arange(44100 * 3) / 44100))
    eng.set_root_midi(65)
    baseline = SynthAudioEngine(seed=6)  # same seed, no sample loaded
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    baseline.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    out = np.concatenate([eng.generate_block(1024) for _ in range(20)])
    base = np.concatenate([baseline.generate_block(1024) for _ in range(20)])
    assert not np.allclose(out, base)  # loaded sample carried across the rebuild
