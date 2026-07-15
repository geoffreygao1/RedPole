from pathlib import Path

import numpy as np
import pytest

import modulation as mod
from audio_engine import AudioEngine
from frequency_mod_processor import FrequencyModProcessor
from spectral_processor import HOP_SIZE

SAMPLE_LOOP = Path(__file__).parent.parent / "assets" / "sample_loop.wav"


def test_load_loop_reads_bundled_sample():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    assert engine.loop_array is not None
    assert engine.loop_array.dtype == np.float32
    assert len(engine.loop_array) > 44100  # more than one second


def test_load_loop_resamples_mismatched_samplerate(tmp_path):
    import soundfile as sf

    bad_path = tmp_path / "wrong_rate.wav"
    tone = np.sin(2 * np.pi * 220 * np.arange(22050) / 22050).astype(np.float32)
    sf.write(str(bad_path), tone, 22050)
    engine = AudioEngine(samplerate=44100, seed=1)
    engine.load_loop(str(bad_path))

    assert engine.loop_array is not None
    assert len(engine.loop_array) == 44100


def test_load_loop_caps_spectral_analysis_for_long_files(tmp_path, monkeypatch):
    import audio_engine
    import soundfile as sf

    path = tmp_path / "long.wav"
    sr = 44100
    sf.write(str(path), np.zeros(sr, dtype=np.float32), sr)
    observed = {}

    def fake_analyze_loop(loop_array, samplerate):
        observed["length"] = len(loop_array)
        return {"freqs": np.zeros((1, 1)), "amps": np.zeros((1, 1)), "frame_rate": 1.0}

    monkeypatch.setattr(audio_engine, "MAX_ANALYSIS_SECONDS", 0.05)
    monkeypatch.setattr(audio_engine, "analyze_loop", fake_analyze_loop)

    engine = AudioEngine(samplerate=sr, seed=1)
    engine.load_loop(str(path))

    assert len(engine.loop_array) == sr
    assert observed["length"] == int(sr * 0.05)


def test_load_loop_caps_long_file_decode_without_full_read(tmp_path, monkeypatch):
    import audio_engine
    import soundfile as sf

    path = tmp_path / "long.wav"
    sr = 44100
    sf.write(str(path), np.zeros(sr, dtype=np.float32), sr)

    def fail_full_read(*args, **kwargs):
        raise AssertionError("load_loop should not decode long files with sf.read")

    monkeypatch.setattr(audio_engine, "MAX_LOOP_SECONDS", 0.05, raising=False)
    monkeypatch.setattr(audio_engine.sf, "read", fail_full_read)

    engine = AudioEngine(samplerate=sr, seed=1)
    engine.load_loop(str(path))

    assert engine.loop_array is not None
    assert engine.loop_array.dtype == np.float32
    assert len(engine.loop_array) == int(sr * 0.05)


def test_load_loop_reads_mp3(tmp_path):
    import soundfile as sf

    mp3_path = tmp_path / "loop.mp3"
    tone = 0.5 * np.sin(2 * np.pi * 220 * np.arange(44100) / 44100).astype(np.float32)
    sf.write(str(mp3_path), tone, 44100)
    engine = AudioEngine(seed=1)
    engine.load_loop(str(mp3_path))
    assert engine.loop_array is not None
    assert len(engine.loop_array) > 40000


def test_generate_block_requires_loaded_loop():
    engine = AudioEngine(seed=1)
    with pytest.raises(RuntimeError):
        engine.generate_block(512)


def test_generate_block_dry_matches_loop_with_no_layers():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)


def test_generate_block_changes_with_active_layer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    dry = engine.generate_block(1024)

    engine2 = AudioEngine(seed=1)
    engine2.load_loop(str(SAMPLE_LOOP))
    engine2.registry.add(hue=1.0, sat=1.0, val=1.0, bpm=120)
    wet = engine2.generate_block(1024)

    assert not np.allclose(dry, wet)


