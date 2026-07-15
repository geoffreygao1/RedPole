import colorsys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

WAVEFORM_WINDOW_SAMPLES = 4096
REFRESH_MS = 50


class RedPoleGUI:
    def __init__(self, root, engine, default_loop_path):
        self.root = root
        self.engine = engine
        self.root.title("RedPole Audio Prototype")
        self._layer_rows = {}

        self.hue_var = tk.DoubleVar(value=0.5)
        self.sat_var = tk.DoubleVar(value=0.7)
        self.val_var = tk.DoubleVar(value=0.7)
        self.bpm_var = tk.DoubleVar(value=70.0)

        self._build_controls()
        self._build_layer_list()
        self._build_waveform()
        self._load_initial_loop(default_loop_path)
        self._schedule_refresh()

    def _build_controls(self):
        frame = ttk.LabelFrame(self.root, text="Scan Input")
        frame.grid(row=0, column=0, sticky="new", padx=8, pady=8)

        ttk.Button(frame, text="Load Loop...", command=self._on_load_loop).grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        ttk.Label(frame, text="Hue").grid(row=1, column=0, sticky="w")
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.hue_var,
            command=lambda _: self._update_swatch(),
        ).grid(row=1, column=1, sticky="ew")

        ttk.Label(frame, text="Saturation").grid(row=2, column=0, sticky="w")
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.sat_var,
            command=lambda _: self._update_swatch(),
        ).grid(row=2, column=1, sticky="ew")

        ttk.Label(frame, text="Value").grid(row=3, column=0, sticky="w")
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.val_var,
            command=lambda _: self._update_swatch(),
        ).grid(row=3, column=1, sticky="ew")

        ttk.Label(frame, text="BPM").grid(row=4, column=0, sticky="w")
        ttk.Scale(frame, from_=40.0, to=180.0, variable=self.bpm_var).grid(
            row=4, column=1, sticky="ew"
        )

        self.swatch = tk.Canvas(frame, width=40, height=40, highlightthickness=1)
        self.swatch.grid(row=1, column=2, rowspan=3, padx=8)
        self._update_swatch()

        ttk.Button(frame, text="Send", command=self._on_send).grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )

    def _hue_to_rgb_hex(self, hue_norm):
        # Hue slider is normalized 0..1 across a red-only span (-10deg..+10deg
        # through 0deg), matching what the real finger-scan sensor can return.
        hue_degrees = (-10.0 + hue_norm * 20.0) % 360.0
        r, g, b = colorsys.hsv_to_rgb(
            hue_degrees / 360.0, self.sat_var.get(), self.val_var.get()
        )
        return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

    def _update_swatch(self):
        self.swatch.configure(bg=self._hue_to_rgb_hex(self.hue_var.get()))

    def _build_layer_list(self):
        frame = ttk.LabelFrame(self.root, text="Active Layers")
        frame.grid(row=1, column=0, sticky="new", padx=8, pady=8)
        self.layer_list_frame = frame

    def _build_waveform(self):
        frame = ttk.LabelFrame(self.root, text="Waveform")
        frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=8, pady=8)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

        fig = Figure(figsize=(5, 3))
        self.ax = fig.add_subplot(111)
        (self.line,) = self.ax.plot(np.zeros(WAVEFORM_WINDOW_SAMPLES))
        self.ax.set_ylim(-1.05, 1.05)
        self.ax.set_xticks([])

        self.canvas = FigureCanvasTkAgg(fig, master=frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _load_initial_loop(self, path):
        try:
            self.engine.load_loop(path)
            self.engine.start()
        except Exception as exc:
            messagebox.showerror("Failed to start audio", str(exc))

    def _on_load_loop(self):
        path = filedialog.askopenfilename(filetypes=[("WAV files", "*.wav")])
        if not path:
            return
        try:
            self.engine.load_loop(path)
        except Exception as exc:
            messagebox.showerror("Failed to load audio", str(exc))

    def _on_send(self):
        layer_id = self.engine.registry.add(
            hue=self.hue_var.get(),
            sat=self.sat_var.get(),
            val=self.val_var.get(),
            bpm=self.bpm_var.get(),
        )
        self._add_layer_row(layer_id, self.bpm_var.get())

    def _add_layer_row(self, layer_id, bpm):
        row = ttk.Frame(self.layer_list_frame)
        row.pack(fill="x", pady=2)
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
        self.line.set_ydata(data)
        self.canvas.draw_idle()
