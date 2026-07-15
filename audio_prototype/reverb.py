import numpy as np

COMB_DELAYS = (1310, 1636, 1813, 1927)
COMB_FEEDBACK = 0.84
ALLPASS_DELAYS = (556, 225)
ALLPASS_GAIN = 0.7
SPACE_STYLES = ("bright_room", "dark_medium", "large_hall", "ambient", "wash")
STYLE_TAPS = {
    "bright_room": ((0.011, 0.42), (0.019, 0.28)),
    "dark_medium": ((0.018, 0.38), (0.037, 0.30), (0.063, 0.18)),
    "large_hall": ((0.029, 0.34), (0.061, 0.27), (0.113, 0.22), (0.157, 0.12)),
    "ambient": (
        (0.041, 0.33),
        (0.089, 0.30),
        (0.143, 0.24),
        (0.197, 0.18),
        (0.251, 0.12),
    ),
    "wash": (
        (0.093, 0.34),
        (0.177, 0.32),
        (0.293, 0.29),
        (0.421, 0.24),
        (0.611, 0.19),
        (0.783, 0.14),
    ),
}


class _Comb:
    """Feedback comb with no direct path in the wet output."""

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
            y = self.buf[:m].copy()
            out[i:i + m] = y
            self.buf = np.concatenate([self.buf[m:], x[i:i + m] + self.feedback * y])
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


class _EarlyReflections:
    def __init__(self, samplerate, max_delay_seconds=1.15):
        self.samplerate = samplerate
        self.max_delay = max(1, int(max_delay_seconds * samplerate))
        self.buf = np.zeros(self.max_delay)

    def process(self, x, taps):
        x = np.asarray(x, dtype=np.float64)
        n = len(x)
        hist = np.concatenate([self.buf, x])
        out = np.zeros(n, dtype=np.float64)
        for delay_seconds, gain in taps:
            delay = min(self.max_delay, max(1, int(delay_seconds * self.samplerate)))
            start = self.max_delay - delay
            out += gain * hist[start:start + n]
        self.buf = hist[-self.max_delay:]
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
        self._early = _EarlyReflections(samplerate)
        self.space_style = "bright_room"
        self.space_size = 0.35
        self.diffusion = 0.45

    def set_feedback(self, feedback):
        for comb in self._combs:
            comb.feedback = feedback

    def set_cutoff(self, cutoff_hz):
        self._lowpass.set_cutoff(cutoff_hz)

    def set_space(self, style="bright_room", size=0.35, diffusion=0.45):
        if style not in SPACE_STYLES:
            raise ValueError(f"Unknown reverb style: {style}")
        self.space_style = style
        self.space_size = float(np.clip(size, 0.0, 1.0))
        self.diffusion = float(np.clip(diffusion, 0.0, 1.0))
        if style == "wash":
            allpass_gain = 0.72 + 0.12 * self.diffusion
        else:
            allpass_gain = 0.52 + 0.25 * self.diffusion
        for allpass in self._allpasses:
            allpass.gain = allpass_gain

    def _space_taps(self):
        size_scale = 0.7 + 0.8 * self.space_size
        gain_scale = 0.25 + 0.85 * self.diffusion
        if self.space_style == "wash":
            size_scale = 0.95 + 0.45 * self.space_size
            gain_scale = 0.55 + 0.75 * self.diffusion
        return tuple(
            (delay * size_scale, gain * gain_scale)
            for delay, gain in STYLE_TAPS[self.space_style]
        )

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        spacious = self._early.process(x, self._space_taps())
        y = sum(c.process(spacious) for c in self._combs) / len(self._combs)
        for ap in self._allpasses:
            y = ap.process(y)
        return self._lowpass.process(y).astype(np.float32)