def test_generate_block_writes_to_visual_buffer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.generate_block(512)
    latest = engine.visual_buffer.read_latest(512)
    assert not np.allclose(latest, np.zeros(512))


def test_generate_block_writes_modulation_buffers():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.registry.add(hue=1.0, sat=1.0, val=1.0, bpm=120)
    engine.generate_block(512)
    warble = engine.warble_buffer.read_latest(512)
    bloom = engine.bloom_buffer.read_latest(512)
    assert not np.allclose(warble, np.zeros(512))
    assert not np.allclose(bloom, np.zeros(512))


def test_modulation_buffers_flat_with_no_layers():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.generate_block(512)
    np.testing.assert_allclose(engine.warble_buffer.read_latest(512), np.zeros(512), atol=1e-9)
    # bloom buffer stores gain - 1.0, so it's zero when dry
    np.testing.assert_allclose(engine.bloom_buffer.read_latest(512), np.zeros(512), atol=1e-9)


def test_default_mode_is_mixed():
    engine = AudioEngine(seed=1)
    assert engine.mode == "mixed"


def test_set_mode_validates():
    engine = AudioEngine(seed=1)
    engine.set_mode("spectral")
    assert engine.mode == "spectral"
    with pytest.raises(ValueError):
        engine.set_mode("reverb")


def test_spectral_mode_zero_layers_is_dry():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("spectral")
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)


def test_spectral_slot_uses_frequency_mod_processor():
    engine = AudioEngine(seed=1)
    assert isinstance(engine.spectral, FrequencyModProcessor)


def test_spectral_mode_layer_changes_output_and_wet_buffer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("spectral")
    engine.registry.add(hue=0.25, sat=0.5, val=1.0, bpm=120)
    block = engine.generate_block(2048)
    dry = engine.loop_array[np.arange(2048) % len(engine.loop_array)]
    assert not np.allclose(block, dry)
    wet = engine.wet_buffer.read_latest(2048)
    assert not np.allclose(wet, np.zeros(2048))


def test_granular_mode_layer_changes_output():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("granular")
    engine.registry.add(hue=0.25, sat=0.5, val=1.0, bpm=180)
    blocks = [engine.generate_block(1024) for _ in range(30)]
    total_wet = engine.wet_buffer.read_latest(1024 * 20)
    assert not np.allclose(total_wet, np.zeros_like(total_wet))
    assert all(b.shape == (1024,) for b in blocks)


def test_tape_mode_writes_zero_wet_buffer():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.registry.add(hue=1.0, sat=1.0, val=1.0, bpm=120)
    engine.generate_block(512)
    np.testing.assert_allclose(engine.wet_buffer.read_latest(512), np.zeros(512))


def test_mixed_mode_in_modes():
    assert "mixed" in AudioEngine.MODES


def test_mixed_mode_zero_layers_is_dry():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("mixed")
    block = engine.generate_block(512)
    expected = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    np.testing.assert_allclose(block, expected, atol=1e-6)


def test_mixed_mode_routes_layers_by_engine():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("mixed")
    engine.registry.add(hue=0.03, sat=0.5, val=1.0, bpm=120, engine="spectral")
    engine.registry.add(hue=0.03, sat=0.5, val=1.0, bpm=180, engine="granular")
    for _ in range(30):
        engine.generate_block(1024)
    # both processors should hold exactly one voice each
    assert len(engine.spectral._voices) == 1
    assert len(engine.granular._voices) == 1
    wet = engine.wet_buffer.read_latest(1024 * 20)
    assert not np.allclose(wet, np.zeros_like(wet))


def test_mixed_mode_routes_microcosm_families_to_wet_bus():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("mixed")
    for family in ("microloop", "granules", "glitch", "multidelay"):
        engine.registry.add(hue=0.03, sat=0.6, val=1.0, bpm=100, engine=family)

    for _ in range(80):
        engine.generate_block(1024)

    wet = engine.wet_buffer.read_latest(1024 * 20)
    assert not np.allclose(wet, np.zeros_like(wet))
    assert np.max(np.abs(wet)) < 1.0


