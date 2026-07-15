import colorsys
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from modulation import MAX_BLOOM_DEPTH, MAX_WARBLE_DEPTH, clamp

WAVEFORM_WINDOW_SAMPLES = 4096
REFRESH_MS = 50
BPM_MIN = 20.0
BPM_MAX = 300.0


class RedPoleGUI:
    def __init__(self, root, engine, default_loop_path):
        self.root = root
        self.engine = engine
        self.root.title("RedPole Audio Prototype")
        self._layer_rows = {}

        self.hue_var = tk.DoubleVar(value=0.0)
        self.sat_var = tk.DoubleVar(value=0.7)
        self.val_var = tk.DoubleVar(value=0.7)
        self.bpm_var = tk.StringVar(value="70")

        self._build_controls()
        self._build_layer_list()
        self._build_waveform()
        self._load_initial_loop(default_loop_path)
        self._schedule_refresh()

    def _build_controls(self):
        frame = ttk.LabelFrame(self.root, text="Scan Input")
        frame.grid(row=0, column=0, sticky="new", padx=8, pady=8)

        ttk.Button(frame, text="Load Loop...", command=self._on_load_loop).grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8)
        )

        ttk.Button(frame, text="Pick Color...", command=self._on_pick_color).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4)
        )

        ttk.Label(frame, text="Hue").grid(row=2, column=0, sticky="w")
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.hue_var,
            command=lambda _: self._update_swatch(),
        ).grid(row=2, column=1, sticky="ew")

        ttk.Label(frame, text="Saturation").grid(row=3, column=0, sticky="w")
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.sat_var,
            command=lambda _: self._update_swatch(),
        ).grid(row=3, column=1, sticky="ew")

        ttk.Label(frame, text="Value").grid(row=4, column=0, sticky="w")
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.val_var,
            command=lambda _: self._update_swatch(),
        ).grid(row=4, column=1, sticky="ew")

        ttk.Label(frame, text="BPM").grid(row=5, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.bpm_var, width=8).grid(
            row=5, column=1, sticky="w"
        )

        self.swatch = tk.Canvas(frame, width=40, height=40, highlightthickness=1)
        self.swatch.grid(row=1, column=2, rowspan=4, padx=8)
        self._update_swatch()

        ttk.Button(frame, text="Send", command=self._on_send).grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )

    def _current_color_hex(self):
        r, g, b = colorsys.hsv_to_rgb(
            self.hue_var.get(), self.sat_var.get(), self.val_var.get()
        )
        return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

    def _update_swatch(self):
        self.swatch.configure(bg=self._current_color_hex())

    def _on_pick_color(self):
        result = colorchooser.askcolor(
            color=self._current_color_hex(), title="Pick scan color"
        )
        if result is None or result[0] is None:
            return
        r, g, b = (c / 255.0 for c in result[0])
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        self.hue_var.set(h)
        self.sat_var.set(s)
        self.val_var.set(v)
        self._update_swatch()

    def _build_layer_list(self):
        frame = ttk.LabelFrame(self.root, text="Active Layers")
        frame.grid(row=1, column=0, sticky="new", padx=8, pady=8)
        self.layer_list_frame = frame

    def _build_waveform(self):
        frame = ttk.LabelFrame(self.root, text="Waveform")
        frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=8, pady=8)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

        fig = Figure(figsize=(6, 3.5))
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
        # Foreground trace: the audible post-modulation output.
        (self.line,) = self.ax.plot(
            zeros, color="tab:blue", linewidth=1.2, label="output"
        )
        self.ax.set_ylim(-1.05, 1.05)
        self.ax.set_xticks([])
        self.ax.legend(loc="upper right", fontsize=7, framealpha=0.6)

        self.canvas = FigureCanvasTkAgg(fig, master=frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

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
        color_hex = self._current_color_hex()
        layer_id = self.engine.registry.add(
            hue=self.hue_var.get(),
            sat=self.sat_var.get(),
            val=self.val_var.get(),
            bpm=bpm,
        )
        self._add_layer_row(layer_id, bpm, color_hex)

    def _add_layer_row(self, layer_id, bpm, color_hex):
        row = ttk.Frame(self.layer_list_frame)
        row.pack(fill="x", pady=2)
        icon = tk.Canvas(row, width=16, height=16, highlightthickness=1, bg=color_hex)
        icon.pack(side="left", padx=(0, 6))
        ttk.Label(row, text=f"Layer {layer_id} (BPM {bpm:.0f})").pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(
            row, text="Remove", command=lambda: self._on_remove(layer_id, row)
        ).pack(side="right")
        self._layer_rows[layer_id] = row

    def _on_remove(self, layer_id, row):
        self.engine.registry.remove(layer_id)
        row.destroy()
        del self._layer_rows[layer_id]

    def _schedule_refresh(self):
        self._refresh_waveform()
        self.root.after(REFRESH_MS, self._schedule_refresh)

    def _refresh_waveform(self):
        data = self.engine.visual_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        warble = self.engine.warble_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        bloom = self.engine.bloom_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        self.line.set_ydata(data)
        self.warble_line.set_ydata(warble / MAX_WARBLE_DEPTH)
        self.bloom_line.set_ydata(bloom / MAX_BLOOM_DEPTH)
        self.canvas.draw_idle()
