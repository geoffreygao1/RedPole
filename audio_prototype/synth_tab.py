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

from gui import (
    PICKER_H,
    PICKER_W,
    _patch_cable_points,
    _picker_coords_to_hsv,
    _random_scan_values,
)

WAVEFORM_WINDOW_SAMPLES = 4096
REFRESH_MS = 50


class SynthTab:
    """Drag-cable patch bay for the SoundscapeEngine: two 5x5 jack grids
    (sources left, transforms right). Drag a cable from a source jack to a
    transform jack to create a voice; release off the transform grid for a
    source-only voice. Mirrors the Loop tab's cable interaction."""

    def __init__(self, parent, synth_engine):
        self.parent = parent
        self.engine = synth_engine
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="both", expand=True)
        self.refresh_ms = REFRESH_MS

        # patch_id -> {color, source_cell, transform_cell, bpm, source_id, transform_id}
        self._patches = {}
        self._patch_rows = {}
        self._drag_source_cell = None
        self._drag_pos = None

        self.hue_var = tk.DoubleVar(value=0.0)
        self.sat_var = tk.DoubleVar(value=0.75)
        self.val_var = tk.DoubleVar(value=0.64)
        self.bpm_var = tk.StringVar(value="70")
        self.root_var = tk.StringVar()

        self._build_controls()
        self._build_bay()
        self._build_patch_list()
        self._build_waveform()
        self._schedule_refresh()

    # ---------- left controls ----------

    def _build_controls(self):
        panel = ttk.Frame(self.frame)
        panel.grid(row=0, column=0, sticky="nw", padx=8, pady=8)

        colorbox = ttk.LabelFrame(panel, text="Finger color + BPM")
        colorbox.pack(fill="x")
        self.picker = tk.Canvas(
            colorbox, width=PICKER_W, height=PICKER_H, highlightthickness=1, cursor="cross"
        )
        self.picker.grid(row=0, column=0, columnspan=3, sticky="w")
        self._picker_image = self._build_picker_image()
        self.picker.create_image(0, 0, anchor="nw", image=self._picker_image)
        self._marker = self.picker.create_oval(0, 0, 0, 0, outline="white", width=2)
        self.picker.bind("<Button-1>", lambda e: self._set_pick(e.x, e.y))
        self.picker.bind("<B1-Motion>", lambda e: self._set_pick(e.x, e.y))
        ttk.Label(colorbox, text="BPM").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(colorbox, textvariable=self.bpm_var, width=8).grid(
            row=1, column=1, sticky="w", pady=(6, 0)
        )
        self.swatch = tk.Canvas(colorbox, width=40, height=40, highlightthickness=1)
        self.swatch.grid(row=1, column=2, padx=8)
        ttk.Button(colorbox, text="Random", command=self._on_random).grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )

        rootbox = ttk.LabelFrame(panel, text="Harmonic root")
        rootbox.pack(fill="x", pady=(8, 0))
        labels = [label for label, _midi in ROOT_NOTE_CHOICES]
        self._root_by_label = {label: midi for label, midi in ROOT_NOTE_CHOICES}
        current = next(
            label for label, midi in ROOT_NOTE_CHOICES if midi == self.engine.root_midi
        )
        self.root_var.set(current)
        ttk.Combobox(
            rootbox, textvariable=self.root_var, values=labels, state="readonly", width=6
        ).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(rootbox, text="Apply (clears patches)", command=self._on_apply_root).grid(
            row=0, column=1, padx=4
        )

        ttk.Button(panel, text="Load Sample...", command=self._on_load_sample).pack(
            fill="x", pady=(8, 0)
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
        self._patches.clear()
        self._redraw_bay()

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

    # ---------- patch bay ----------

    def _build_bay(self):
        box = ttk.LabelFrame(
            self.frame, text="Patch bay - drag a source jack to a transform jack"
        )
        box.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        self.frame.columnconfigure(1, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.bay = tk.Canvas(
            box, width=SYNTH_CANVAS_W, height=SYNTH_CANVAS_H,
            bg="#161616", highlightthickness=0,
        )
        self.bay.pack(fill="both", expand=True)
        self.bay.bind("<Button-1>", self._on_press)
        self.bay.bind("<B1-Motion>", self._on_drag)
        self.bay.bind("<ButtonRelease-1>", self._on_release)
        self._redraw_bay()

    def _draw_grid(self, origin, rows, title):
        ox, oy = origin
        c = self.bay
        c.create_text(ox, oy - 22, text=title, anchor="w", fill="#bdbdbd",
                      font=("TkDefaultFont", 9))
        for r, name in enumerate(rows):
            cy = oy + r * SYNTH_CELL + SYNTH_CELL / 2
            c.create_text(ox - 10, cy, text=name, anchor="e", fill="#d5d5d5",
                          font=("TkDefaultFont", 9))
            for col in range(SYNTH_GRID_SIZE):
                x0 = ox + col * SYNTH_CELL
                y0 = oy + r * SYNTH_CELL
                c.create_rectangle(x0, y0, x0 + SYNTH_CELL, y0 + SYNTH_CELL,
                                   outline="#444", fill="#222")
                c.create_text(x0 + 8, y0 + 10, text=VARIANT_LABELS[col],
                              fill="#808080", font=("TkDefaultFont", 8))

    def _draw_jacks(self, origin, filled):
        for r in range(SYNTH_GRID_SIZE):
            for col in range(SYNTH_GRID_SIZE):
                cx, cy = _cell_center(origin, r, col)
                color = filled.get((r, col), "#3a3a3a")
                self.bay.create_oval(
                    cx - SYNTH_JACK_RADIUS, cy - SYNTH_JACK_RADIUS,
                    cx + SYNTH_JACK_RADIUS, cy + SYNTH_JACK_RADIUS,
                    outline="#8a8a8a", fill=color, width=2,
                )

    def _redraw_bay(self):
        c = self.bay
        c.delete("all")
        self._draw_grid(SYNTH_SOURCE_ORIGIN, SYNTH_SOURCE_ROWS, "sources")
        self._draw_grid(SYNTH_TRANSFORM_ORIGIN, SYNTH_TRANSFORM_ROWS, "transforms")

        source_fill = {}
        transform_fill = {}
        for p in self._patches.values():
            source_fill[p["source_cell"]] = p["color"]
            if p["transform_cell"] is not None:
                transform_fill[p["transform_cell"]] = p["color"]

        # cables under the jacks
        for p in self._patches.values():
            sx, sy = source_cell_center(*p["source_cell"])
            if p["transform_cell"] is not None:
                tx, ty = transform_cell_center(*p["transform_cell"])
                c.create_line(*_patch_cable_points(sx, sy, tx, ty),
                              fill=p["color"], width=3)
            else:
                c.create_line(sx, sy, sx + 18, sy, fill=p["color"], width=3)

        if self._drag_source_cell is not None and self._drag_pos is not None:
            sx, sy = source_cell_center(*self._drag_source_cell)
            c.create_line(*_patch_cable_points(sx, sy, *self._drag_pos),
                          fill=self._color_hex(), width=2, dash=(4, 3))

        self._draw_jacks(SYNTH_SOURCE_ORIGIN, source_fill)
        self._draw_jacks(SYNTH_TRANSFORM_ORIGIN, transform_fill)

    def _on_press(self, event):
        self._drag_source_cell = source_cell_at(event.x, event.y)
        self._drag_pos = None

    def _on_drag(self, event):
        if self._drag_source_cell is None:
            return
        self._drag_pos = (event.x, event.y)
        self._redraw_bay()

    def _on_release(self, event):
        if self._drag_source_cell is None:
            return
        source_cell = self._drag_source_cell
        transform_cell = transform_cell_at(event.x, event.y)
        self._drag_source_cell = None
        self._drag_pos = None
        self._connect(source_cell, transform_cell)

    def _connect(self, source_cell, transform_cell):
        if len(self._patches) >= SYNTH_PATCH_LIMIT:
            messagebox.showinfo("Patch bay full", f"Maximum voices reached ({SYNTH_PATCH_LIMIT}).")
            self._redraw_bay()
            return
        bpm = parse_bpm(self.bpm_var.get())
        if bpm is None:
            messagebox.showerror("Invalid BPM", f"BPM must be a number ({self.bpm_var.get()!r}).")
            self._redraw_bay()
            return
        source_id = source_preset_id(*source_cell)
        transform_id = (
            transform_preset_id(*transform_cell) if transform_cell is not None else None
        )
        color = self._color_hex()
        pid = self.engine.connect_patch(
            self.hue_var.get(), self.sat_var.get(), self.val_var.get(),
            bpm, source_id, transform_id,
        )
        self._patches[pid] = {
            "color": color,
            "source_cell": source_cell,
            "transform_cell": transform_cell,
            "bpm": bpm,
            "source_id": source_id,
            "transform_id": transform_id,
        }
        self._add_patch_row(pid, bpm, source_id, transform_id, color)
        self._redraw_bay()

    # ---------- patch list ----------

    def _build_patch_list(self):
        box = ttk.LabelFrame(self.frame, text="Active patches")
        box.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        self.frame.rowconfigure(1, weight=1)
        canvas = tk.Canvas(box, height=120, highlightthickness=0)
        scrollbar = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
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
        self._patches.pop(pid, None)
        row = self._patch_rows.pop(pid, None)
        if row is not None:
            row.destroy()
        self._redraw_bay()

    # ---------- waveform (lightweight Tk canvas) ----------

    def _build_waveform(self):
        box = ttk.LabelFrame(self.frame, text="Waveform")
        box.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        self.wave = tk.Canvas(box, height=110, bg="#0b0b0b", highlightthickness=0)
        self.wave.pack(fill="both", expand=True)
        self.wave_line = self.wave.create_line(0, 0, 0, 0, fill="#4da6ff", width=1)

    def _draw_wave(self):
        data = self.engine.visual_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        w = max(2, self.wave.winfo_width())
        h = max(2, self.wave.winfo_height())
        n = WAVEFORM_POINTS
        seg = max(1, len(data) // n)
        pts = []
        for i in range(n):
            chunk = data[i * seg:(i + 1) * seg]
            if len(chunk) == 0:
                v = 0.0
            else:
                v = float(chunk[int(np.argmax(np.abs(chunk)))])
            x = i / (n - 1) * w
            y = h / 2 - v * (h / 2 - 2)
            pts.extend((x, y))
        if len(pts) >= 4:
            self.wave.coords(self.wave_line, *pts)

    def _schedule_refresh(self):
        # Only redraw while this tab is actually visible -- keeps GIL holds
        # tiny so they can't starve the audio producer thread.
        if self.frame.winfo_viewable():
            self._draw_wave()
        self.parent.after(self.refresh_ms, self._schedule_refresh)