def test_stereo_block_pans_glitch_wet_events():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("mixed")
    engine.wet_dry = 1.0
    engine.registry.add(hue=0.7, sat=0.8, val=1.0, bpm=95, engine="glitch")

    stereo = np.concatenate([engine.generate_stereo_block(1024) for _ in range(120)])

    assert stereo.shape == (1024 * 120, 2)
    assert not np.allclose(stereo[:, 0], stereo[:, 1])
    assert np.max(np.abs(stereo)) <= 1.0


def test_stereo_glitch_pan_is_smoothed():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("mixed")
    engine.wet_dry = 1.0
    engine.registry.add(hue=0.7, sat=0.8, val=1.0, bpm=95, engine="glitch")

    stereo = np.concatenate([engine.generate_stereo_block(1024) for _ in range(160)])
    side = stereo[:, 1] - stereo[:, 0]

    assert np.max(np.abs(np.diff(side))) < 0.14


def test_audio_callback_outputs_stereo(monkeypatch):
    events = []

    class FakeStream:
        def __init__(self, **kwargs):
            events.append(("init", kwargs["channels"]))

        def start(self):
            events.append(("start",))

        def stop(self):
            events.append(("stop",))

        def close(self):
            events.append(("close",))

    monkeypatch.setattr("audio_engine.sd.OutputStream", FakeStream)
    engine = AudioEngine(seed=1)
    engine.start()

    assert events == [("init", 2)]


def test_mixed_mode_tape_layer_modulates_base():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("mixed")
    engine.registry.add(hue=0.06, sat=1.0, val=1.0, bpm=120, engine="tape")
    block = engine.generate_block(2048)
    dry = engine.loop_array[np.arange(2048) % len(engine.loop_array)]
    assert not np.allclose(block, dry)
    # no spectral/granular layers -> wet stays silent
    np.testing.assert_allclose(engine.wet_buffer.read_latest(2048), np.zeros(2048))


def test_dry_is_ducked_with_wet_layers():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("granular")
    for _ in range(4):
        engine.registry.add(hue=0.0, sat=0.5, val=0.0, bpm=1.0, engine="granular")
    # val=0 silences grains; bpm=1 nearly never pulses -> block is just
    # the ducked dry signal
    block = engine.generate_block(512)
    dry = engine.loop_array[np.arange(512) % len(engine.loop_array)]
    expected_duck = max(0.5, 1.0 / (1.0 + 0.12 * 4))
    np.testing.assert_allclose(block, dry * expected_duck, atol=1e-3)


