import colorsys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from modulation import (
    FINGER_HUE_MAX,
    FINGER_HUE_MIN,
    FINGER_SAT_MAX,
    FINGER_SAT_MIN,
    FINGER_VAL_MAX,
    FINGER_VAL_MIN,
    MAX_BLOOM_DEPTH,
    MAX_WARBLE_DEPTH,
    clamp,
)

WAVEFORM_WINDOW_SAMPLES = 4096
WAVEFORM_FIGSIZE = (7.2, 1.7)
REFRESH_MS = 50
LEFT_COLUMN_GRID = {
    "row": 0,
    "column": 0,
    "rowspan": 2,
    "sticky": "nsw",
    "padx": (8, 0),
    "pady": 8,
}
LEFT_STACK_ROWS = {
    "scan_input": 0,
    "audition": 1,
    "scan_sources": 2,
}
BPM_MIN = 20.0
BPM_MAX = 300.0
RANDOM_BPM_MIN = 45.0
RANDOM_BPM_MAX = 180.0
PICKER_W = 220
PICKER_H = 120
PATCH_GRID_SIZE = 5
PATCH_ROW_ENGINES = ("microloop", "granules", "glitch", "multidelay", "reverb")
PATCH_COL_LABELS = ("I", "II", "III", "IV", "V")
PATCH_CANVAS_W = 960
PATCH_CANVAS_H = 440
PATCH_SOURCE_X = 100
PATCH_GRID_X = 560
PATCH_GRID_Y = 70
PATCH_CELL = 58
PATCH_SOURCE_TOP = 70
PATCH_SOURCE_COLUMN_SIZE = 8
PATCH_SOURCE_COLUMN_GAP = 76
PATCH_SOURCE_LIMIT = 25


def _picker_coords_to_hsv(x, y, w=PICKER_W, h=PICKER_H):
    """Map picker canvas coordinates to the finger-scan color gamut.

    x sweeps hue from red to orange; y stays bright enough that the
    orange side does not collapse into brown.
    """
    fx = clamp(x / (w - 1), 0.0, 1.0)
    fy = clamp(y / (h - 1), 0.0, 1.0)
    hue = FINGER_HUE_MIN + (FINGER_HUE_MAX - FINGER_HUE_MIN) * fx
    val = FINGER_VAL_MAX - (FINGER_VAL_MAX - FINGER_VAL_MIN) * fy
    sat = FINGER_SAT_MAX - (FINGER_SAT_MAX - FINGER_SAT_MIN) * fy
    return hue, sat, val


def _random_scan_values(rng=None):
    rng = np.random.default_rng() if rng is None else rng
    x = int(rng.integers(0, PICKER_W))
    y = int(rng.integers(0, PICKER_H))
    bpm = float(rng.uniform(RANDOM_BPM_MIN, RANDOM_BPM_MAX))
    return x, y, bpm


def _patch_cell_to_engine(row, col):
    if not (0 <= row < PATCH_GRID_SIZE and 0 <= col < PATCH_GRID_SIZE):
        return None
    return PATCH_ROW_ENGINES[row]


def _source_positions_for_ids(source_ids):
    return {
        source_id: position
        for source_id, position in zip(source_ids, _patch_slot_positions())
    }


def _source_positions_for_sources(sources):
    return _source_positions_for_ids([source["id"] for source in sources])


def _patch_slot_positions():
    usable_h = max(1, PATCH_CANVAS_H - PATCH_SOURCE_TOP - 24)
    row_count = PATCH_SOURCE_COLUMN_SIZE
    gap = usable_h / max(1, row_count - 1)
    positions = []
    for i in range(PATCH_SOURCE_LIMIT):
        col = i // PATCH_SOURCE_COLUMN_SIZE
        row = i % PATCH_SOURCE_COLUMN_SIZE
        positions.append((
            PATCH_SOURCE_X + col * PATCH_SOURCE_COLUMN_GAP,
            PATCH_SOURCE_TOP + row * gap,
        ))
    return positions


def _patch_cable_points(x1, y1, x2, y2):
    dx = x2 - x1
    sag = min(72.0, max(24.0, abs(dx) * 0.16))
    points = []
    steps = 12
    for i in range(steps + 1):
        t = i / steps
        x = x1 + dx * t
        baseline = y1 + (y2 - y1) * t
        y = baseline + sag * 4.0 * t * (1.0 - t)
        points.extend((x, y))
    return tuple(points)


