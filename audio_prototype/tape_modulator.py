import numpy as np

from modulation import clamp, hue_to_bipolar, sat_to_unit, val_to_unit
from modulation import soft_clip

SAMPLE_RATE_DEFAULT = 44100
AMPLITUDE_FOCUS_BASE_HZ = 1200.0
AMPLITUDE_FOCUS_SPAN_OCTAVES = 2.0
DEFAULT_TAPE_COLUMNS = {
    "wow": 1.0,
    "flutter": 1.0,
    "tone": 0.0,
    "dropout": 0.0,
}


def amplitude_focus_controls(hue, sat, val, bpm):
    sat = sat_to_unit(sat)
    val = val_to_unit(val)
    bpm = clamp(bpm, 20.0, 300.0)
    bpm_norm = (bpm - 20.0) / 280.0
    return {
        "focus_hz": AMPLITUDE_FOCUS_BASE_HZ
        * 2.0 ** (AMPLITUDE_FOCUS_SPAN_OCTAVES * hue_to_bipolar(hue)),
        "contrast": 0.5 + 1.5 * sat,
        "smoothing_hz": 0.8 + 10.0 * bpm_norm + 8.0 * sat,
        "depth_scale": val,
    }


def tape_column_controls(layers):
    controls = dict(DEFAULT_TAPE_COLUMNS)
    if not layers:
        return controls

    for layer in layers:
        strength = 0.45 + 0.55 * val_to_unit(layer["val"])
        sat = 0.55 + 0.45 * sat_to_unit(layer["sat"])
        col = int(clamp(layer.get("patch_col", 0), 0, 4))
        if col == 0:
            controls["wow"] += 1.25 * strength
        elif col == 1:
            controls["flutter"] += 1.35 * strength
        elif col == 2:
            controls["tone"] += 0.38 * strength * sat * hue_to_bipolar(
                layer.get("hue", 0.5)
            )
        elif col == 3:
            controls["dropout"] += 0.55 * strength
        else:
            controls["wow"] += 0.35 * strength
            controls["flutter"] += 0.35 * strength

    controls["wow"] = min(3.0, controls["wow"])
    controls["flutter"] = min(3.2, controls["flutter"])
    controls["tone"] = clamp(controls["tone"], -0.45, 0.45)
    controls["dropout"] = min(0.75, controls["dropout"])
    return controls


