import numpy as np
import pytest

from wet_bus import WetBusManager, density_controls

SR = 44100


def _tone(freq, seconds=1.0, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


def _rms(x):
    return float(np.sqrt(np.mean(np.asarray(x) ** 2)))


def test_density_controls_are_neutral_with_no_density():
    controls = density_controls(wet_voice_count=0, reverb_layer_count=0)
    assert controls["wet_gain"] == pytest.approx(1.0)
    assert controls["feedback_trim"] == pytest.approx(0.0)
    assert controls["cutoff_scale"] == pytest.approx(1.0)
    assert controls["highpass_hz"] == pytest.approx(35.0)
    assert controls["low_mid_gain"] == pytest.approx(1.0)


def test_density_controls_tighten_as_layers_accumulate():
    light = density_controls(wet_voice_count=1, reverb_layer_count=0)
    dense = density_controls(wet_voice_count=20, reverb_layer_count=4)
    assert dense["density"] > light["density"]
    assert dense["wet_gain"] == pytest.approx(1.0)
    assert dense["feedback_trim"] > light["feedback_trim"]
    assert dense["cutoff_scale"] < light["cutoff_scale"]
    assert dense["highpass_hz"] == pytest.approx(35.0)
    assert dense["low_mid_gain"] == pytest.approx(1.0)


def test_wet_bus_process_has_no_patch_count_dampening():
    manager = WetBusManager(SR)
    low = _tone(120.0)
    presence = _tone(1800.0)
    low_out = manager.process(low, wet_voice_count=20, reverb_layer_count=0)

    manager2 = WetBusManager(SR)
    presence_out = manager2.process(
        presence, wet_voice_count=20, reverb_layer_count=0
    )

    np.testing.assert_allclose(low_out, low, atol=1e-6)
    np.testing.assert_allclose(presence_out, presence, atol=1e-6)


def test_process_is_neutral_for_zero_density_after_filter_settle():
    manager = WetBusManager(SR)
    x = _tone(800.0)
    out = manager.process(x, wet_voice_count=0, reverb_layer_count=0)
    np.testing.assert_allclose(out[4000:], x[4000:], atol=0.04)
    assert out.dtype == np.float32
