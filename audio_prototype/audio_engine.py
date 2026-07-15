import threading

import soundfile as sf
import sounddevice as sd
import numpy as np

from granular_processor import GranularProcessor
from layers import LayerRegistry
from modulation import RmsLimiter, combine_layers, soft_clip
from reverb import SchroederReverb
from ring_buffer import RingBuffer
from spectral_processor import FFT_SIZE, SpectralProcessor, analyze_frame, analyze_loop
from tape_modulator import TapeModulator
from wet_bus import WetBusManager

VISUALIZER_BUFFER_SECONDS = 2.0
DUCK_PER_LAYER = 0.12
DUCK_FLOOR = 0.5
REVERB_DEFAULT_FEEDBACK = 0.84
REVERB_DEFAULT_CUTOFF = 7800.0
REVERB_SMOOTHING = 0.1  # per-block drift toward the target character


def bpm_to_reverb_feedback(bpm):
    """Slow, calm pulses open a long wash; fast pulses tighten the room."""
    return min(0.92, max(0.72, 0.95 - 0.001 * bpm))


def val_to_reverb_cutoff(val):
    """Dark crimsons give a muffled tail; bright pinks keep it airy."""
    return 800.0 + 7000.0 * min(1.0, max(0.0, val))


class AudioEngine:
    MODES = ("tape", "spectral", "granular", "mixed")

    def __init__(self, samplerate=44100, blocksize=1024, seed=None):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.registry = LayerRegistry()
        self.modulator = TapeModulator(samplerate=samplerate, seed=seed)
        self.spectral = SpectralProcessor(samplerate, seed=seed)
        self.granular = GranularProcessor(samplerate, seed=seed)
        self.reverb = SchroederReverb(samplerate)
        self.wet_bus = WetBusManager(samplerate)
        self.reverb_mix = 0.35
        # Guards the wet bus against sustained overload (many layers,
        # live-analysis feedback, long reverb tails all stacking up).
        self.wet_limiter = RmsLimiter(target_rms=0.35)
        self.live_analysis = False
        # 0 = dry loop only, 0.5 = balanced (default), 1 = wet texture only.
        self.wet_dry = 0.5
        self._rv_feedback = REVERB_DEFAULT_FEEDBACK
        self._rv_cutoff = REVERB_DEFAULT_CUTOFF
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
        self._paused = False
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
        data, file_rate = sf.read(path, dtype="float32", always_2d=True)
        if file_rate != self.samplerate:
            raise ValueError(
                f"Loop file sample rate {file_rate} does not match engine "
                f"sample rate {self.samplerate}"
            )
        self.loop_array = data.mean(axis=1).astype("float32")
        self._dry_pos = 0
        try:
            self.spectral.set_analysis(analyze_loop(self.loop_array, self.samplerate))
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
        mode = self.mode
        zeros = np.zeros(frames, dtype=np.float32)

        if mode == "tape":
            combined = combine_layers(layers)
            block = self.modulator.process(
                self.loop_array,
                frames,
                combined["warble_depth"],
                combined["bloom_depth"],
                combined["rate_hz"],
            )
            self.warble_buffer.write(self.modulator.last_warble_signal)
            self.bloom_buffer.write(self.modulator.last_gain - 1.0)
            self.wet_buffer.write(zeros)
        else:
            if mode == "mixed":
                tape_layers = [l for l in layers if l["engine"] == "tape"]
                spec_layers = [l for l in layers if l["engine"] == "spectral"]
                gran_layers = [l for l in layers if l["engine"] == "granular"]
                reverb_layers = [l for l in layers if l["engine"] == "reverb"]
                combined = combine_layers(tape_layers)
                # Zero-depth tape processing is an exact dry passthrough,
                # so the base stays continuous when no tape layers exist.
                base = self.modulator.process(
                    self.loop_array,
                    frames,
                    combined["warble_depth"],
                    combined["bloom_depth"],
                    combined["rate_hz"],
                )
            else:
                spec_layers = layers if mode == "spectral" else []
                gran_layers = layers if mode == "granular" else []
                reverb_layers = []
                base = self._next_dry(frames)

            live_frame = None
            if self.live_analysis and spec_layers:
                live_frame = analyze_frame(self._analysis_window, self.samplerate)

            wet_raw = self.spectral.process(
                self.loop_array, frames, spec_layers, live_frame=live_frame
            ) + self.granular.process(self.loop_array, frames, gran_layers)

            n_wet = len(spec_layers) + len(gran_layers)
            duck = max(DUCK_FLOOR, 1.0 / (1.0 + DUCK_PER_LAYER * n_wet))

            # Reverb is itself an assignable engine: reverb-assigned layers
            # add no signal of their own but shape the shared room -- their
            # average pulse sets the decay, their average brightness colors
            # the tail. No reverb layers -> drift back to neutral defaults.
            if reverb_layers:
                n_rv = len(reverb_layers)
                target_fb = bpm_to_reverb_feedback(
                    sum(l["bpm"] for l in reverb_layers) / n_rv
                )
                target_cut = val_to_reverb_cutoff(
                    sum(l["val"] for l in reverb_layers) / n_rv
                )
            else:
                n_rv = 0
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

            managed_wet_raw = self.wet_bus.process(
                wet_raw,
                wet_voice_count=n_wet,
                reverb_layer_count=n_rv,
            )
            wet = self.wet_limiter.process(
                managed_wet_raw
                + self.reverb_mix * self.reverb.process(managed_wet_raw)
            )
            # Wet/dry balance: 0 = dry only, 0.5 = both full, 1 = wet only.
            mix = self.wet_dry
            dry_gain = min(1.0, 2.0 * (1.0 - mix))
            wet_gain = min(1.0, 2.0 * mix)
            block = soft_clip(dry_gain * duck * base + wet_gain * wet).astype(
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

    def _callback(self, outdata, frames, time_info, status):
        outdata[:, 0] = self.generate_block(frames)

    def start(self):
        self._stream = sd.OutputStream(
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            channels=1,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
