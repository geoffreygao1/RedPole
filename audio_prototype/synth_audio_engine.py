"""Interactive desktop wrapper around the Phase 1 SoundscapeEngine.

Adds a sounddevice output-stream lifecycle, a visualizer ring buffer, and a
thread lock (SoundscapeEngine mutates plain dicts/lists with no locking of
its own, so connect/disconnect from the UI thread must be serialized against
the audio callback's generate_block). Deliberately far thinner than
AudioEngine: no loop, no LayerRegistry, no reverb/wet-bus -- SoundscapeEngine
already does its own mixing and limiting."""

import threading
import time

import numpy as np
import sounddevice as sd

from audio_io import read_mono_audio, resample_linear
from ring_buffer import RingBuffer
from soundscape_engine import SoundscapeEngine

VISUALIZER_BUFFER_SECONDS = 2.0


class SynthAudioEngine:
    def __init__(self, samplerate=44100, blocksize=2048, seed=None, root_midi=62):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self._seed = seed
        self._root_midi = int(root_midi)
        self._root_target = float(self._root_midi)
        self._lock = threading.Lock()
        self.engine = SoundscapeEngine(
            samplerate=samplerate, seed=seed, root_midi=self._root_midi
        )
        self._loaded_sample = None
        self.visual_buffer = RingBuffer(int(samplerate * VISUALIZER_BUFFER_SECONDS))
        self._stream = None
        self._paused = True
        self._running = False
        self._producer = None

    @property
    def root_midi(self):
        return int(round(self._root_target))

    # ---------- patch control ----------

    def connect_patch(self, hue, sat, val, bpm, source_preset, transform_preset=None):
        with self._lock:
            return self.engine.connect_patch(
                hue, sat, val, bpm, source_preset, transform_preset
            )

    def disconnect_patch(self, patch_id):
        with self._lock:
            self.engine.disconnect_patch(patch_id)

    def set_patch_transform(self, patch_id, transform_preset):
        with self._lock:
            self.engine.set_patch_transform(patch_id, transform_preset)

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
        # Blocking/write mode (no callback): PortAudio pulls audio in its own
        # C thread from a large internal buffer (latency="high"), so a GIL
        # stall on the Tk/main thread delays the producer's next write() but
        # does not underrun playback. This removes the callback-needs-the-GIL
        # glitch that a matplotlib redraw could trigger.
        self._stream = sd.OutputStream(
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            channels=2,
            latency="high",
        )

    def _run_producer(self):
        silence = np.zeros((self.blocksize, 2), dtype=np.float32)
        while self._running:
            block = (
                self.generate_stereo_block(self.blocksize)
                if not self._paused
                else silence
            )
            try:
                self._stream.write(block)
            except Exception:
                # A closed/aborted stream during shutdown, or a transient
                # backend error, must not kill the producer loop.
                if not self._running:
                    break

    def start(self):
        # Mirrors the prior contract: start() while paused opens nothing.
        if not self._paused:
            self.resume()

    def resume(self):
        self._paused = False
        if self._stream is None:
            self._open_stream()
        self._stream.start()
        if not self._running:
            self._running = True
            self._producer = threading.Thread(target=self._run_producer, daemon=True)
            self._producer.start()

    def pause(self):
        # Keep the stream + producer alive but feed silence, so playback stays
        # glitch-free and resumes instantly.
        self._paused = True

    def stop(self):
        self._running = False
        if self._producer is not None:
            self._producer.join(timeout=1.0)
            self._producer = None
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
        if len(samples) == 0:
            raise ValueError("sample must contain at least one frame")
        with self._lock:
            self._loaded_sample = samples
            self.engine.sources.texture.load_sample(samples)

    def set_root_midi(self, root_midi):
        with self._lock:
            self._root_midi = int(root_midi)
            self._root_target = float(root_midi)
            self.engine = SoundscapeEngine(
                samplerate=self.samplerate, seed=self._seed, root_midi=self._root_midi
            )
            if self._loaded_sample is not None:
                self.engine.sources.texture.load_sample(self._loaded_sample)

    def set_root(self, target_midi):
        with self._lock:
            self._root_target = float(target_midi)
            self.engine.set_root(target_midi)