class TapeModulator:
    """Applies organic, tape-like warble (pitch) and bloom (amplitude)
    modulation to samples read from a looping buffer.

    Rate (wow/flutter speed, bloom breathing speed) is anchored to the
    combined BPM (`rate_hz`); depth is anchored to combined HSV, already
    computed by `modulation.combine_layers` before calling `process`.
    """

    def __init__(self, samplerate=SAMPLE_RATE_DEFAULT, seed=None):
        self.samplerate = samplerate
        self._rng = np.random.default_rng(seed)
        self._read_pos = 0.0
        self._wow_phase = 0.0
        self._flutter_phase = 0.0
        self._jitter_state = 0.0
        self._bloom_state = 0.0
        self._dropout_state = 0.0
        self._tone_low_state = 0.0
        # Most recent control signals from process(), for visualization:
        # last_warble_signal is the depth-scaled pitch deviation (rate - 1),
        # last_gain is the bloom amplitude multiplier (centered on 1.0).
        self.last_warble_signal = np.zeros(0, dtype=np.float32)
        self.last_gain = np.ones(0, dtype=np.float32)

    def _one_pole_alpha(self, cutoff_hz):
        cutoff_hz = max(cutoff_hz, 1e-6)
        return float(np.exp(-2.0 * np.pi * cutoff_hz / self.samplerate))

    def _smoothed_noise(self, n, state, cutoff_hz):
        alpha = self._one_pole_alpha(cutoff_hz)
        raw = self._rng.uniform(-1.0, 1.0, size=n)
        out = np.empty(n, dtype=np.float64)
        prev = state
        for i in range(n):
            prev = alpha * prev + (1.0 - alpha) * raw[i]
            out[i] = prev
        return out, prev

    def _source_contour(self, samples, controls):
        env = np.abs(samples).astype(np.float64)
        mean = float(np.mean(env))
        if mean <= 1e-9:
            return np.zeros(len(samples), dtype=np.float64)

        contour = env / mean - 1.0
        contour *= controls["contrast"]
        alpha = self._one_pole_alpha(controls["smoothing_hz"])
        out = np.empty(len(samples), dtype=np.float64)
        prev = self._bloom_state
        for i, sample in enumerate(contour):
            prev = alpha * prev + (1.0 - alpha) * sample
            out[i] = prev
        self._bloom_state = prev
        return np.clip(out, -1.0, 1.0)

    def _tone_color(self, samples, tone):
        tone = clamp(tone, -0.45, 0.45)
        if abs(tone) < 1e-9:
            return samples
        alpha = self._one_pole_alpha(1400.0)
        low = np.empty(len(samples), dtype=np.float64)
        prev = self._tone_low_state
        for i, sample in enumerate(samples):
            prev = alpha * prev + (1.0 - alpha) * sample
            low[i] = prev
        self._tone_low_state = prev
        high = samples - low
        if tone < 0.0:
            amount = abs(tone)
            return samples + 0.16 * amount * low - 0.10 * amount * high
        return samples - 0.08 * tone * low + 0.14 * tone * high

    def process(
        self,
        loop_array,
        frames,
        warble_depth,
        bloom_depth,
        rate_hz,
        hue=0.0,
        sat=0.5,
        val=1.0,
        tape_controls=None,
    ):
        loop_len = len(loop_array)
        t = np.arange(frames) / self.samplerate

        # Wow: slow drift. Flutter: faster wobble. Both scaled by BPM-derived
        # rate_hz but kept in their natural physical ranges.
        wow_rate = 0.1 + 0.15 * rate_hz
        flutter_rate = 4.0 + 2.0 * rate_hz

        wow = np.sin(2.0 * np.pi * wow_rate * t + self._wow_phase)
        flutter = np.sin(2.0 * np.pi * flutter_rate * t + self._flutter_phase)
        jitter, self._jitter_state = self._smoothed_noise(
            frames, self._jitter_state, cutoff_hz=1.0 + rate_hz
        )

        self._wow_phase = (
            self._wow_phase + 2.0 * np.pi * wow_rate * frames / self.samplerate
        ) % (2.0 * np.pi)
        self._flutter_phase = (
            self._flutter_phase + 2.0 * np.pi * flutter_rate * frames / self.samplerate
        ) % (2.0 * np.pi)

        tape_controls = DEFAULT_TAPE_COLUMNS if tape_controls is None else tape_controls
        raw_warble = (
            0.6 * tape_controls["wow"] * wow
            + 0.3 * tape_controls["flutter"] * flutter
            + 0.1 * jitter
        )
        raw_warble /= max(1.0, 0.6 * tape_controls["wow"] + 0.3 * tape_controls["flutter"])
        rate_per_sample = 1.0 + warble_depth * raw_warble

        # Exclusive prefix sum: the i-th output sample reads from the
        # position *before* applying increment i, so depth=0 (rate=1
        # everywhere) reproduces the loop exactly with no offset.
        cum = np.cumsum(rate_per_sample)
        positions = (self._read_pos + cum - rate_per_sample) % loop_len
        self._read_pos = float((self._read_pos + cum[-1]) % loop_len)

        idx0 = np.floor(positions).astype(np.int64) % loop_len
        idx1 = (idx0 + 1) % loop_len
        frac = positions - np.floor(positions)
        output = loop_array[idx0] * (1.0 - frac) + loop_array[idx1] * frac

        controls = amplitude_focus_controls(hue, sat, val, rate_hz * 60.0)
        contour = self._source_contour(output, controls)
        gain = np.clip(
            1.0 + bloom_depth * controls["depth_scale"] * contour,
            0.05,
            1.95,
        )
        if tape_controls["dropout"] > 1e-9:
            dropout_noise, self._dropout_state = self._smoothed_noise(
                frames,
                self._dropout_state,
                cutoff_hz=0.5 + 0.4 * rate_hz,
            )
            dropout = np.clip((1.0 - dropout_noise) * 0.5, 0.0, 1.0)
            gain *= 1.0 - tape_controls["dropout"] * dropout
        output = output * gain

        output = self._tone_color(output, tape_controls["tone"])

        self.last_warble_signal = (warble_depth * raw_warble).astype(np.float32)
        self.last_gain = gain.astype(np.float32)

        return soft_clip(output).astype(np.float32)