def test_wet_events_dynamically_duck_dry_source():
    class FakeMicrocosm:
        def __init__(self, wet):
            self.wet = wet.astype(np.float32)

        def process(self, loop_array, frames, layers, source_pos=0):
            return self.wet[:frames]

    frames = 1024
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("mixed")
    engine.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=120, engine="microloop")
    engine.wet_dry = 0.0
    engine.wet_bus.process = lambda wet, wet_voice_count, reverb_layer_count: wet
    engine.reverb_mix = 0.0

    silent_wet = np.zeros(frames, dtype=np.float32)
    engine.microcosm = FakeMicrocosm(silent_wet)
    quiet = engine.generate_block(frames)

    engine._dry_pos = 0
    engine.modulator._read_pos = 0.0
    engine._wet_duck_state = 0.0
    loud_wet = np.zeros(frames, dtype=np.float32)
    loud_wet[frames // 4:frames // 2] = 0.8
    engine.microcosm = FakeMicrocosm(loud_wet)
    ducked = engine.generate_block(frames)

    active = slice(frames // 4, frames // 2)
    assert np.mean(np.abs(ducked[active])) < np.mean(np.abs(quiet[active])) * 0.86


def test_reverb_adds_tail_to_wet():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("granular")
    engine.reverb_mix = 1.0
    layer_id = engine.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=180, engine="granular")
    for _ in range(40):
        engine.generate_block(1024)
    engine.registry.remove(layer_id)
    # with the layer gone the raw wet is silent, but the reverb tail rings on
    tail = np.concatenate([engine.generate_block(1024) for _ in range(3)])
    dry = None  # tail block includes dry loop; compare against wet buffer instead
    wet_tail = engine.wet_buffer.read_latest(1024 * 3)
    assert not np.allclose(wet_tail, np.zeros_like(wet_tail))


def test_pause_resume_state_without_stream():
    engine = AudioEngine(seed=1)
    assert engine.paused is True
    engine.pause()
    assert engine.paused is True
    engine.resume()
    assert engine.paused is False


def test_start_does_not_play_when_initially_paused(monkeypatch):
    events = []

    class FakeStream:
        def __init__(self, **kwargs):
            events.append(("init", kwargs["samplerate"], kwargs["blocksize"]))

        def start(self):
            events.append(("start",))

        def stop(self):
            events.append(("stop",))

        def close(self):
            events.append(("close",))

    monkeypatch.setattr("audio_engine.sd.OutputStream", FakeStream)
    engine = AudioEngine(seed=1)
    engine.start()

    assert engine.paused is True
    assert events == [("init", engine.samplerate, engine.blocksize)]

    engine.resume()
    assert engine.paused is False
    assert events[-1] == ("start",)


def test_wet_dry_default_is_balanced():
    engine = AudioEngine(seed=1)
    assert engine.wet_dry == pytest.approx(0.5)


def test_wet_dry_zero_mutes_wet():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("granular")
    engine.wet_dry = 0.0
    engine.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=180, engine="granular")
    for _ in range(30):
        block = engine.generate_block(1024)
    # wet is fully muted, so output is just the ducked dry loop
    start = engine._dry_pos - 1024
    dry = engine.loop_array[
        (start + np.arange(1024)) % len(engine.loop_array)
    ]
    duck = max(0.5, 1.0 / (1.0 + 0.12 * 1))
    assert np.max(np.abs(block)) <= np.max(np.abs(dry * duck)) + 1e-5
    assert np.mean(np.abs(block)) < np.mean(np.abs(dry * duck))


def test_wet_dry_one_mutes_dry():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("granular")
    engine.wet_dry = 1.0
    # silent wet layer (val=0, bpm=1): with dry muted too, output ~ zero
    engine.registry.add(hue=0.0, sat=0.5, val=0.0, bpm=1.0, engine="granular")
    block = engine.generate_block(512)
    np.testing.assert_allclose(block, np.zeros(512), atol=1e-5)


def test_reverb_character_follows_reverb_layer_bpm():
    def settled_feedback(bpm):
        engine = AudioEngine(seed=1)
        engine.load_loop(str(SAMPLE_LOOP))
        engine.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=bpm, engine="reverb")
        for _ in range(60):
            engine.generate_block(1024)
        return engine.reverb._combs[0].feedback

    assert settled_feedback(40) > settled_feedback(180)


def test_slow_ambient_reverb_layer_reaches_long_tail_feedback():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.registry.add(hue=0.92, sat=1.0, val=1.0, bpm=40, engine="reverb")

    for _ in range(80):
        engine.generate_block(1024)

    assert engine.reverb._combs[0].feedback > 0.95


def test_reverb_character_follows_reverb_layer_brightness():
    def settled_cutoff(val):
        engine = AudioEngine(seed=1)
        engine.load_loop(str(SAMPLE_LOOP))
        engine.registry.add(hue=0.0, sat=0.5, val=val, bpm=120, engine="reverb")
        for _ in range(60):
            engine.generate_block(1024)
        return engine.reverb._lowpass.cutoff_hz

    assert settled_cutoff(0.3) < settled_cutoff(1.0)


