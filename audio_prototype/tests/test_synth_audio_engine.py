import numpy as np
import pytest
import time

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


class _FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.writes = 0
        self.started = False
        self.closed = False
        self.last = None

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    def write(self, block):
        self.writes += 1
        self.last = np.array(block)
        time.sleep(0.001)


def _install_fake_stream(monkeypatch):
    created = {}

    def factory(**kwargs):
        stream = _FakeStream(**kwargs)
        created["stream"] = stream
        return stream

    monkeypatch.setattr("synth_audio_engine.sd.OutputStream", factory)
    return created


def test_start_while_paused_opens_no_stream(monkeypatch):
    created = _install_fake_stream(monkeypatch)
    eng = SynthAudioEngine(seed=1)
    eng.start()
    assert eng.paused is True
    assert "stream" not in created
    assert eng._stream is None


def test_resume_opens_high_latency_stream_and_produces(monkeypatch):
    created = _install_fake_stream(monkeypatch)
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    eng.resume()
    time.sleep(0.05)
    eng.stop()
    stream = created["stream"]
    assert stream.kwargs.get("latency") == "high"
    assert stream.kwargs.get("channels") == 2
    assert stream.writes > 0
    assert stream.closed is True
    assert eng._running is False


def test_pause_writes_silence_but_keeps_stream_open(monkeypatch):
    created = _install_fake_stream(monkeypatch)
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    eng.resume()
    time.sleep(0.03)
    eng.pause()
    time.sleep(0.05)
    stream = created["stream"]
    assert eng.paused is True
    assert stream.closed is False
    # the most recent block written while paused is silent
    assert float(np.max(np.abs(stream.last))) == 0.0
    eng.stop()


def test_stop_joins_producer_and_closes(monkeypatch):
    created = _install_fake_stream(monkeypatch)
    eng = SynthAudioEngine(seed=1)
    eng.resume()
    time.sleep(0.02)
    eng.stop()
    assert eng._running is False
    assert eng._producer is None
    assert created["stream"].closed is True


def test_produces_stereo_blocks(monkeypatch):
    created = _install_fake_stream(monkeypatch)
    eng = SynthAudioEngine(seed=1)
    eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2")
    eng.resume()
    time.sleep(0.05)
    eng.stop()
    assert created["stream"].last.shape[1] == 2


def test_load_sample_array_changes_texture_output():
    a = SynthAudioEngine(seed=6)
    b = SynthAudioEngine(seed=6)
    b.load_sample_array(np.sin(2 * np.pi * 440 * np.arange(44100 * 3) / 44100))
    a.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    b.connect_patch(0.03, 0.68, 0.94, 90.0, "texture_1")
    out_a = np.concatenate([a.generate_block(1024) for _ in range(20)])
    out_b = np.concatenate([b.generate_block(1024) for _ in range(20)])
    assert not np.allclose(out_a, out_b)


def test_load_sample_array_rejects_empty_samples():
    eng = SynthAudioEngine(seed=6)
    with pytest.raises(ValueError):
        eng.load_sample_array(np.zeros(0, dtype=np.float32))


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


def test_set_root_updates_target_without_clearing_patches():
    eng = SynthAudioEngine(seed=1, root_midi=62)
    pid = eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2", None)
    eng.set_root(55.0)
    assert eng.root_midi == 55
    assert [p["id"] for p in eng.active_patches()] == [pid]   # patches survive
    assert eng.engine._root_target == 55.0


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
