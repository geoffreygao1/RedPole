import numpy as np


def clamp(value, min_v, max_v):
    return max(min_v, min(max_v, value))


def density_controls(wet_voice_count, reverb_layer_count):
    """Return wet-bus controls derived from active additive density."""
    wet_voice_count = max(0, int(wet_voice_count))
    reverb_layer_count = max(0, int(reverb_layer_count))
    total_density = wet_voice_count + 0.5 * reverb_layer_count
    normalized = clamp(total_density / 20.0, 0.0, 1.0)

    return {
        "density": normalized,
        "wet_gain": 1.0 / (1.0 + 0.034 * wet_voice_count),
        "feedback_trim": 0.12 * normalized,
        "cutoff_scale": 1.0 - 0.45 * normalized,
        "highpass_hz": 35.0 + 145.0 * normalized,
        "low_mid_gain": 1.0 - 0.35 * normalized,
    }


class OnePoleHighpass:
    """First-order high-pass implemented as x - lowpass(x)."""

    def __init__(self, samplerate, cutoff_hz):
        self.samplerate = samplerate
        self._low_state = 0.0
        self.set_cutoff(cutoff_hz)

    def set_cutoff(self, cutoff_hz):
        self.cutoff_hz = float(cutoff_hz)
        self._alpha = 1.0 - np.exp(-2.0 * np.pi * self.cutoff_hz / self.samplerate)

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        out = np.empty(len(x), dtype=np.float64)
        state = self._low_state
        alpha = self._alpha
        for i, sample in enumerate(x):
            state += alpha * (sample - state)
            out[i] = sample - state
        self._low_state = state
        return out


class OnePoleLowpass:
    def __init__(self, samplerate, cutoff_hz):
        self.samplerate = samplerate
        self._state = 0.0
        self.set_cutoff(cutoff_hz)

    def set_cutoff(self, cutoff_hz):
        self.cutoff_hz = float(cutoff_hz)
        self._alpha = 1.0 - np.exp(-2.0 * np.pi * self.cutoff_hz / self.samplerate)

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        out = np.empty(len(x), dtype=np.float64)
        state = self._state
        alpha = self._alpha
        for i, sample in enumerate(x):
            state += alpha * (sample - state)
            out[i] = state
        self._state = state
        return out


class WetBusManager:
    """Density-aware wet-bus level and tone cleanup."""

    def __init__(self, samplerate):
        self.samplerate = samplerate
        self._highpass = OnePoleHighpass(samplerate, cutoff_hz=35.0)
        self._low_mid = OnePoleLowpass(samplerate, cutoff_hz=650.0)

    def controls(self, wet_voice_count, reverb_layer_count):
        return density_controls(wet_voice_count, reverb_layer_count)

    def process(self, wet, wet_voice_count, reverb_layer_count):
        wet = np.asarray(wet, dtype=np.float64)
        controls = self.controls(wet_voice_count, reverb_layer_count)
        if controls["density"] <= 0.0:
            return wet.astype(np.float32)
        self._highpass.set_cutoff(controls["highpass_hz"])

        highpassed = self._highpass.process(wet)
        low_mid = self._low_mid.process(highpassed)
        cleaned = highpassed - (1.0 - controls["low_mid_gain"]) * low_mid
        return (controls["wet_gain"] * cleaned).astype(np.float32)
