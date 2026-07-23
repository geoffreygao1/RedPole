from soundscape_sources import SOURCE_PRESETS
from soundscape_transforms import TRANSFORM_PRESETS
from synth_tab import (
    BPM_MAX,
    BPM_MIN,
    ROOT_NOTE_CHOICES,
    SYNTH_GRID_SIZE,
    SYNTH_SOURCE_ROWS,
    SYNTH_TRANSFORM_ROWS,
    next_selection,
    parse_bpm,
    source_preset_id,
    transform_preset_id,
)


def test_source_grid_covers_all_25_source_presets():
    ids = {
        source_preset_id(r, c)
        for r in range(SYNTH_GRID_SIZE)
        for c in range(SYNTH_GRID_SIZE)
    }
    assert ids == {p["id"] for p in SOURCE_PRESETS}
    assert len(ids) == 25


def test_transform_grid_covers_all_25_transform_presets():
    ids = {
        transform_preset_id(r, c)
        for r in range(SYNTH_GRID_SIZE)
        for c in range(SYNTH_GRID_SIZE)
    }
    assert ids == {p["id"] for p in TRANSFORM_PRESETS}
    assert len(ids) == 25


def test_grid_rows_map_to_declared_engines():
    assert SYNTH_SOURCE_ROWS == ("additive", "granular", "resonant", "noise", "texture")
    assert SYNTH_TRANSFORM_ROWS == ("delay", "spectral", "pitch", "grainfx", "spatial")
    # every id in a source row belongs to that row's engine
    by_engine = {}
    for p in SOURCE_PRESETS:
        by_engine.setdefault(p["engine"], []).append(p["id"])
    for r, engine in enumerate(SYNTH_SOURCE_ROWS):
        row_ids = [source_preset_id(r, c) for c in range(SYNTH_GRID_SIZE)]
        assert row_ids == by_engine[engine]


def test_root_note_choices_include_default_d4():
    assert ("D4", 62) in ROOT_NOTE_CHOICES
    for label, midi in ROOT_NOTE_CHOICES:
        assert isinstance(label, str)
        assert isinstance(midi, int)


def test_next_selection_single_select_toggle():
    assert next_selection(None, (0, 0)) == (0, 0)
    assert next_selection((0, 0), (1, 2)) == (1, 2)
    assert next_selection((1, 2), (1, 2)) is None  # click selected cell -> clear


def test_parse_bpm_clamps_and_rejects_garbage():
    assert parse_bpm("90") == 90.0
    assert parse_bpm("5") == BPM_MIN
    assert parse_bpm("9000") == BPM_MAX
    assert parse_bpm("not a number") is None
    assert parse_bpm("") is None


import tkinter as tk

import pytest

from synth_audio_engine import SynthAudioEngine
from synth_tab import SYNTH_GRID_SIZE, SynthTab


def _tk_root_or_skip():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk widget test")
    root.withdraw()
    return root


def test_synth_tab_builds_two_grids_of_buttons():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        assert len(tab.source_cells) == SYNTH_GRID_SIZE * SYNTH_GRID_SIZE
        assert len(tab.transform_cells) == SYNTH_GRID_SIZE * SYNTH_GRID_SIZE
    finally:
        root.destroy()


def test_synth_tab_connect_adds_a_patch():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        tab._select_source(0, 1)          # additive_2
        tab.bpm_var.set("90")
        tab._on_connect()
        assert len(eng.active_patches()) == 1
        assert eng.active_patches()[0]["source_preset"] == "additive_2"
    finally:
        root.destroy()


def test_synth_tab_connect_without_source_is_noop():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        tab.bpm_var.set("90")
        tab._on_connect()  # no source selected
        assert eng.active_patches() == []
    finally:
        root.destroy()

from synth_tab import (
    SYNTH_GRID_SIZE as _GRID,
    source_cell_at,
    source_cell_center,
    transform_cell_at,
    transform_cell_center,
)


def test_source_cell_center_round_trips_through_cell_at():
    for r in range(_GRID):
        for c in range(_GRID):
            cx, cy = source_cell_center(r, c)
            assert source_cell_at(cx, cy) == (r, c)


def test_transform_cell_center_round_trips_through_cell_at():
    for r in range(_GRID):
        for c in range(_GRID):
            cx, cy = transform_cell_center(r, c)
            assert transform_cell_at(cx, cy) == (r, c)


def test_cell_at_returns_none_outside_grids():
    assert source_cell_at(-50, -50) is None
    assert transform_cell_at(0, 0) is None            # left of the transform grid
    assert source_cell_at(*transform_cell_center(0, 0)) is None  # transform area is not source


def test_source_grid_is_left_of_transform_grid():
    assert source_cell_center(0, _GRID - 1)[0] < transform_cell_center(0, 0)[0]
