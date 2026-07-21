import threading

import soundfile as sf
import sounddevice as sd
import numpy as np

from crowd import CrowdState, EntryGestureTracker
from frequency_mod_processor import FrequencyModProcessor
from granular_processor import GranularProcessor
from layers import LayerRegistry
from microcosm_processor import MicrocosmProcessor
from modulation import (
    RmsLimiter,
    combine_layers,
    hue_to_bipolar,
    sat_to_unit,
    soft_clip,
    val_to_unit,
)
from reverb import SchroederReverb
from ring_buffer import RingBuffer
from spectral_processor import (
    FFT_SIZE,
    HOP_SIZE,
    SpectralProcessor,
    analyze_frame,
    analyze_loop,
)
from tape_modulator import TapeModulator, tape_column_controls
from wet_bus import WetBusManager

VISUALIZER_BUFFER_SECONDS = 2.0
MAX_LOOP_SECONDS = 600.0
MAX_ANALYSIS_SECONDS = 120.0
LOAD_CHUNK_FRAMES = 262144
REVERB_DEFAULT_FEEDBACK = 0.84
REVERB_DEFAULT_CUTOFF = 7800.0
REVERB_SMOOTHING = 0.1  # per-block drift toward the target character
REVERB_TAIL_HOLD_BLOCKS = 220
MAX_DENSITY_WET_BOOST = 0.18
FULL_WET_BOOST_DENSITY = 20.0


def bpm_to_reverb_feedback(bpm):
    """Slow, calm pulses open a long wash; fast pulses tighten the room."""
    return min(0.985, max(0.82, 0.99 - 0.00025 * bpm))


def val_to_reverb_cutoff(val):
    """Dark crimsons give a muffled tail; bright pinks keep it airy."""
    return 800.0 + 7000.0 * val_to_unit(val)


def effective_wet_dry_mix(wet_dry, wet_voice_count, reverb_layer_count):
    wet_dry = float(np.clip(wet_dry, 0.0, 1.0))
    if wet_dry <= 0.0 or wet_dry >= 1.0:
        return wet_dry
    reverb_density = 0.5 * reverb_layer_count if wet_voice_count > 0 else 0.0
    density = max(0.0, wet_voice_count + reverb_density)
    boost = MAX_DENSITY_WET_BOOST * min(1.0, density / FULL_WET_BOOST_DENSITY)
    return min(1.0, wet_dry + boost)


def reverb_layer_controls(layers):
    if not layers:
        return {
            "style": "wash",
            "size": 0.35,
            "diffusion": 0.45,
            "send": 0.0,
            "val": 0.0,
            "bpm": 120.0,
        }

    n = len(layers)
    weights = np.array(
        [0.2 + l["sat"] + l["val"] for l in layers],
        dtype=np.float64,
    )
    sats = np.array([l["sat"] for l in layers], dtype=np.float64)
    vals = np.array([l["val"] for l in layers], dtype=np.float64)
    bpms = np.array([l["bpm"] for l in layers], dtype=np.float64)
    sat = float(np.average([sat_to_unit(s) for s in sats], weights=weights))
    val = float(np.average([val_to_unit(v) for v in vals], weights=weights))
    bpm = float(np.average(bpms, weights=weights))
    density = min(1.0, np.sqrt(n / 6.0))

    return {
        "style": "wash",
        "size": min(1.0, 0.48 + 0.38 * sat + 0.30 * density),
        "diffusion": min(1.0, 0.55 + 0.30 * sat + 0.25 * density),
        "send": min(1.0, 0.18 + 0.45 * val + 0.55 * density),
        "val": val,
        "bpm": bpm,
    }


def resample_linear(data, source_rate, target_rate):
    if source_rate == target_rate or len(data) == 0:
        return data.astype(np.float32)
    target_len = max(1, int(round(len(data) * target_rate / source_rate)))
    source_x = np.linspace(0.0, 1.0, len(data), endpoint=False)
    target_x = np.linspace(0.0, 1.0, target_len, endpoint=False)
    return np.interp(target_x, source_x, data).astype(np.float32)


def read_mono_audio(path, max_seconds=None):
    if max_seconds is None:
        max_seconds = MAX_LOOP_SECONDS
    chunks = []
    with sf.SoundFile(path) as file:
        file_rate = file.samplerate
        frames_to_read = len(file)
        if max_seconds is not None:
            frames_to_read = min(frames_to_read, max(1, int(max_seconds * file_rate)))

        remaining = frames_to_read
        while remaining > 0:
            block = file.read(
                min(LOAD_CHUNK_FRAMES, remaining),
                dtype="float32",
                always_2d=True,
            )
            if len(block) == 0:
                break
            chunks.append(block.mean(axis=1).astype(np.float32))
            remaining -= len(block)

    if not chunks:
        return np.zeros(0, dtype=np.float32), file_rate
    return np.concatenate(chunks).astype(np.float32), file_rate


