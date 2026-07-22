"""PaulXStretch-style spectral smear for synth mode.

A streaming phase-vocoder: it keeps each STFT frame's magnitudes but
randomizes their phases, turning short loops and transients into a suspended
wash.
"""

import numpy as np

FFT_SIZE = 2048
HOP = FFT_SIZE // 4
WINDOW_NORM = (FFT_SIZE / HOP) * 0.5


class SpectralSmear:
    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._rng = np.random.default_rng(seed)
        self._window = np.sqrt(np.clip(np.hanning(FFT_SIZE), 0.0, None))
        self._in = np.zeros(0, dtype=np.float64)
        self._out = np.zeros(FFT_SIZE, dtype=np.float64)
        self._tail = np.zeros(FFT_SIZE, dtype=np.float64)
        self._prev_mag = None

    def process(self, x, suspension=0.0, smear=0.0):
        x = np.asarray(x, dtype=np.float64)
        self._in = np.concatenate([self._in, x])
        suspension = float(np.clip(suspension, 0.0, 1.0))
        smear = float(np.clip(smear, 0.0, 1.0))
        mag_alpha = 0.95 * suspension

        while len(self._in) >= FFT_SIZE:
            frame = self._in[:FFT_SIZE] * self._window
            spec = np.fft.rfft(frame)
            mag = np.abs(spec)
            if self._prev_mag is None or len(self._prev_mag) != len(mag):
                self._prev_mag = mag
            mag = mag_alpha * self._prev_mag + (1.0 - mag_alpha) * mag
            self._prev_mag = mag
            phase = np.angle(spec) + smear * self._rng.uniform(
                -np.pi, np.pi, size=len(spec)
            )
            frame_out = np.fft.irfft(mag * np.exp(1j * phase), n=FFT_SIZE)
            frame_out *= self._window / WINDOW_NORM
            self._out += frame_out
            self._tail = np.concatenate([self._tail, self._out[:HOP].copy()])
            self._out = np.concatenate([self._out[HOP:], np.zeros(HOP)])
            self._in = self._in[HOP:]

        n = len(x)
        if len(self._tail) < n:
            out = np.zeros(n, dtype=np.float64)
            out[: len(self._tail)] = self._tail
            self._tail = np.zeros(0, dtype=np.float64)
            return out.astype(np.float32)
        out = self._tail[:n]
        self._tail = self._tail[n:]
        return out.astype(np.float32)