def _can_add_patch_source(sources):
    return len(sources) < PATCH_SOURCE_LIMIT


class RedPoleGUI:
    def __init__(self, root, engine, default_loop_path):
        self.root = root
        self.engine = engine
        self.root.title("RedPole Audio Prototype")
        self._layer_rows = {}
        self._source_colors = {}
        self._drag_source_id = None
        self._drag_line = None

        self.hue_var = tk.DoubleVar(value=0.0)
        self.sat_var = tk.DoubleVar(value=0.75)
        self.val_var = tk.DoubleVar(value=0.64)
        self.bpm_var = tk.StringVar(value="70")
        self.wet_dry_var = tk.DoubleVar(value=self.engine.wet_dry)

        self._build_layout_frames()
        self._build_controls()
        self._build_audition_controls()
        self._build_layer_list()
        self._build_waveform()
        self._build_patch_bay()
        self._load_initial_loop(default_loop_path)
        self._schedule_refresh()

    def _build_layout_frames(self):
        self.left_column = ttk.Frame(self.root)
        self.left_column.grid(**LEFT_COLUMN_GRID)
        self.left_column.columnconfigure(0, weight=1)
        self.left_column.rowconfigure(LEFT_STACK_ROWS["scan_sources"], weight=1)

    # ---------- controls ----------

    def _build_controls(self):
        frame = ttk.LabelFrame(self.left_column, text="Scan Input")
        frame.grid(
            row=LEFT_STACK_ROWS["scan_input"],
            column=0,
            sticky="new",
            pady=(0, 8),
        )

        ttk.Button(frame, text="Load Loop...", command=self._on_load_loop).grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8)
        )

        self.pause_button = ttk.Button(
            frame, text="Play", command=self._on_toggle_playback, width=7
        )
        self.pause_button.grid(row=1, column=0, columnspan=3, sticky="ew")

        ttk.Label(frame, text="Finger color").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(6, 2)
        )
        self.picker = tk.Canvas(
            frame, width=PICKER_W, height=PICKER_H, highlightthickness=1, cursor="cross"
        )
        self.picker.grid(row=3, column=0, columnspan=3, sticky="w")
        self._picker_image = self._build_picker_image()
        self.picker.create_image(0, 0, anchor="nw", image=self._picker_image)
        self._marker = self.picker.create_oval(
            0, 0, 0, 0, outline="white", width=2
        )
        self.picker.bind("<Button-1>", self._on_pick)
        self.picker.bind("<B1-Motion>", self._on_pick)

        ttk.Label(frame, text="BPM").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(frame, textvariable=self.bpm_var, width=8).grid(
            row=4, column=1, sticky="w", pady=(6, 0)
        )
        self.swatch = tk.Canvas(frame, width=40, height=40, highlightthickness=1)
        self.swatch.grid(row=4, column=2, rowspan=2, padx=8)

        ttk.Label(frame, text="Route in patch bay").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )

        ttk.Button(frame, text="Random", command=self._on_random_scan).grid(
            row=6, column=0, sticky="ew", pady=(8, 0)
        )
        ttk.Button(frame, text="Send", command=self._on_send).grid(
            row=6, column=1, columnspan=2, sticky="ew", pady=(8, 0)
        )

        # initialize marker/swatch at gamut center, mid brightness
        self._set_pick(PICKER_W // 2, PICKER_H // 2)

    def _build_audition_controls(self):
        frame = ttk.LabelFrame(self.left_column, text="Audition")
        frame.grid(
            row=LEFT_STACK_ROWS["audition"],
            column=0,
            sticky="new",
            pady=(0, 8),
        )

        ttk.Label(frame, text="Wet/Dry").grid(row=0, column=0, sticky="w")
        ttk.Scale(
            frame,
            from_=0.0,
            to=1.0,
            variable=self.wet_dry_var,
            command=lambda _v: setattr(
                self.engine, "wet_dry", self.wet_dry_var.get()
            ),
        ).grid(row=0, column=1, columnspan=2, sticky="ew")

        frame.columnconfigure(1, weight=1)

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

    def _on_pick(self, event):
        self._set_pick(event.x, event.y)

    def _set_pick(self, x, y):
        x = int(clamp(x, 0, PICKER_W - 1))
        y = int(clamp(y, 0, PICKER_H - 1))
        hue, sat, val = _picker_coords_to_hsv(x, y)
        self.hue_var.set(hue)
        self.sat_var.set(sat)
        self.val_var.set(val)
        self.picker.coords(self._marker, x - 5, y - 5, x + 5, y + 5)
        self._update_swatch()

    def _current_color_hex(self):
        r, g, b = colorsys.hsv_to_rgb(
            self.hue_var.get(), self.sat_var.get(), self.val_var.get()
        )
        return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

    def _update_swatch(self):
        self.swatch.configure(bg=self._current_color_hex())

    def _on_random_scan(self):
        x, y, bpm = _random_scan_values()
        self._set_pick(x, y)
        self.bpm_var.set(f"{bpm:.0f}")

    def _on_toggle_playback(self):
        if self.engine.paused:
            self.engine.resume()
            self.pause_button.configure(text="Pause")
        else:
            self.engine.pause()
            self.pause_button.configure(text="Play")

    # ---------- layers ----------

    def _build_layer_list(self):
        frame = ttk.LabelFrame(self.left_column, text="Scan Sources")
        frame.grid(
            row=LEFT_STACK_ROWS["scan_sources"],
            column=0,
            sticky="nsew",
        )

        canvas = tk.Canvas(frame, height=180, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        self.layer_list_frame = ttk.Frame(canvas)

        window = canvas.create_window(
            (0, 0), window=self.layer_list_frame, anchor="nw"
        )
        self.layer_list_frame.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfigure(window, width=e.width)
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # scroll with the mouse wheel while the pointer is over the list
        canvas.bind(
            "<Enter>",
            lambda _e: canvas.bind_all(
                "<MouseWheel>",
                lambda e: canvas.yview_scroll(-e.delta // 120, "units"),
            ),
        )
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

    def _read_bpm(self):
        try:
            bpm = float(self.bpm_var.get())
        except ValueError:
            messagebox.showerror(
                "Invalid BPM", f"BPM must be a number (got {self.bpm_var.get()!r})"
            )
            return None
        return clamp(bpm, BPM_MIN, BPM_MAX)

    def _on_send(self):
        bpm = self._read_bpm()
        if bpm is None:
            return
        sources = self.engine.registry.sources_snapshot()
        if not _can_add_patch_source(sources):
            messagebox.showinfo(
                "Patch bay full",
                f"Maximum patch outputs reached ({PATCH_SOURCE_LIMIT}).",
            )
            return
        color_hex = self._current_color_hex()
        source_id = self.engine.registry.add_source(
            hue=self.hue_var.get(),
            sat=self.sat_var.get(),
            val=self.val_var.get(),
            bpm=bpm,
        )
        self._source_colors[source_id] = color_hex
        self._add_layer_row(source_id, bpm, color_hex)
        self._redraw_patch_bay()

    def _add_layer_row(self, layer_id, bpm, color_hex):
        row = ttk.Frame(self.layer_list_frame)
        row.pack(fill="x", pady=2)
        icon = tk.Canvas(row, width=16, height=16, highlightthickness=1, bg=color_hex)
        icon.pack(side="left", padx=(0, 6))
        ttk.Label(row, text=f"Source {layer_id} (BPM {bpm:.0f})").pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(
            row, text="Remove", command=lambda: self._on_remove(layer_id, row)
        ).pack(side="right")
        self._layer_rows[layer_id] = row

    def _on_remove(self, layer_id, row):
        self.engine.registry.remove_source(layer_id)
        self._source_colors.pop(layer_id, None)
        row.destroy()
        del self._layer_rows[layer_id]
        self._redraw_patch_bay()

    # ---------- audio / waveform ----------

    def _build_waveform(self):
        frame = ttk.LabelFrame(self.root, text="Waveform")
        frame.grid(row=1, column=1, sticky="nsew", padx=8, pady=(0, 8))
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=3)
        self.root.rowconfigure(1, weight=1)

        fig = Figure(figsize=WAVEFORM_FIGSIZE)
        self.ax = fig.add_subplot(111)
        zeros = np.zeros(WAVEFORM_WINDOW_SAMPLES)
        # Faint background traces: the modulation control signals, each
        # normalized to +/-1 at their global maximum depth so their scale
        # is comparable block to block.
        (self.warble_line,) = self.ax.plot(
            zeros, color="tab:orange", alpha=0.35, linewidth=1.0,
            label="warble (pitch mod)",
        )
        (self.bloom_line,) = self.ax.plot(
            zeros, color="tab:green", alpha=0.35, linewidth=1.0,
            label="bloom (amp mod)",
        )
        (self.wet_line,) = self.ax.plot(
            zeros, color="tab:purple", alpha=0.35, linewidth=1.0,
            label="added texture (wet)",
        )
        # Foreground trace: the audible post-modulation output.
        (self.line,) = self.ax.plot(
            zeros, color="tab:blue", linewidth=1.2, label="output"
        )
        self.ax.set_ylim(-1.05, 1.05)
        self.ax.set_xticks([])
        self.ax.legend(loc="upper right", fontsize=7, framealpha=0.6)

        self.canvas = FigureCanvasTkAgg(fig, master=frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    # ---------- patch bay ----------

    def _build_patch_bay(self):
        frame = ttk.LabelFrame(self.root, text="Patch Bay")
        frame.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        self.patch_canvas = tk.Canvas(
            frame,
            width=PATCH_CANVAS_W,
            height=PATCH_CANVAS_H,
            highlightthickness=0,
            bg="#161616",
        )
        self.patch_canvas.pack(fill="both", expand=True)
        self.patch_canvas.bind("<Button-1>", self._on_patch_press)
        self.patch_canvas.bind("<B1-Motion>", self._on_patch_drag)
        self.patch_canvas.bind("<ButtonRelease-1>", self._on_patch_release)
        self._redraw_patch_bay()

    def _source_positions(self):
        sources = self.engine.registry.sources_snapshot()
        return _source_positions_for_sources(sources)

    def _cell_center(self, row, col):
        return (
            PATCH_GRID_X + col * PATCH_CELL + PATCH_CELL / 2,
            PATCH_GRID_Y + row * PATCH_CELL + PATCH_CELL / 2,
        )

    def _cell_at(self, x, y):
        col = int((x - PATCH_GRID_X) // PATCH_CELL)
        row = int((y - PATCH_GRID_Y) // PATCH_CELL)
        if _patch_cell_to_engine(row, col) is None:
            return None
        return row, col

    def _nearest_source(self, x, y):
        for source_id, (sx, sy) in self._source_positions().items():
            if (x - sx) ** 2 + (y - sy) ** 2 <= 14 ** 2:
                return source_id
        return None

    def _redraw_patch_bay(self):
        canvas = self.patch_canvas
        canvas.delete("all")
        canvas.create_text(
            PATCH_SOURCE_X,
            22,
            text="outputs",
            fill="#bdbdbd",
            font=("TkDefaultFont", 9),
        )
        canvas.create_text(
            PATCH_GRID_X + PATCH_CELL * PATCH_GRID_SIZE / 2,
            22,
            text="effects",
            fill="#bdbdbd",
            font=("TkDefaultFont", 9),
        )

        for row, engine in enumerate(PATCH_ROW_ENGINES):
            y = PATCH_GRID_Y + row * PATCH_CELL + PATCH_CELL / 2
            canvas.create_text(
                PATCH_GRID_X - 12,
                y,
                text=engine,
                anchor="e",
                fill="#d5d5d5",
                font=("TkDefaultFont", 9),
            )
            for col in range(PATCH_GRID_SIZE):
                x0 = PATCH_GRID_X + col * PATCH_CELL
                y0 = PATCH_GRID_Y + row * PATCH_CELL
                canvas.create_rectangle(
                    x0,
                    y0,
                    x0 + PATCH_CELL,
                    y0 + PATCH_CELL,
                    outline="#555555",
                    fill="#222222",
                    width=1,
                )
                canvas.create_text(
                    x0 + PATCH_CELL / 2,
                    y0 + PATCH_CELL / 2,
                    text=PATCH_COL_LABELS[col],
                    fill="#808080",
                    font=("TkDefaultFont", 8),
                )

        positions = self._source_positions()
        sources = self.engine.registry.sources_snapshot()
        for slot, (sx, sy) in enumerate(_patch_slot_positions(), start=1):
            canvas.create_oval(
                sx - 8,
                sy - 8,
                sx + 8,
                sy + 8,
                outline="#777777",
                fill="#3a3a3a",
                width=1,
                tags=(f"slot-{slot}", "slot"),
            )
            canvas.create_text(
                sx - 18,
                sy,
                text=str(slot),
                anchor="e",
                fill="#777777",
                font=("TkDefaultFont", 8),
            )
        for source in sources:
            source_id = source["id"]
            sx, sy = positions[source_id]
            color = self._source_colors.get(source_id, "#cccccc")
            route = source["route"]
            if route is not None:
                tx, ty = self._cell_center(route["patch_row"], route["patch_col"])
                canvas.create_line(
                    *_patch_cable_points(sx, sy, tx, ty),
                    fill=color,
                    width=3,
                    tags=(f"connection-{source_id}", "connection"),
                )
            canvas.create_oval(
                sx - 8,
                sy - 8,
                sx + 8,
                sy + 8,
                outline="#f0f0f0",
                fill=color,
                width=2,
                tags=(f"source-{source_id}", "source"),
            )
            canvas.create_text(
                sx - 18,
                sy,
                text=str(source_id),
                anchor="e",
                fill="#d5d5d5",
                font=("TkDefaultFont", 8),
            )

    def _on_patch_press(self, event):
        self._drag_source_id = self._nearest_source(event.x, event.y)
        if self._drag_source_id is None:
            items = self.patch_canvas.find_overlapping(
                event.x - 5, event.y - 5, event.x + 5, event.y + 5
            )
            for item in items:
                tags = self.patch_canvas.gettags(item)
                for tag in tags:
                    if tag.startswith("connection-"):
                        self._drag_source_id = int(tag.split("-", 1)[1])
                        break
                if self._drag_source_id is not None:
                    break
        if self._drag_source_id is None:
            return
        sx, sy = self._source_positions()[self._drag_source_id]
        color = self._source_colors.get(self._drag_source_id, "#cccccc")
        self._drag_line = self.patch_canvas.create_line(
            *_patch_cable_points(sx, sy, event.x, event.y),
            fill=color,
            dash=(4, 3),
            width=2,
        )

    def _on_patch_drag(self, event):
        if self._drag_source_id is None or self._drag_line is None:
            return
        sx, sy = self._source_positions()[self._drag_source_id]
        self.patch_canvas.coords(
            self._drag_line,
            *_patch_cable_points(sx, sy, event.x, event.y),
        )

    def _on_patch_release(self, event):
        if self._drag_source_id is None:
            return
        cell = self._cell_at(event.x, event.y)
        if cell is None:
            self.engine.registry.disconnect_source(self._drag_source_id)
        else:
            row, col = cell
            self.engine.registry.connect_source(
                self._drag_source_id,
                engine=_patch_cell_to_engine(row, col),
                row=row,
                col=col,
            )
        self._drag_source_id = None
        self._drag_line = None
        self._redraw_patch_bay()

    def _load_initial_loop(self, path):
        try:
            self.engine.load_loop(path)
            self.engine.start()
        except Exception as exc:
            messagebox.showerror("Failed to start audio", str(exc))

    def _on_load_loop(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Audio files", "*.wav *.mp3"),
                ("WAV files", "*.wav"),
                ("MP3 files", "*.mp3"),
            ]
        )
        if not path:
            return
        try:
            self.engine.load_loop(path)
        except Exception as exc:
            messagebox.showerror("Failed to load audio", str(exc))

    def _schedule_refresh(self):
        self._refresh_waveform()
        self.root.after(REFRESH_MS, self._schedule_refresh)

    def _refresh_waveform(self):
        data = self.engine.visual_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        warble = self.engine.warble_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        bloom = self.engine.bloom_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        wet = self.engine.wet_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        self.line.set_ydata(data)
        self.warble_line.set_ydata(warble / MAX_WARBLE_DEPTH)
        self.bloom_line.set_ydata(bloom / MAX_BLOOM_DEPTH)
        self.wet_line.set_ydata(wet)
        self.canvas.draw_idle()
