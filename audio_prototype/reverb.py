import numpy as np

COMB_DELAYS = (1310, 1636, 1813, 1927)
COMB_FEEDBACK = 0.84
ALLPASS_DELAYS = (556, 225)
ALLPASS_GAIN = 0.7


class _Comb:
    """Feedback comb: y[n] = x[n] + g * y[n - D].

    Processed in chunks of at most D samples so the feedback only ever
    reaches into already-computed output (held in `buf`, oldest first) --
    exact recursion, fully vectorized per chunk.
    """

    def __init__(self, delay, feedback):
        self.delay = delay
        self.feedback = feedback
        self.buf = np.zeros(delay)

    def process(self, x):
        n = len(x)
        out = np.empty(n)
        i = 0
        while i < n:
            m = min(self.delay, n - i)
            y = x[i:i + m] + self.feedback * self.buf[:m]
            out[i:i + m] = y
            self.buf = np.concatenate([self.buf[m:], y])
            i += m
        return out


class _Allpass:
    """Allpass: y[n] = -g * x[n] + x[n - D] + g * y[n - D]."""

    def __init__(self, delay, gain):
        self.delay = delay
        self.gain = gain
        self.xbuf = np.zeros(delay)
        self.ybuf = np.zeros(delay)

    def process(self, x):
        n = len(x)
        out = np.empty(n)
        i = 0
        while i < n:
            m = min(self.delay, n - i)
            y = -self.gain * x[i:i + m] + self.xbuf[:m] + self.gain * self.ybuf[:m]
            out[i:i + m] = y
            self.xbuf = np.concatenate([self.xbuf[m:], x[i:i + m]])
            self.ybuf = np.concatenate([self.ybuf[m:], y])
            i += m
        return out


class OnePoleLowpass:
    """y[n] = y[n-1] + a * (x[n] - y[n-1]); colors the reverb tail."""

    def __init__(self, samplerate, cutoff_hz):
        self.samplerate = samplerate
        self._state = 0.0
        self.set_cutoff(cutoff_hz)

    def set_cutoff(self, cutoff_hz):
        self.cutoff_hz = cutoff_hz
        self._alpha = 1.0 - np.exp(-2.0 * np.pi * cutoff_hz / self.samplerate)

    def process(self, x):
        out = np.empty(len(x))
        state = self._state
        alpha = self._alpha
        for i in range(len(x)):
            state += alpha * (x[i] - state)
            out[i] = state
        self._state = state
        return out


DEFAULT_CUTOFF = 7800.0


class SchroederReverb:
    """Classic Schroeder reverb: 4 parallel feedback combs into 2 series
    allpasses, then a one-pole lowpass that colors the tail. Output is
    100% wet; the caller owns the dry/wet mix. Feedback (decay length)
    and cutoff (tail brightness) are adjustable at block rate."""

    def __init__(self, samplerate=44100):
        self.samplerate = samplerate
        self._combs = [_Comb(d, COMB_FEEDBACK) for d in COMB_DELAYS]
        self._allpasses = [_Allpass(d, ALLPASS_GAIN) for d in ALLPASS_DELAYS]
        self._lowpass = OnePoleLowpass(samplerate, DEFAULT_CUTOFF)

    def set_feedback(self, feedback):
        for comb in self._combs:
            comb.feedback = feedback

    def set_cutoff(self, cutoff_hz):
        self._lowpass.set_cutoff(cutoff_hz)

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        y = sum(c.process(x) for c in self._combs) / len(self._combs)
        for ap in self._allpasses:
            y = ap.process(y)
        return self._lowpass.process(y).astype(np.float32)