class AudioEngine:
    MODES = ("tape", "spectral", "granular", "mixed")

    def __init__(self, samplerate=44100, blocksize=1024, seed=None):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.registry = LayerRegistry()
        self.entry_gestures = EntryGestureTracker(samplerate)
        self._stereo_rng = np.random.default_rng(None if seed is None else seed + 7919)
        self._glitch_pan = 0.0
        self._stereo_side_state = 0.0
        self.modulator = TapeModulator(samplerate=samplerate, seed=seed)
        self.spectral = FrequencyModProcessor(samplerate, seed=seed)
        self.granular = GranularProcessor(samplerate, seed=seed)
        self.microcosm = MicrocosmProcessor(samplerate, seed=seed)
        self.reverb = SchroederReverb(samplerate)
        self.wet_bus = WetBusManager(samplerate)
        self.reverb_mix = 0.975  # +30% per user request (was 0.75)
        # Guards the wet bus against sustained overload (many layers,
        # live-analysis feedback, long reverb tails all stacking up).
        self.wet_limiter = RmsLimiter(target_rms=0.35)
        self.live_analysis = False
        # 0 = dry loop only, 0.5 = balanced (default), 1 = wet texture only.
        self.wet_dry = 0.5
        self._rv_feedback = REVERB_DEFAULT_FEEDBACK
        self._rv_cutoff = REVERB_DEFAULT_CUTOFF
        self._reverb_tail_blocks = 0
        buf_len = int(samplerate * VISUALIZER_BUFFER_SECONDS)
        self.visual_buffer = RingBuffer(buf_len)
        # Tape-mode control signals (warble pitch deviation, bloom gain-1):
        self.warble_buffer = RingBuffer(buf_len)
        self.bloom_buffer = RingBuffer(buf_len)
        # Spectral/granular wet-only signal (added texture, no dry loop):
        self.wet_buffer = RingBuffer(buf_len)
        self.loop_array = None
        self._stream = None
        self._mode = "mixed"
        self._mode_lock = threading.Lock()
        self._dry_pos = 0
        self._paused = True
        # Rolling window of recent output for live spectral analysis.
        self._analysis_window = np.zeros(FFT_SIZE, dtype=np.float32)

    @property
    def mode(self):
        with self._mode_lock:
            return self._mode

    def set_mode(self, mode):
        if mode not in self.MODES:
            raise ValueError(f"Unknown mode {mode!r}; expected one of {self.MODES}")
        with self._mode_lock:
            self._mode = mode

    @property
    def paused(self):
        return self._paused

    def pause(self):
        self._paused = True
        if self._stream is not None:
            self._stream.stop()

    def resume(self):
        self._paused = False
        if self._stream is not None:
            self._stream.start()

    def load_loop(self, path):
        mono, file_rate = read_mono_audio(path)
        self.loop_array = resample_linear(mono, file_rate, self.samplerate)
        self._dry_pos = 0
        try:
            max_analysis = max(1, int(MAX_ANALYSIS_SECONDS * self.samplerate))
            analysis_source = self.loop_array[:max_analysis]
            self.spectral.set_analysis(analyze_loop(analysis_source, self.samplerate))
        except Exception:
            # Spectral mode degrades to dry playback rather than crashing.
            self.spectral.set_analysis(None)

    def _next_dry(self, frames):
        idx = (self._dry_pos + np.arange(frames)) % len(self.loop_array)
        self._dry_pos = int((self._dry_pos + frames) % len(self.loop_array))
        return self.loop_array[idx]

    def _update_analysis_window(self, block):
        n = len(block)
        if n >= FFT_SIZE:
            self._analysis_window = block[-FFT_SIZE:].astype(np.float32)
        else:
            self._analysis_window = np.concatenate(
                [self._analysis_window[n:], block]
            ).astype(np.float32)

    def generate_block(self, frames):
        if self.loop_array is None:
            raise RuntimeError("No loop loaded; call load_loop() first")
        layers = self.registry.snapshot()
        crowd = CrowdState.from_layers(layers)
        entry = self.entry_gestures.process(layers, frames, crowd.density)
        mode = self.mode
        zeros = np.zeros(frames, dtype=np.float32)

        if mode == "tape":
            combined = combine_layers(layers)
            tape_controls = tape_column_controls(layers)
            avg_hue = sum(l["hue"] for l in layers) / len(layers) if layers else 0.0
            avg_sat = sum(l["sat"] for l in layers) / len(layers) if layers else 0.5
            avg_val = sum(l["val"] for l in layers) / len(layers) if layers else 1.0
            block = self.modulator.process(
                self.loop_array,
                frames,
                combined["warble_depth"],
                combined["bloom_depth"] * (1.0 + entry.engine_gain("tape")),
                combined["rate_hz"],
                hue=avg_hue,
                sat=avg_sat,
                val=avg_val,
                tape_controls=tape_controls,
            )
            self.warble_buffer.write(self.modulator.last_warble_signal)
            self.bloom_buffer.write(self.modulator.last_gain - 1.0)
            self.wet_buffer.write(zeros)
        else:
            source_pos = None
            if mode == "mixed":
                tape_layers = [l for l in layers if l["engine"] == "tape"]
                spec_layers = [l for l in layers if l["engine"] == "spectral"]
                gran_layers = [l for l in layers if l["engine"] == "granular"]
                micro_layers = [
                    l for l in layers
                    if l["engine"] in ("microloop", "granules", "glitch", "multidelay")
                ]
                reverb_layers = [l for l in layers if l["engine"] == "reverb"]
                combined = combine_layers(tape_layers)
                tape_controls = tape_column_controls(tape_layers)
                avg_hue = (
                    sum(l["hue"] for l in tape_layers) / len(tape_layers)
                    if tape_layers
                    else 0.0
                )
                avg_sat = (
                    sum(l["sat"] for l in tape_layers) / len(tape_layers)
                    if tape_layers
                    else 0.5
                )
                avg_val = (
                    sum(l["val"] for l in tape_layers) / len(tape_layers)
                    if tape_layers
                    else 1.0
                )
                # Zero-depth tape processing is an exact dry passthrough,
                # so the base stays continuous when no tape layers exist.
                source_pos = self.modulator._read_pos
                if tape_layers:
                    base = self.modulator.process(
                        self.loop_array,
                        frames,
                        combined["warble_depth"],
                        combined["bloom_depth"] * (1.0 + entry.engine_gain("tape")),
                        combined["rate_hz"],
                        hue=avg_hue,
                        sat=avg_sat,
                        val=avg_val,
                        tape_controls=tape_controls,
                    )
                else:
                    base = self._next_dry(frames)
                    self.modulator._read_pos = self._dry_pos
                    self.modulator.last_warble_signal = zeros
                    self.modulator.last_gain = np.ones(frames, dtype=np.float32)
            else:
                spec_layers = layers if mode == "spectral" else []
                gran_layers = layers if mode == "granular" else []
                micro_layers = []
                reverb_layers = []
                source_pos = self._dry_pos
                base = self._next_dry(frames)

            if not layers and self._reverb_tail_blocks <= 0:
                block = base.astype(np.float32)
                self.warble_buffer.write(zeros)
                self.bloom_buffer.write(zeros)
                self.wet_buffer.write(zeros)
                self._update_analysis_window(block)
                self.visual_buffer.write(block)
                return block

            live_frame = None
            if self.live_analysis and spec_layers:
                live_frame = analyze_frame(self._analysis_window, self.samplerate)

            spectral_wet = self.spectral.process(
                self.loop_array,
                frames,
                spec_layers,
                live_frame=live_frame,
                scan_start=source_pos / HOP_SIZE,
            )
            granular_wet = self.granular.process(
                self.loop_array,
                frames,
                gran_layers,
                source_pos=source_pos,
            )
            micro_wet = self.microcosm.process(
                self.loop_array,
                frames,
                micro_layers,
                source_pos=source_pos,
            )
            spectral_wet *= 1.0 + entry.engine_gain("spectral")
            granular_wet *= 1.0 + entry.engine_gain("granular")
            wet_raw = spectral_wet + granular_wet + micro_wet

            n_wet = len(spec_layers) + len(gran_layers) + len(micro_layers)

            # Reverb is itself an assignable engine: reverb-assigned layers
            # add no signal of their own but send the source into the shared
            # room. Average pulse and brightness set global room character.
            # No reverb layers -> drift back to neutral defaults.
            if reverb_layers:
                n_rv = len(reverb_layers)
                rv_controls = reverb_layer_controls(reverb_layers)
                rv_val = rv_controls["val"]
                target_fb = min(0.994, max(0.955, 0.996 - 0.00012 * rv_controls["bpm"]))
                target_cut = min(4800.0, 700.0 + 4200.0 * rv_val)
            else:
                n_rv = 0
                rv_controls = reverb_layer_controls([])
                target_fb = REVERB_DEFAULT_FEEDBACK
                target_cut = REVERB_DEFAULT_CUTOFF
            controls = self.wet_bus.controls(
                wet_voice_count=n_wet,
                reverb_layer_count=n_rv,
            )
            target_fb = max(0.62, target_fb - controls["feedback_trim"])
            target_cut = max(700.0, target_cut * controls["cutoff_scale"])
            self._rv_feedback += REVERB_SMOOTHING * (target_fb - self._rv_feedback)
            self._rv_cutoff += REVERB_SMOOTHING * (target_cut - self._rv_cutoff)
            self.reverb.set_feedback(self._rv_feedback)
            self.reverb.set_cutoff(self._rv_cutoff)
            self.reverb.set_space(
                style=rv_controls["style"],
                size=rv_controls["size"],
                diffusion=rv_controls["diffusion"],
            )

            managed_wet_raw = self.wet_bus.process(
                wet_raw,
                wet_voice_count=n_wet,
                reverb_layer_count=n_rv,
            )
            if reverb_layers:
                reverb_input = managed_wet_raw
            else:
                reverb_input = zeros
            if float(np.max(np.abs(reverb_input))) > 1e-7:
                self._reverb_tail_blocks = REVERB_TAIL_HOLD_BLOCKS
            elif self._reverb_tail_blocks > 0:
                self._reverb_tail_blocks -= 1
            reverb_wet = (
                self.reverb.process(reverb_input)
                if reverb_layers or self._reverb_tail_blocks > 0
                else zeros
            )
            wet = self.wet_limiter.process(
                managed_wet_raw
                + self.reverb_mix * reverb_wet
            )
            # Wet/dry balance: 0 = dry only, 0.5 = both full, 1 = wet only.
            mix = effective_wet_dry_mix(self.wet_dry, n_wet, n_rv)
            dry_gain = min(1.0, 2.0 * (1.0 - mix))
            wet_gain = min(1.0, 2.0 * mix)
            block = soft_clip(dry_gain * base + wet_gain * wet).astype(
                np.float32
            )
            if mode == "mixed":
                # the tape modulator runs as the base, so its control
                # signals are live and worth showing
                self.warble_buffer.write(self.modulator.last_warble_signal)
                self.bloom_buffer.write(self.modulator.last_gain - 1.0)
            else:
                self.warble_buffer.write(zeros)
                self.bloom_buffer.write(zeros)
            self.wet_buffer.write(wet)

        self._update_analysis_window(block)
        self.visual_buffer.write(block)
        return block

    def _effect_pan(self, layers):
        pan_layers = [l for l in layers if l["engine"] != "reverb"]
        if not pan_layers:
            return 0.0

        if any(l["engine"] == "glitch" for l in pan_layers):
            if self._stereo_rng.random() < 0.16:
                self._glitch_pan = float(self._stereo_rng.choice((-0.62, -0.38, 0.38, 0.62)))
            return self._glitch_pan

        weighted = sum(
            hue_to_bipolar(l["hue"]) * (0.25 + sat_to_unit(l["sat"]))
            for l in pan_layers
        )
        weight_total = sum(0.25 + sat_to_unit(l["sat"]) for l in pan_layers)
        return float(np.clip(weighted / max(1e-9, weight_total), -0.85, 0.85))

    def generate_stereo_block(self, frames):
        mono = self.generate_block(frames)
        layers = self.registry.snapshot()
        pan = self._effect_pan(layers)
        if abs(pan) < 1e-6:
            return np.column_stack([mono, mono]).astype(np.float32)

        wet = self.wet_buffer.read_latest(frames)
        has_glitch = any(l["engine"] == "glitch" for l in layers)
        side_width = 0.34 if has_glitch else 0.30
        target_gain = side_width * pan
        start_gain = self._stereo_side_state
        ramp = np.linspace(start_gain, target_gain, frames, dtype=np.float64)
        side = ramp * wet
        self._stereo_side_state = float(target_gain)
        left = soft_clip(mono - side)
        right = soft_clip(mono + side)
        return np.column_stack([left, right]).astype(np.float32)

    def _callback(self, outdata, frames, time_info, status):
        outdata[:, :] = self.generate_stereo_block(frames)

    def start(self):
        self._stream = sd.OutputStream(
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            channels=2,
            callback=self._callback,
        )
        if not self._paused:
            self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