def test_reverb_color_selects_space_style():
    def settled_style(hue):
        engine = AudioEngine(seed=1)
        engine.load_loop(str(SAMPLE_LOOP))
        engine.registry.add(
            hue=hue,
            sat=mod.FINGER_SAT_MAX,
            val=mod.FINGER_VAL_MAX,
            bpm=80,
            engine="reverb",
        )
        for _ in range(80):
            engine.generate_block(1024)
        return engine.reverb.space_style

    hue_span = mod.FINGER_HUE_MAX - mod.FINGER_HUE_MIN
    assert settled_style(mod.FINGER_HUE_MIN + hue_span * 0.125) == "bright_room"
    assert settled_style(mod.FINGER_HUE_MIN + hue_span * 0.375) == "dark_medium"
    assert settled_style(mod.FINGER_HUE_MIN + hue_span * 0.625) == "large_hall"
    assert settled_style(mod.FINGER_HUE_MIN + hue_span * 0.875) == "ambient"


def test_reverb_patch_column_five_selects_wash_style():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    source_id = engine.registry.add_source(
        hue=0.05,
        sat=1.0,
        val=1.0,
        bpm=40,
    )
    engine.registry.connect_source(
        source_id,
        engine="reverb",
        row=4,
        col=4,
    )

    for _ in range(90):
        engine.generate_block(1024)

    assert engine.reverb.space_style == "wash"
    assert engine.reverb._combs[0].feedback > 0.97
    assert engine.reverb._lowpass.cutoff_hz < 5000.0


def test_multiple_reverb_layers_expand_space_and_send():
    def settle(layers):
        engine = AudioEngine(seed=1)
        engine.load_loop(str(SAMPLE_LOOP))
        for layer in layers:
            engine.registry.add(**layer, engine="reverb")
        for _ in range(80):
            engine.generate_block(1024)
        wet = engine.wet_buffer.read_latest(1024 * 20)
        return (
            engine.reverb.space_size,
            engine.reverb.diffusion,
            float(np.sqrt(np.mean(wet**2))),
        )

    one = [
        {"hue": 0.05, "sat": 0.2, "val": 0.5, "bpm": 150},
    ]
    many = [
        {"hue": 0.05, "sat": 0.2, "val": 0.5, "bpm": 150},
        {"hue": 0.65, "sat": 0.9, "val": 0.8, "bpm": 70},
        {"hue": 0.92, "sat": 1.0, "val": 1.0, "bpm": 45},
    ]

    one_size, one_diffusion, one_wet = settle(one)
    many_size, many_diffusion, many_wet = settle(many)

    assert many_size > one_size
    assert many_diffusion > one_diffusion
    assert many_wet > one_wet * 1.2


def test_reverb_layers_add_wet_tail_without_ducking_dry():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=120, engine="reverb")
    for _ in range(12):
        block = engine.generate_block(512)
    start = engine._dry_pos - 512
    dry = engine.loop_array[(start + np.arange(512)) % len(engine.loop_array)]
    # a reverb-only layer should not duck the dry/base path, but its wet
    # tail is audible after the room predelay and in the wet buffer.
    assert np.max(np.abs(block - dry)) > 0.0
    assert not np.allclose(engine.wet_buffer.read_latest(512), np.zeros(512))


def test_reverb_layer_adds_source_tail_to_wet_side():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=120, engine="reverb")

    for _ in range(20):
        engine.generate_block(1024)

    wet = engine.wet_buffer.read_latest(1024 * 10)
    assert not np.allclose(wet, np.zeros_like(wet))


