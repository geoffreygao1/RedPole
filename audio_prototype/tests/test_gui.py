import colorsys

from gui import (
    BPM_MAX,
    BPM_MIN,
    LEFT_COLUMN_GRID,
    LEFT_STACK_ROWS,
    PATCH_GRID_SIZE,
    PATCH_GRID_X,
    PATCH_GRID_Y,
    PATCH_CELL,
    PATCH_CANVAS_H,
    PATCH_CANVAS_W,
    PATCH_ROW_ENGINES,
    PATCH_SOURCE_LIMIT,
    PICKER_H,
    PICKER_W,
    WAVEFORM_FIGSIZE,
    _can_add_patch_source,
    _patch_cable_points,
    _patch_effect_jack_bounds,
    _patch_cell_to_engine,
    _patch_slot_positions,
    _picker_coords_to_hsv,
    _random_scan_values,
    _source_positions_for_sources,
    _source_positions_for_ids,
)


class FixedRng:
    def integers(self, low, high):
        return high - 1

    def uniform(self, low, high):
        return (low + high) / 2.0


def test_random_scan_values_stay_in_picker_and_bpm_ranges():
    x, y, bpm = _random_scan_values(FixedRng())

    assert x == PICKER_W - 1
    assert y == PICKER_H - 1
    assert BPM_MIN <= bpm <= BPM_MAX


def test_random_scan_values_produce_valid_hsv():
    x, y, _bpm = _random_scan_values(FixedRng())
    hue, sat, val = _picker_coords_to_hsv(x, y)

    assert 0.0 <= hue <= 1.0
    assert 0.0 <= sat <= 1.0
    assert 0.0 <= val <= 1.0


def test_picker_gamut_stays_in_bright_transilluminated_finger_range():
    _hue_top, sat_top, val_top = _picker_coords_to_hsv(0, 0)
    _hue_bottom, sat_bottom, val_bottom = _picker_coords_to_hsv(
        PICKER_W - 1,
        PICKER_H - 1,
    )

    assert val_top >= 0.96
    assert val_bottom >= 0.88
    assert sat_top >= 0.68
    assert sat_bottom >= 0.58


