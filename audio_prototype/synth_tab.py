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


# ---- patch-bay geometry (pure; unit-tested without Tk) ----

SYNTH_CANVAS_W = 980
SYNTH_CANVAS_H = 380
SYNTH_CELL = 56
SYNTH_JACK_RADIUS = 9
SYNTH_SOURCE_ORIGIN = (90, 60)       # (x, y) top-left of the source grid
SYNTH_TRANSFORM_ORIGIN = (620, 60)   # (x, y) top-left of the transform grid
SYNTH_PATCH_LIMIT = 25
WAVEFORM_POINTS = 480
VARIANT_LABELS = ("I", "II", "III", "IV", "V")   # per-column preset variant labels


def _cell_center(origin, row, col):
    ox, oy = origin
    return (ox + col * SYNTH_CELL + SYNTH_CELL / 2, oy + row * SYNTH_CELL + SYNTH_CELL / 2)


def _cell_at(origin, x, y):
    ox, oy = origin
    if x < ox or y < oy:
        return None
    col = int((x - ox) // SYNTH_CELL)
    row = int((y - oy) // SYNTH_CELL)
    if 0 <= row < SYNTH_GRID_SIZE and 0 <= col < SYNTH_GRID_SIZE:
        return (row, col)
    return None


def source_cell_center(row, col):
    return _cell_center(SYNTH_SOURCE_ORIGIN, row, col)


def transform_cell_center(row, col):
    return _cell_center(SYNTH_TRANSFORM_ORIGIN, row, col)


def source_cell_at(x, y):
    return _cell_at(SYNTH_SOURCE_ORIGIN, x, y)


def transform_cell_at(x, y):
    return _cell_at(SYNTH_TRANSFORM_ORIGIN, x, y)


import colorsys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from gui import PICKER_H, PICKER_W, _picker_coords_to_hsv, _random_scan_values

WAVEFORM_WINDOW_SAMPLES = 4096
WAVEFORM_FIGSIZE = (7.2, 1.7)
REFRESH_MS = 50
SYNTH_CELL_W = 6  # button width in text units


class SynthTab:
    """Builds the Synth-tab UI: two 5x5 preset grids, a finger-color picker,
    BPM entry, root-note selector, Connect button, active-patch list, a
    Load Sample button, and a waveform view fed by the SynthAudioEngine."""

    def __init__(self, parent, synth_engine):
        self.parent = parent
        self.engine = synth_engine
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="both", expand=True)
        self.refresh_ms = REFRESH_MS

        self.selected_source = None
        self.selected_transform = None
        self.source_cells = {}
        self.transform_cells = {}
        self._patch_rows = {}

        self.hue_var = tk.DoubleVar(value=0.0)
        self.sat_var = tk.DoubleVar(value=0.75)
        self.val_var = tk.DoubleVar(value=0.64)
        self.bpm_var = tk.StringVar(value="70")
        self.root_var = tk.StringVar()

        self._build_grids()
        self._build_color_controls()
        self._build_root_control()
        self._build_action_controls()
        self._build_patch_list()
        self._build_waveform()
        self._schedule_refresh()

    # ---------- grids ----------

    def _build_grids(self):
        wrapper = ttk.Frame(self.frame)
        wrapper.grid(row=0, column=0, columnspan=2, sticky="nw", padx=8, pady=8)
        self._build_one_grid(
            wrapper, 0, "Sources", SYNTH_SOURCE_ROWS, self.source_cells,
            self._select_source,
        )
        self._build_one_grid(
            wrapper, 1, "Transforms (optional)", SYNTH_TRANSFORM_ROWS,
            self.transform_cells, self._select_transform,
        )

    def _build_one_grid(self, parent, col, title, rows, cells, on_click):
        box = ttk.LabelFrame(parent, text=title)
        box.grid(row=0, column=col, sticky="nw", padx=(0, 16))
        for c in range(SYNTH_GRID_SIZE):
            ttk.Label(box, text=str(c + 1)).grid(row=0, column=c + 1, padx=1)
        for r, name in enumerate(rows):
            ttk.Label(box, text=name).grid(row=r + 1, column=0, sticky="e", padx=(0, 4))
            for c in range(SYNTH_GRID_SIZE):
                btn = tk.Button(
                    box, width=SYNTH_CELL_W, relief="raised",
                    command=lambda rr=r, cc=c: on_click(rr, cc),
                )
                btn.grid(row=r + 1, column=c + 1, padx=1, pady=1)
                cells[(r, c)] = btn

    def _paint_grid(self, cells, selected):
        for (r, c), btn in cells.items():
            btn.configure(
                relief="sunken" if (r, c) == selected else "raised",
                bg="#ffd27f" if (r, c) == selected else "SystemButtonFace",
            )

    def _select_source(self, row, col):
        self.selected_source = next_selection(self.selected_source, (row, col))
        self._paint_grid(self.source_cells, self.selected_source)

    def _select_transform(self, row, col):
        self.selected_transform = next_selection(self.selected_transform, (row, col))
        self._paint_grid(self.transform_cells, self.selected_transform)

    # ---------- color ----------

    def _build_color_controls(self):
        frame = ttk.LabelFrame(self.frame, text="Finger color + BPM")
        frame.grid(row=1, column=0, sticky="nw", padx=8, pady=(0, 8))
        self.picker = tk.Canvas(
            frame, width=PICKER_W, height=PICKER_H, highlightthickness=1, cursor="cross"
        )
        self.picker.grid(row=0, column=0, columnspan=3, sticky="w")
        self._picker_image = self._build_picker_image()
        self.picker.create_image(0, 0, anchor="nw", image=self._picker_image)
        self._marker = self.picker.create_oval(0, 0, 0, 0, outline="white", width=2)
        self.picker.bind("<Button-1>", lambda e: self._set_pick(e.x, e.y))
        self.picker.bind("<B1-Motion>", lambda e: self._set_pick(e.x, e.y))

        ttk.Label(frame, text="BPM").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(frame, textvariable=self.bpm_var, width=8).grid(
            row=1, column=1, sticky="w", pady=(6, 0)
        )
        self.swatch = tk.Canvas(frame, width=40, height=40, highlightthickness=1)
        self.swatch.grid(row=1, column=2, padx=8)
        ttk.Button(frame, text="Random", command=self._on_random).grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )
        self._set_pick(PICKER_W // 2, PICKER_H // 2)

    def _build_picker_image(self):
        img = tk.PhotoImage(width=PICKER_W, height=PICKER_H)
        rows = []
        for y in range(PICKER_H):
            row = []
            for x in range(PICKER_W):
                hue, sat, val = _picker_coords_to_hsv(x, y)
                r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
                row.append(f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}")
            rows.append("{" + " ".join(row) + "}")
        img.put(" ".join(rows))
        return img

    def _set_pick(self, x, y):
        x = int(min(PICKER_W - 1, max(0, x)))
        y = int(min(PICKER_H - 1, max(0, y)))
        hue, sat, val = _picker_coords_to_hsv(x, y)
        self.hue_var.set(hue)
        self.sat_var.set(sat)
        self.val_var.set(val)
        self.picker.coords(self._marker, x - 5, y - 5, x + 5, y + 5)
        self.swatch.configure(bg=self._color_hex())

    def _color_hex(self):
        r, g, b = colorsys.hsv_to_rgb(
            self.hue_var.get(), self.sat_var.get(), self.val_var.get()
        )
        return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

    def _on_random(self):
        x, y, bpm = _random_scan_values()
        self._set_pick(x, y)
        self.bpm_var.set(f"{bpm:.0f}")

    # ---------- root note ----------

    def _build_root_control(self):
        frame = ttk.LabelFrame(self.frame, text="Harmonic root")
        frame.grid(row=1, column=1, sticky="nw", padx=8, pady=(0, 8))
        labels = [label for label, _midi in ROOT_NOTE_CHOICES]
        self._root_by_label = {label: midi for label, midi in ROOT_NOTE_CHOICES}
        current = next(
            label for label, midi in ROOT_NOTE_CHOICES if midi == self.engine.root_midi
        )
        self.root_var.set(current)
        ttk.Combobox(
            frame, textvariable=self.root_var, values=labels, state="readonly", width=6
        ).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(frame, text="Apply (clears patches)", command=self._on_apply_root).grid(
            row=0, column=1, padx=4
        )

    def _on_apply_root(self):
        if self.engine.active_patches() and not messagebox.askokcancel(
            "Change root note",
            "Changing the harmonic root rebuilds the engine and removes all "
            "active patches. Continue?",
        ):
            return
        self.engine.set_root_midi(self._root_by_label[self.root_var.get()])
        for row in list(self._patch_rows.values()):
            row.destroy()
        self._patch_rows.clear()

    # ---------- actions ----------

    def _build_action_controls(self):
        frame = ttk.Frame(self.frame)
        frame.grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))
        ttk.Button(frame, text="Connect patch", command=self._on_connect).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(frame, text="Load Sample...", command=self._on_load_sample).grid(
            row=0, column=1
        )

    def _on_connect(self):
        if self.selected_source is None:
            if self.parent.winfo_viewable():
                messagebox.showinfo("No source", "Select a source preset first.")
            return
        bpm = parse_bpm(self.bpm_var.get())
        if bpm is None:
            messagebox.showerror("Invalid BPM", f"BPM must be a number ({self.bpm_var.get()!r}).")
            return
        source_id = source_preset_id(*self.selected_source)
        transform_id = (
            transform_preset_id(*self.selected_transform)
            if self.selected_transform is not None
            else None
        )
        pid = self.engine.connect_patch(
            self.hue_var.get(), self.sat_var.get(), self.val_var.get(),
            bpm, source_id, transform_id,
        )
        self._add_patch_row(pid, bpm, source_id, transform_id, self._color_hex())

    def _on_load_sample(self):
        path = filedialog.askopenfilename(
            filetypes=[("Audio files", "*.wav *.mp3"), ("WAV files", "*.wav")]
        )
        if not path:
            return
        try:
            self.engine.load_sample(path)
        except Exception as exc:
            messagebox.showerror("Failed to load sample", str(exc))

    # ---------- patch list ----------

    def _build_patch_list(self):
        frame = ttk.LabelFrame(self.frame, text="Active patches")
        frame.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        self.frame.rowconfigure(3, weight=1)
        self.frame.columnconfigure(0, weight=1)
        canvas = tk.Canvas(frame, height=140, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        self.patch_list_frame = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=self.patch_list_frame, anchor="nw")
        self.patch_list_frame.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _add_patch_row(self, pid, bpm, source_id, transform_id, color_hex):
        row = ttk.Frame(self.patch_list_frame)
        row.pack(fill="x", pady=2)
        tk.Canvas(row, width=16, height=16, highlightthickness=1, bg=color_hex).pack(
            side="left", padx=(0, 6)
        )
        label = f"#{pid}  {source_id}"
        if transform_id:
            label += f" -> {transform_id}"
        label += f"  (BPM {bpm:.0f})"
        ttk.Label(row, text=label).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Remove", command=lambda: self._remove_patch(pid)).pack(
            side="right"
        )
        self._patch_rows[pid] = row

    def _remove_patch(self, pid):
        self.engine.disconnect_patch(pid)
        row = self._patch_rows.pop(pid, None)
        if row is not None:
            row.destroy()

    # ---------- waveform ----------

    def _build_waveform(self):
        frame = ttk.LabelFrame(self.frame, text="Waveform")
        frame.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        fig = Figure(figsize=WAVEFORM_FIGSIZE)
        self.ax = fig.add_subplot(111)
        (self.line,) = self.ax.plot(
            np.zeros(WAVEFORM_WINDOW_SAMPLES), color="tab:blue", linewidth=1.2
        )
        self.ax.set_ylim(-1.05, 1.05)
        self.ax.set_xticks([])
        self.canvas = FigureCanvasTkAgg(fig, master=frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _schedule_refresh(self):
        data = self.engine.visual_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        self.line.set_ydata(data)
        self.canvas.draw_idle()
        self.parent.after(self.refresh_ms, self._schedule_refresh)
