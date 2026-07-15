import pytest

from crowd import CrowdState, EntryGestureTracker


def _layer(layer_id, engine="granular", bpm=120.0, val=0.8):
    return {
        "id": layer_id,
        "hue": 0.0,
        "sat": 0.5,
        "val": val,
        "bpm": bpm,
        "engine": engine,
    }


def test_crowd_state_summarizes_density_bpm_brightness_and_engine_weights():
    layers = [
        _layer(1, engine="tape", bpm=90.0, val=0.4),
        _layer(2, engine="granular", bpm=150.0, val=0.8),
        _layer(3, engine="granular", bpm=120.0, val=1.0),
    ]

    state = CrowdState.from_layers(layers)

    assert state.count == 3
    assert 0.0 < state.density < 1.0
    assert state.bpm_mean == pytest.approx(120.0)
    assert state.bpm_activity > 0.0
    assert state.brightness_mean == pytest.approx((0.4 + 0.8 + 1.0) / 3.0)
    assert state.engine_weights["granular"] > state.engine_weights["tape"]
    assert state.engine_weights["spectral"] == 0.0


def test_entry_gesture_triggers_for_new_layer_then_decays():
    tracker = EntryGestureTracker(samplerate=10, duration_seconds=2.0)
    layers = [_layer(1, engine="spectral", val=1.0)]

    first = tracker.process(layers, frames=5, density=0.2)
    second = tracker.process(layers, frames=5, density=0.2)
    later = tracker.process(layers, frames=20, density=0.2)
    after_expiry = tracker.process(layers, frames=5, density=0.2)

    assert first.engine_gain("spectral") > 0.0
    assert second.engine_gain("spectral") < first.engine_gain("spectral")
    assert later.engine_gain("spectral") > 0.0
    assert after_expiry.engine_gain("spectral") == 0.0


def test_entry_gesture_accepts_microcosm_families():
    tracker = EntryGestureTracker(samplerate=10, duration_seconds=2.0)
    layers = [
        _layer(1, engine="microloop", val=0.8),
        _layer(2, engine="granules", val=0.8),
        _layer(3, engine="glitch", val=0.8),
        _layer(4, engine="multidelay", val=0.8),
    ]

    state = tracker.process(layers, frames=5, density=0.3)

    for engine in ("microloop", "granules", "glitch", "multidelay"):
        assert state.engine_gain(engine) > 0.0


def test_entry_gesture_does_not_retrigger_existing_layer():
    tracker = EntryGestureTracker(samplerate=10, duration_seconds=1.0)
    layers = [_layer(1, engine="granular", val=1.0)]

    first = tracker.process(layers, frames=5, density=0.0)
    tracker.process(layers, frames=10, density=0.0)
    after_expiry = tracker.process(layers, frames=5, density=0.0)

    assert first.engine_gain("granular") > 0.0
    assert after_expiry.engine_gain("granular") == 0.0


def test_entry_gesture_limits_simultaneous_notices():
    tracker = EntryGestureTracker(samplerate=10, duration_seconds=2.0, max_active=3)
    layers = [_layer(i, engine="granular", val=1.0) for i in range(10)]

    state = tracker.process(layers, frames=1, density=1.0)

    assert state.active_count == 3
    assert state.engine_gain("granular") <= 0.5