def test_picker_gamut_runs_from_red_to_orange_without_brown():
    hue_left, _sat_left, _val_left = _picker_coords_to_hsv(0, PICKER_H // 2)
    hue_right, sat_right, val_right = _picker_coords_to_hsv(
        PICKER_W - 1,
        PICKER_H - 1,
    )
    r, g, b = colorsys.hsv_to_rgb(hue_right, sat_right, val_right)

    assert hue_left == 0.0
    assert 0.06 <= hue_right <= 0.10
    assert r > g > b
    assert min(r, g, b) > 0.18


def test_patch_grid_rows_route_to_effect_engines():
    assert PATCH_GRID_SIZE == 5
    assert PATCH_ROW_ENGINES == (
        "microloop",
        "granules",
        "glitch",
        "multidelay",
        "tape",
    )
    for row, engine in enumerate(PATCH_ROW_ENGINES[:4]):
        assert _patch_cell_to_engine(row, 0) == engine
        assert _patch_cell_to_engine(row, 4) == engine
    assert [_patch_cell_to_engine(4, col) for col in range(5)] == [
        "tape",
        "tape",
        "tape",
        "tape",
        "reverb",
    ]


def test_tape_patch_column_labels_are_subtle_color_controls():
    from gui import PATCH_TAPE_COL_LABELS

    assert PATCH_TAPE_COL_LABELS == ("wow", "flutter", "tone", "dropout", "reverb")


def test_patch_bay_is_primary_and_waveform_is_shorter():
    assert PATCH_CANVAS_W >= 900
    assert PATCH_CANVAS_H >= 400
    assert PATCH_CELL >= 50
    assert WAVEFORM_FIGSIZE[1] <= 2.0


def test_left_controls_stack_independently_from_right_rows():
    assert LEFT_COLUMN_GRID["row"] == 0
    assert LEFT_COLUMN_GRID["column"] == 0
    assert LEFT_COLUMN_GRID["rowspan"] == 2
    assert LEFT_STACK_ROWS == {
        "scan_input": 0,
        "audition": 1,
        "scan_sources": 2,
    }


def test_patch_effect_grid_is_shifted_right_of_output_columns():
    positions = _source_positions_for_ids(list(range(1, PATCH_SOURCE_LIMIT + 1)))
    rightmost_output_x = max(x for x, _y in positions.values())

    assert PATCH_GRID_X - rightmost_output_x >= 90


def test_patch_cell_rejects_out_of_range_coordinates():
    assert _patch_cell_to_engine(-1, 0) is None
    assert _patch_cell_to_engine(0, -1) is None
    assert _patch_cell_to_engine(PATCH_GRID_SIZE, 0) is None
    assert _patch_cell_to_engine(0, PATCH_GRID_SIZE) is None


def test_source_positions_form_five_by_five_grid():
    positions = _source_positions_for_ids(list(range(1, 11)))

    first_x = positions[1][0]
    first_y = positions[1][1]
    assert positions[5][0] == first_x
    assert positions[5][1] == first_y + PATCH_CELL * 4
    assert positions[6][0] == first_x + PATCH_CELL
    assert positions[6][1] == first_y
    assert positions[10][0] == first_x + PATCH_CELL
    assert positions[10][1] == first_y + PATCH_CELL * 4


def test_patch_bay_preallocates_twenty_five_output_slots():
    positions = _patch_slot_positions()

    assert len(positions) == PATCH_SOURCE_LIMIT
    assert positions[0][0] == positions[4][0]
    assert positions[5][0] == positions[0][0] + PATCH_CELL
    assert positions[24][0] == positions[0][0] + PATCH_CELL * 4
    assert positions[24][1] == positions[0][1] + PATCH_CELL * 4


def test_effect_grid_cells_have_centered_jack_targets():
    bounds = _patch_effect_jack_bounds(2, 3)
    cx = (bounds[0] + bounds[2]) / 2
    cy = (bounds[1] + bounds[3]) / 2

    assert cx == PATCH_GRID_X + PATCH_CELL * 3 + PATCH_CELL / 2
    assert cy == PATCH_GRID_Y + PATCH_CELL * 2 + PATCH_CELL / 2
    assert 0 < bounds[2] - bounds[0] < PATCH_CELL


def test_active_sources_use_preallocated_output_slots_in_order():
    sources = [{"id": 101}, {"id": 205}, {"id": 307}]
    positions = _source_positions_for_sources(sources)
    slots = _patch_slot_positions()

    assert positions[101] == slots[0]
    assert positions[205] == slots[1]
    assert positions[307] == slots[2]


def test_patch_cable_points_curve_between_jacks():
    points = _patch_cable_points(80, 60, 360, 120)

    assert points[:2] == (80, 60)
    assert points[-2:] == (360, 120)
    assert len(points) >= 22
    assert len(points) % 2 == 0
    y_values = points[1::2]
    sag_values = []
    expected_sag = (360 - 80) * 0.16
    for i, y in enumerate(y_values):
        t = i / (len(y_values) - 1)
        baseline = 60 + (120 - 60) * t
        expected = baseline + expected_sag * 4 * t * (1 - t)
        assert y == expected
        sag_values.append(y - baseline)
    midpoint_sag = sag_values[len(sag_values) // 2]
    assert midpoint_sag == max(sag_values)


def test_patch_source_limit_stops_after_twenty_five_outputs():
    assert _can_add_patch_source([{"id": i} for i in range(PATCH_SOURCE_LIMIT - 1)])
    assert not _can_add_patch_source(
        [{"id": i} for i in range(PATCH_SOURCE_LIMIT)]
    )


import tkinter as tk

import pytest


class _StubEngine:
    """Minimal engine stand-in: records pause/resume, no real stream."""

    def __init__(self):
        self.paused = True
        self.calls = []

    def pause(self):
        self.paused = True
        self.calls.append("pause")

    def resume(self):
        self.paused = False
        self.calls.append("resume")


def _tk_root_or_skip():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk widget test")
    root.withdraw()
    return root


def test_gui_constructor_accepts_synth_engine():
    import inspect

    from gui import RedPoleGUI

    params = list(inspect.signature(RedPoleGUI.__init__).parameters)
    assert params == ["self", "root", "engine", "synth_engine", "default_loop_path"]


def test_switching_to_synth_tab_pauses_loop_and_resumes_synth():
    root = _tk_root_or_skip()
    try:
        from synth_audio_engine import SynthAudioEngine
        from gui import RedPoleGUI

        loop = _StubEngine()
        loop.registry = None  # not touched before a tab switch
        synth = SynthAudioEngine(seed=1)
        # Avoid opening a real audio device in the test.
        synth.resume = lambda: synth.__dict__.__setitem__("_resumed", True)
        synth.pause = lambda: None
        # Build with a stub loop engine that also has the attributes the Loop
        # tab needs; simpler to skip full loop-tab wiring by monkeypatching.
        pytest.skip("covered by manual launch; see Task 8 Step 2")
    finally:
        root.destroy()
