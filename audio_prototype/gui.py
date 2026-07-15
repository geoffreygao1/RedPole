import colorsys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from modulation import FINGER_GAMUT_HALF_WIDTH, MAX_BLOOM_DEPTH, MAX_WARBLE_DEPTH, clamp

WAVEFORM_WINDOW_SAMPLES = 4096
REFRESH_MS = 50
BPM_MIN = 20.0
BPM_MAX = 300.0
PICKER_W = 220
PICKER_H = 120


def _picker_coords_to_hsv(x, y, w=PICKER_W, h=PICKER_H):
    """Map picker canvas coordinates to the finger-scan color gamut.

    x sweeps hue across the red-centered gamut (crimson -> red ->
    orange-pink); y sweeps brightness (bright at top), with saturation
    rising as the color darkens -- mirroring real transillumination
    images, where dim reds are deep and bright ones wash out pink.
    """
    fx = clamp(x / (w - 1), 0.0, 1.0)
    fy = clamp(y / (h - 1), 0.0, 1.0)
    hue = (-FINGER_GAMUT_HALF_WIDTH + 2 * FINGER_GAMUT_HALF_WIDTH * fx) % 1.0
    val = 1.0 - 0.72 * fy
    sat = 0.55 + 0.4 * fy
    return hue, sat, val


class RedPoleGUI:
    def __init__(self, root, engine, default_loop_path):
        self.root = root
        self.engine = engine
        self.root.title("RedPole Audio Prototype")
        self._layer_rows = {}

        self.hue_var = tk.DoubleVar(value=0.0)
        self.sat_var = tk.DoubleVar(value=0.75)
        self.val_var = tk.DoubleVar(value=0.64)
        self.bpm_var = tk.StringVar(value="70")
        self.mode_var = tk.StringVar(value="tape")
        self.engine_var = tk.StringVar(value="spectral")
        self.live_var = tk.BooleanVar(value=False)
        self.reverb_var = tk.DoubleVar(value=self.engine.reverb_mix)
        self.wet_dry_var = tk.DoubleVar(value=self.engine.wet_dry)

        self._build_controls()
        self._build_layer_list()
        self._build_waveform()
        self._load_initial_loop(default_loop_path)
        self._schedule_refresh()

    # ---------- controls ----------

    def _build_controls(self):
        frame = ttk.LabelFrame(self.root, text="Scan Input")
        frame.grid(row=0, column=0, sticky="new", padx=8, pady=8)

        ttk.Button(frame, text="Load Loop...", command=self._on_load_loop).grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8)
        )

        ttk.Label(frame, text="Mode").grid(row=1, column=0, sticky="w")
        mode_box = ttk.Combobox(
            frame, textvariable=self.mode_var, state="readonly",
            values=list(self.engine.MODES), width=10,
        )
        mode_box.grid(row=1, column=1, sticky="w", pady=(0, 4))
        mode_box.bind("<<ComboboxSelected>>",
                      lambda _e: self.engine.set_mode(self.mode_var.get()))

        self.pause_button = ttk.Button(
            frame, text="Pause", command=self._on_toggle_playback, width=7
        )
        self.pause_button.grid(row=1, column=2, padx=(8, 0))

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

        ttk.Label(frame, text="Engine").grid(row=5, column=0, sticky="w", pady=(4, 0))
        ttk.Combobox(
            frame, textvariable=self.engine_var, state="readonly",
            values=["tape", "spectral", "granular"], width=10,
        ).grid(row=5, column=1, sticky="w", pady=(4, 0))

        ttk.Checkbutton(
            frame, text="Live analysis (spectral feedback)",
            variable=self.live_var, command=self._on_live_toggle,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(frame, text="Reverb").grid(row=7, column=0, sticky="w")
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.reverb_var,
            command=lambda _v: setattr(
                self.engine, "reverb_mix", self.reverb_var.get()
            ),
        ).grid(row=7, column=1, columnspan=2, sticky="ew")

        ttk.Label(frame, text="Wet/Dry").grid(row=8, column=0, sticky="w")
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.wet_dry_var,
            command=lambda _v: setattr(
                self.engine, "wet_dry", self.wet_dry_var.get()
            ),
        ).grid(row=8, column=1, columnspan=2, sticky="ew")

        ttk.Button(frame, text="Send", command=self._on_send).grid(
            row=9, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )

        # initialize marker/swatch at gamut center, mid brightness
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

    def _on_live_toggle(self):
        self.engine.live_analysis = self.live_var.get()

    def _on_toggle_playback(self):
        if self.engine.paused:
            self.engine.resume()
            self.pause_button.configure(text="Pause")
        else:
            self.engine.pause()
            self.pause_button.configure(text="Play")

    # ---------- layers ----------

    def _build_layer_list(self):
        frame = ttk.LabelFrame(self.root, text="Active Layers")
        frame.grid(row=1, column=0, sticky="new", padx=8, pady=8)
        self.layer_list_frame = frame

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
        engine_name = self.engine_var.get()
        layer_id = self.engine.registry.add(
            hue=self.hue_var.get(),
            sat=self.sat_var.get(),
            val=self.val_var.get(),
            bpm=bpm,
            engine=engine_name,
        )
        self._add_layer_row(layer_id, bpm, color_hex, engine_name)

    def _add_layer_row(self, layer_id, bpm, color_hex, engine_name):
        row = ttk.Frame(self.layer_list_frame)
        row.pack(fill="x", pady=2)
        icon = tk.Canvas(row, width=16, height=16, highlightthickness=1, bg=color_hex)
        icon.pack(side="left", padx=(0, 6))
        ttk.Label(row, text=f"Layer {layer_id} (BPM {bpm:.0f}, {engine_name})").pack(
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

    # ---------- audio / waveform ----------

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
