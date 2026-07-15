import threading

import numpy as np


class RingBuffer:
    """Fixed-size rolling buffer of the most recent audio samples, for the
    waveform visualizer. Not used for playback -- only for display."""

    def __init__(self, capacity):
        self.capacity = capacity
        self._buffer = np.zeros(capacity, dtype=np.float32)
        self._lock = threading.Lock()

    def write(self, chunk):
        chunk = np.asarray(chunk, dtype=np.float32)
        n = len(chunk)
        with self._lock:
            if n >= self.capacity:
                self._buffer = chunk[-self.capacity :].copy()
            else:
                self._buffer = np.concatenate([self._buffer[n:], chunk])

    def read_latest(self, n):
        with self._lock:
            if n >= self.capacity:
                return self._buffer.copy()
            return self._buffer[-n:].copy()
