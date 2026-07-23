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
