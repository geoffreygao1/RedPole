import threading

import soundfile as sf
import sounddevice as sd
import numpy as np

from granular_processor import GranularProcessor
from layers import LayerRegistry
from modulation import combine_layers, soft_clip
from ring_buffer import RingBuffer
from spectral_processor import SpectralProcessor, analyze_loop
from tape_modulator import TapeModulator

VISUALIZER_BUFFER_SECONDS = 2.0


class AudioEngine:
    MODES = ("tape", "spectral", "granular")

    def __init__(self, samplerate=44100, blocksize=1024, seed=None):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.registry = LayerRegistry()
        self.modulator = TapeModulator(samplerate=samplerate, seed=seed)
        self.spectral = SpectralProcessor(samplerate, seed=seed)
        self.granular = GranularProcessor(samplerate, seed=seed)
        buf_len = int(samplerate * VISUALIZER_BUFFER_SECONDS)
        self.visual_buffer = RingBuffer(buf_len)
        # Tape-mode control signals (warble pitch deviation, bloom gain-1):
        self.warble_buffer = RingBuffer(buf_len)
        self.bloom_buffer = RingBuffer(buf_len)
        # Spectral/granular wet-only signal (added texture, no dry loop):
        self.wet_buffer = RingBuffer(buf_len)
        self.loop_array = None
        self._stream = None
        self._mode = "tape"
        self._mode_lock = threading.Lock()
        self._dry_pos = 0

    @property
    def mode(self):
        with self._mode_lock:
            return self._mode

    def set_mode(self, mode):
        if mode not in self.MODES:
            raise ValueError(f"Unknown mode {mode!r}; expected one of {self.MODES}")
        with self._mode_lock:
            self._mode = mode

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
            dry = self._next_dry(frames)
            processor = self.spectral if mode == "spectral" else self.granular
            wet = processor.process(self.loop_array, frames, layers)
            block = soft_clip(dry + wet).astype(np.float32)
            self.warble_buffer.write(zeros)
            self.bloom_buffer.write(zeros)
            self.wet_buffer.write(wet)

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
