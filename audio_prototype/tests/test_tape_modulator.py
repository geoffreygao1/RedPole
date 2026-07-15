import numpy as np
import pytest

from tape_modulator import TapeModulator


def test_process_returns_requested_length():
    loop = np.linspace(-0.5, 0.5, 1000, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    out = tm.process(loop, frames=512, warble_depth=0.01, bloom_depth=0.1, rate_hz=1.0)
    assert out.shape == (512,)
    assert out.dtype == np.float32


def test_zero_depth_is_dry_passthrough():
    loop = np.linspace(-0.5, 0.5, 100, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    out = tm.process(loop, frames=25, warble_depth=0.0, bloom_depth=0.0, rate_hz=1.0)
    expected = loop[np.arange(25) % 100]
    np.testing.assert_allclose(out, expected, atol=1e-6)


def test_zero_depth_wraps_around_loop_boundary():
    loop = np.linspace(-0.5, 0.5, 10, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    out = tm.process(loop, frames=25, warble_depth=0.0, bloom_depth=0.0, rate_hz=1.0)
    expected = loop[np.arange(25) % 10]
    np.testing.assert_allclose(out, expected, atol=1e-6)


def test_read_position_persists_across_calls():
    loop = np.linspace(-0.5, 0.5, 10, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    first = tm.process(loop, frames=7, warble_depth=0.0, bloom_depth=0.0, rate_hz=1.0)
    second = tm.process(loop, frames=7, warble_depth=0.0, bloom_depth=0.0, rate_hz=1.0)
    combined = np.concatenate([first, second])
    expected = loop[np.arange(14) % 10]
    np.testing.assert_allclose(combined, expected, atol=1e-6)


def test_nonzero_warble_depth_changes_output():
    loop = np.sin(np.linspace(0, 20 * np.pi, 2000, dtype=np.float32))
    tm_dry = TapeModulator(samplerate=44100, seed=1)
    tm_wet = TapeModulator(samplerate=44100, seed=1)
    dry = tm_dry.process(loop, frames=1024, warble_depth=0.0, bloom_depth=0.0, rate_hz=1.5)
    wet = tm_wet.process(loop, frames=1024, warble_depth=0.02, bloom_depth=0.0, rate_hz=1.5)
    assert not np.allclose(dry, wet)


def test_process_exposes_modulation_signals():
    loop = np.linspace(-0.5, 0.5, 1000, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    tm.process(loop, frames=512, warble_depth=0.02, bloom_depth=0.5, rate_hz=1.5)
    assert tm.last_warble_signal.shape == (512,)
    assert tm.last_gain.shape == (512,)
    # warble signal is depth-scaled, so bounded by the depth passed in
    assert np.all(np.abs(tm.last_warble_signal) <= 0.02 + 1e-9)
    # gain is centered on 1.0
    assert np.all(tm.last_gain > 0.0)
    assert not np.allclose(tm.last_gain, 1.0)


def test_zero_depth_modulation_signals_are_flat():
    loop = np.linspace(-0.5, 0.5, 1000, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    tm.process(loop, frames=256, warble_depth=0.0, bloom_depth=0.0, rate_hz=1.0)
    np.testing.assert_allclose(tm.last_warble_signal, np.zeros(256), atol=1e-9)
    np.testing.assert_allclose(tm.last_gain, np.ones(256), atol=1e-9)


def test_output_stays_within_soft_clip_range():
    loop = np.ones(500, dtype=np.float32)
    tm = TapeModulator(samplerate=44100, seed=1)
    out = tm.process(loop, frames=500, warble_depth=0.02, bloom_depth=0.6, rate_hz=3.0)
    assert np.all(np.abs(out) < 1.0)