def test_full_wet_reverb_layer_is_not_dry_like():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.wet_dry = 1.0
    engine.registry.add(hue=0.92, sat=1.0, val=1.0, bpm=45, engine="reverb")

    dry_blocks = []
    wet_blocks = []
    for _ in range(80):
        start = engine._dry_pos
        dry_blocks.append(
            engine.loop_array[(start + np.arange(1024)) % len(engine.loop_array)]
        )
        wet_blocks.append(engine.generate_block(1024))

    dry = np.concatenate(dry_blocks[-30:])
    wet = np.concatenate(wet_blocks[-30:])
    corr = np.corrcoef(dry, wet)[0, 1]

    assert abs(corr) < 0.75


def test_reverb_source_send_follows_color_and_saturation_space():
    def render(hue, sat):
        engine = AudioEngine(seed=1)
        engine.load_loop(str(SAMPLE_LOOP))
        engine.registry.add(hue=hue, sat=sat, val=0.75, bpm=120, engine="reverb")
        for _ in range(20):
            engine.generate_block(1024)
        return engine.wet_buffer.read_latest(1024 * 10)

    low_color = render(hue=0.94, sat=1.0)
    high_color = render(hue=0.06, sat=0.0)
    assert not np.allclose(low_color, high_color)


def test_reverb_source_send_follows_average_value():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.registry.add(hue=0.0, sat=0.5, val=0.2, bpm=120, engine="reverb")
    for _ in range(20):
        engine.generate_block(1024)
    low_energy = float(np.sqrt(np.mean(engine.wet_buffer.read_latest(1024 * 10) ** 2)))

    engine2 = AudioEngine(seed=1)
    engine2.load_loop(str(SAMPLE_LOOP))
    engine2.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=120, engine="reverb")
    for _ in range(20):
        engine2.generate_block(1024)
    high_energy = float(np.sqrt(np.mean(engine2.wet_buffer.read_latest(1024 * 10) ** 2)))

    assert high_energy > low_energy


def test_new_wet_layer_gets_short_entry_gesture(monkeypatch):
    class FakeSpectral:
        def process(self, loop_array, frames, layers, live_frame=None, scan_start=None):
            t = np.arange(frames) / 44100.0
            return (
                0.1 * np.sin(2.0 * np.pi * 440.0 * t)
            ).astype(np.float32) if layers else np.zeros(frames)

    class FakeGranular:
        def process(self, loop_array, frames, layers, source_pos=0):
            return np.zeros(frames, dtype=np.float32)

    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.reverb_mix = 0.0
    engine.wet_dry = 1.0
    engine.spectral = FakeSpectral()
    engine.granular = FakeGranular()
    engine.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=120, engine="spectral")

    first = engine.generate_block(1024)
    for _ in range(260):
        later = engine.generate_block(1024)

    first_delta = float(np.sqrt(np.mean(first**2)))
    later_delta = float(np.sqrt(np.mean(later**2)))

    assert first_delta > later_delta * 1.1


def test_many_reverb_layers_stay_bounded():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.reverb_mix = 1.0
    for i in range(32):
        engine.registry.add(
            hue=(i % 12) / 100.0,
            sat=0.8,
            val=1.0,
            bpm=40,
            engine="reverb",
        )

    for _ in range(120):
        block = engine.generate_block(1024)
        assert not np.any(np.isnan(block))
        assert np.max(np.abs(block)) <= 1.0

    wet = engine.wet_buffer.read_latest(1024 * 30)
    assert float(np.sqrt(np.mean(wet**2))) < 0.5


def test_many_layers_with_feedback_stay_bounded():
    """20 layers + live analysis + long reverb must not overload."""
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.live_analysis = True
    engine.reverb_mix = 1.0
    for i in range(10):
        engine.registry.add(hue=0.02, sat=0.8, val=1.0, bpm=40, engine="spectral")
        engine.registry.add(hue=0.05, sat=0.8, val=1.0, bpm=40, engine="granular")

    for _ in range(150):
        block = engine.generate_block(1024)
        assert not np.any(np.isnan(block))

    wet = engine.wet_buffer.read_latest(1024 * 40)
    wet_rms = float(np.sqrt(np.mean(wet**2)))
    # adaptive wet-bus management holds sustained wet energy down before
    # the limiter has to become the primary sound-shaping stage
    assert wet_rms < 0.5
    controls = engine.wet_bus.controls(wet_voice_count=20, reverb_layer_count=0)
    assert controls["wet_gain"] < 0.6


