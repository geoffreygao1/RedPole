import modulation as mod
from soundscape_color import calibrate_color
from soundscape_voices import sync_voices


def test_calibrate_color_maps_gamut_extremes_to_unit_range():
    dark = calibrate_color(mod.FINGER_HUE_MIN, mod.FINGER_SAT_MIN, mod.FINGER_VAL_MIN)
    bright = calibrate_color(mod.FINGER_HUE_MAX, mod.FINGER_SAT_MAX, mod.FINGER_VAL_MAX)
    assert dark["warmth"] == 0.0
    assert bright["warmth"] == 1.0
    assert bright["brightness"] > dark["brightness"]
    assert bright["saturation"] > dark["saturation"]
    for d in (dark, bright):
        for key in ("warmth", "brightness", "saturation"):
            assert 0.0 <= d[key] <= 1.0


def test_sync_voices_drops_inactive_and_keeps_active():
    voices = {1: "a", 2: "b", 3: "c"}
    sync_voices(voices, [1, 3])
    assert voices == {1: "a", 3: "c"}


def test_sync_voices_handles_empty_active_list():
    voices = {1: "a"}
    sync_voices(voices, [])
    assert voices == {}
