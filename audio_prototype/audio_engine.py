import soundfile as sf
import sounddevice as sd

from layers import LayerRegistry
from modulation import combine_layers
from ring_buffer import RingBuffer
from tape_modulator import TapeModulator

VISUALIZER_BUFFER_SECONDS = 2.0


class AudioEngine:
    def __init__(self, samplerate=44100, blocksize=1024, seed=None):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.registry = LayerRegistry()
        self.modulator = TapeModulator(samplerate=samplerate, seed=seed)
        self.visual_buffer = RingBuffer(int(samplerate * VISUALIZER_BUFFER_SECONDS))
        # Modulation control signals for visualization: warble stores the
        # depth-scaled pitch deviation, bloom stores (gain - 1.0).
        self.warble_buffer = RingBuffer(int(samplerate * VISUALIZER_BUFFER_SECONDS))
        self.bloom_buffer = RingBuffer(int(samplerate * VISUALIZER_BUFFER_SECONDS))
        self.loop_array = None
        self._stream = None

    def load_loop(self, path):
        data, file_rate = sf.read(path, dtype="float32", always_2d=True)
        if file_rate != self.samplerate:
            raise ValueError(
                f"Loop file sample rate {file_rate} does not match engine "
                f"sample rate {self.samplerate}"
            )
        self.loop_array = data.mean(axis=1).astype("float32")

    def generate_block(self, frames):
        if self.loop_array is None:
            raise RuntimeError("No loop loaded; call load_loop() first")
        layers = self.registry.snapshot()
        combined = combine_layers(layers)
        block = self.modulator.process(
            self.loop_array,
            frames,
            combined["warble_depth"],
            combined["bloom_depth"],
            combined["rate_hz"],
        )
        self.visual_buffer.write(block)
        self.warble_buffer.write(self.modulator.last_warble_signal)
        self.bloom_buffer.write(self.modulator.last_gain - 1.0)
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