def test_live_analysis_flag_does_not_change_frequency_mod_behavior():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("spectral")
    engine.registry.add(hue=0.0, sat=0.0, val=1.0, bpm=120, engine="spectral")

    engine.live_analysis = False
    for _ in range(10):
        engine.generate_block(1024)
    precomputed = engine.generate_block(4096)

    engine2 = AudioEngine(seed=1)
    engine2.load_loop(str(SAMPLE_LOOP))
    engine2.set_mode("spectral")
    engine2.registry.add(hue=0.0, sat=0.0, val=1.0, bpm=120, engine="spectral")
    engine2.live_analysis = True
    for _ in range(10):
        engine2.generate_block(1024)
    live = engine2.generate_block(4096)

    np.testing.assert_allclose(precomputed, live)


def _band_rms(x, samplerate, low_hz, high_hz):
    x = np.asarray(x)
    spectrum = np.fft.rfft(x * np.hanning(len(x)))
    freqs = np.fft.rfftfreq(len(x), 1.0 / samplerate)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    return float(np.sqrt(np.mean(np.abs(spectrum[mask]) ** 2)))


def test_dense_wet_layers_trigger_wet_bus_gain_reduction():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    for _ in range(20):
        engine.registry.add(hue=0.03, sat=0.7, val=1.0, bpm=120, engine="spectral")

    for _ in range(20):
        engine.generate_block(1024)

    controls = engine.wet_bus.controls(wet_voice_count=20, reverb_layer_count=0)
    assert controls["wet_gain"] < 0.6
    assert engine.wet_limiter.gain > 0.2


def test_dense_wet_bus_reduces_low_mid_energy():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    low_mid = np.sin(2 * np.pi * 160 * np.arange(8192) / engine.samplerate).astype(
        np.float32
    )

    shaped_sparse = engine.wet_bus.process(
        low_mid, wet_voice_count=1, reverb_layer_count=0
    )

    engine2 = AudioEngine(seed=1)
    engine2.load_loop(str(SAMPLE_LOOP))
    shaped_dense = engine2.wet_bus.process(
        low_mid, wet_voice_count=20, reverb_layer_count=0
    )

    sparse_low = _band_rms(shaped_sparse, engine.samplerate, 80, 300)
    dense_low = _band_rms(shaped_dense, engine.samplerate, 80, 300)
    assert dense_low < sparse_low * 0.7


def test_reverb_density_tightens_feedback_and_cutoff():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=40, engine="reverb")
    for _ in range(20):
        engine.registry.add(hue=0.03, sat=0.7, val=1.0, bpm=120, engine="spectral")

    for _ in range(80):
        engine.generate_block(1024)

    dense_feedback = engine.reverb._combs[0].feedback
    dense_cutoff = engine.reverb._lowpass.cutoff_hz

    sparse = AudioEngine(seed=1)
    sparse.load_loop(str(SAMPLE_LOOP))
    sparse.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=40, engine="reverb")
    for _ in range(80):
        sparse.generate_block(1024)

    assert dense_feedback < sparse.reverb._combs[0].feedback
    assert dense_cutoff < sparse.reverb._lowpass.cutoff_hz


def test_new_fm_layer_starts_at_current_source_position():
    engine = AudioEngine(seed=1)
    engine.load_loop(str(SAMPLE_LOOP))
    engine.set_mode("spectral")
    engine.generate_block(HOP_SIZE * 5)
    source_pos = engine._dry_pos

    engine.registry.add(hue=0.0, sat=0.5, val=1.0, bpm=40, engine="spectral")
    engine.generate_block(HOP_SIZE)

    assert engine.spectral._last_base_pos == pytest.approx(source_pos)
