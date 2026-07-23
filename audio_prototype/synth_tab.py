"""Synth tab: two 5x5 preset grids (source + transform) driving a
SynthAudioEngine. This module holds the pure grid/selection/parsing helpers
(unit-tested without Tk) and the SynthTab widget builder (added in a later
task)."""

from soundscape_sources import SOURCE_PRESETS
from soundscape_transforms import TRANSFORM_PRESETS

SYNTH_GRID_SIZE = 5
SYNTH_SOURCE_ROWS = ("additive", "granular", "resonant", "noise", "texture")
SYNTH_TRANSFORM_ROWS = ("delay", "spectral", "pitch", "grainfx", "spatial")

BPM_MIN = 20.0
BPM_MAX = 300.0

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def _grouped(presets, rows):
    by_engine = {}
    for p in presets:
        by_engine.setdefault(p["engine"], []).append(p["id"])
    return [tuple(by_engine[row]) for row in rows]


_SOURCE_GRID = _grouped(SOURCE_PRESETS, SYNTH_SOURCE_ROWS)
_TRANSFORM_GRID = _grouped(TRANSFORM_PRESETS, SYNTH_TRANSFORM_ROWS)


def source_preset_id(row, col):
    return _SOURCE_GRID[row][col]


def transform_preset_id(row, col):
    return _TRANSFORM_GRID[row][col]


def _midi_label(midi):
    return f"{_NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


ROOT_NOTE_CHOICES = [(_midi_label(m), m) for m in range(48, 85)]  # C3..C6


def next_selection(current, clicked):
    """Single-select toggle: clicking a new cell selects it; clicking the
    currently-selected cell clears the selection."""
    return None if current == clicked else clicked


def parse_bpm(text):
    try:
        bpm = float(text)
    except (TypeError, ValueError):
        return None
    return float(min(BPM_MAX, max(BPM_MIN, bpm)))
