"""Interactive desktop wrapper around the Phase 1 SoundscapeEngine.

Adds a sounddevice output-stream lifecycle, a visualizer ring buffer, and a
thread lock (SoundscapeEngine mutates plain dicts/lists with no locking of
its own, so connect/disconnect from the UI thread must be serialized against
the audio callback's generate_block). Deliberately far thinner than
AudioEngine: no loop, no LayerRegistry, no reverb/wet-bus -- SoundscapeEngine
already does its own mixing and limiting."""

import threading

import numpy as np
import sounddevice as sd

from audio_io import read_mono_audio, resample_linear
from ring_buffer import RingBuffer
from soundscape_engine import SoundscapeEngine

VISUALIZER_BUFFER_SECONDS = 2.0


class SynthAudioEngine:
    def __init__(self, samplerate=44100, blocksize=1024, seed=None, root_midi=62):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self._seed = seed
        self._root_midi = int(root_midi)
        self._lock = threading.Lock()
        self.engine = SoundscapeEngine(
            samplerate=samplerate, seed=seed, root_midi=self._root_midi
        )
        self._loaded_sample = None
        self.visual_buffer = RingBuffer(int(samplerate * VISUALIZER_BUFFER_SECONDS))
        self._stream = None
        self._paused = True

    @property
    def root_midi(self):
        return self._root_midi

    # ---------- patch control ----------

    def connect_patch(self, hue, sat, val, bpm, source_preset, transform_preset=None):
        with self._lock:
            return self.engine.connect_patch(
                hue, sat, val, bpm, source_preset, transform_preset
            )

    def disconnect_patch(self, patch_id):
        with self._lock:
            self.engine.disconnect_patch(patch_id)

    def active_patches(self):
        with self._lock:
            return [
                {
                    "id": p.id,
                    "hue": p.hue,
                    "sat": p.sat,
                    "val": p.val,
                    "bpm": p.bpm,
                    "source_preset": p.source_preset,
                    "transform_preset": p.transform_preset,
                }
                for p in self.engine._patches.values()
            ]

    # ---------- audio ----------

    def generate_block(self, frames):
        with self._lock:
            try:
                block = self.engine.generate_block(frames)
            except Exception:
                block = np.zeros(frames, dtype=np.float32)
        self.visual_buffer.write(block)
        return block

    def generate_stereo_block(self, frames):
        mono = self.generate_block(frames)
        return np.column_stack([mono, mono]).astype(np.float32)

    # ---------- stream lifecycle ----------

    @property
    def paused(self):
        return self._paused

    def _open_stream(self):
        self._stream = sd.OutputStream(
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            channels=2,
            callback=self._callback,
        )

    def _callback(self, outdata, frames, time_info, status):
        outdata[:, :] = self.generate_stereo_block(frames)

    def start(self):
        if self._stream is None:
            self._open_stream()
        if not self._paused:
            self._stream.start()

    def resume(self):
        self._paused = False
        if self._stream is None:
            self._open_stream()
        self._stream.start()

    def pause(self):
        self._paused = True
        if self._stream is not None:
            self._stream.stop()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    # ---------- sample + tuning ----------

    def load_sample(self, path):
        mono, file_rate = read_mono_audio(path)
        samples = resample_linear(mono, file_rate, self.samplerate)
        self.load_sample_array(samples)

    def load_sample_array(self, samples):
        samples = np.asarray(samples, dtype=np.float64)
        with self._lock:
            self._loaded_sample = samples
            self.engine.sources.texture.load_sample(samples)

    def set_root_midi(self, root_midi):
        with self._lock:
            self._root_midi = int(root_midi)
            self.engine = SoundscapeEngine(
                samplerate=self.samplerate, seed=self._seed, root_midi=self._root_midi
            )
            if self._loaded_sample is not None:
                self.engine.sources.texture.load_sample(self._loaded_sample)
