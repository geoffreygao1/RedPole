import numpy as np

from modulation import clamp, hue_to_bipolar, sat_to_unit, val_to_unit

MIN_RATE_HZ = 0.08
MAX_RATE_HZ = 9.0
MIN_DEPTH_SAMPLES = 0.4
MAX_DEPTH_SAMPLES = 9.0
VOICE_LEVEL = 0.416  # +30% per user request (was 0.32)
EVENT_MIN_SECONDS = 0.18
EVENT_MAX_SECONDS = 0.75
EVENT_DENSITY_TARGET = 2.5
EVENT_JITTER = 0.75


def fm_layer_controls(layer):
    bpm = clamp(layer["bpm"], 20.0, 300.0)
    sat = sat_to_unit(layer["sat"])
    val = val_to_unit(layer["val"])
    hue_pos = hue_to_bipolar(layer["hue"])
    bpm_norm = (bpm - 20.0) / 280.0
    return {
        "rate_hz": MIN_RATE_HZ + (MAX_RATE_HZ - MIN_RATE_HZ) * bpm_norm,
        "depth_samples": (
            MIN_DEPTH_SAMPLES
            + (MAX_DEPTH_SAMPLES - MIN_DEPTH_SAMPLES) * val * (0.35 + 0.65 * sat)
        ),
        "tone_bias": hue_pos,
        "noise_mix": 0.12 + 0.35 * sat,
        "event_interval": EVENT_MIN_SECONDS
        + (EVENT_MAX_SECONDS - EVENT_MIN_SECONDS) * (1.0 - val),
    }


class FrequencyModProcessor:
    """Source-derived micro-FM.

    This is not a pitched FM synth voice. It reads the source around the
    current playback position with tiny audio/sub-audio displacement, then
    returns only the difference from the dry source. Multiple layers add
    independent modulators, normalized by sqrt(N), so density increases
    timbral complexity more than level.
    """

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._seed = seed
        self._voices = {}
        self._last_base_pos = 0.0

    def set_analysis(self, _analysis):
        # Kept for AudioEngine compatibility with the old spectral slot.
        self._voices = {}

    def process(self, loop_array, frames, layers, live_frame=None, scan_start=None):
        if not layers or len(loop_array) == 0:
            self._voices = {}
            return np.zeros(frames, dtype=np.float32)

        loop = np.asarray(loop_array, dtype=np.float64)
        base_pos = 0.0 if scan_start is None else float(scan_start) * 1024.0
        self._last_base_pos = base_pos
        dry = self._read(loop, base_pos + np.arange(frames))
        displacement = np.zeros(frames, dtype=np.float64)

        active = set()
        for layer in layers:
            vid = layer["id"]
            active.add(vid)
            voice = self._voices.get(vid)
            if voice is None:
                seed = None if self._seed is None else self._seed + vid
                rng = np.random.default_rng(seed)
                voice = {
                    "rng": rng,
                    "phase": rng.uniform(0.0, 2.0 * np.pi),
                    "noise": 0.0,
                    "until_event": int(rng.uniform(0.0, 0.12) * self.samplerate),
                    "event_remaining": 0,
                    "event_total": 1,
                }
                self._voices[vid] = voice

            controls = fm_layer_controls(layer)
            event_env = self._event_envelope(voice, frames, controls, len(layers))
            if not np.any(event_env > 0.0):
                continue
            t = np.arange(frames) / self.samplerate
            rate = controls["rate_hz"]
            phase = voice["phase"]
            tone_rate = rate * (1.0 + 0.35 * controls["tone_bias"])
            sine = np.sin(2.0 * np.pi * tone_rate * t + phase)
            second = 0.45 * np.sin(2.0 * np.pi * rate * 1.618 * t + phase * 0.37)
            noise, voice["noise"] = self._smoothed_noise(
                voice["rng"],
                frames,
                voice["noise"],
                cutoff_hz=max(0.5, rate * 1.5),
            )
            mod = (1.0 - controls["noise_mix"]) * (sine + second) + controls[
                "noise_mix"
            ] * noise
            displacement += controls["depth_samples"] * event_env * mod
            voice["phase"] = (
                phase + 2.0 * np.pi * tone_rate * frames / self.samplerate
            ) % (2.0 * np.pi)

        self._voices = {k: v for k, v in self._voices.items() if k in active}
        displacement /= max(1.0, np.sqrt(len(layers)))
        warped = self._read(loop, base_pos + np.arange(frames) + displacement)
        wet = VOICE_LEVEL * (warped - dry)
        return np.tanh(wet).astype(np.float32)

    def _event_envelope(self, voice, frames, controls, layer_count):
        rng = voice["rng"]
        env = np.zeros(frames, dtype=np.float64)
        i = 0
        probability = min(1.0, EVENT_DENSITY_TARGET / max(1, layer_count))
        while i < frames:
            if voice["event_remaining"] > 0:
                n = min(frames - i, voice["event_remaining"])
                start_remaining = voice["event_remaining"]
                remaining = start_remaining - np.arange(n)
                progress = 1.0 - remaining / max(1, voice["event_total"])
                env[i:i + n] = np.sin(np.pi * progress) ** 2
                voice["event_remaining"] -= n
                i += n
                continue

            if voice["until_event"] > 0:
                n = min(frames - i, voice["until_event"])
                voice["until_event"] -= n
                i += n
                continue

            if rng.random() < probability:
                duration = rng.uniform(0.045, 0.16)
                voice["event_total"] = max(1, int(duration * self.samplerate))
                voice["event_remaining"] = voice["event_total"]

            interval = controls["event_interval"] * rng.uniform(
                1.0 - EVENT_JITTER, 1.0 + EVENT_JITTER
            )
            voice["until_event"] = max(1, int(interval * self.samplerate))

        return env

    def _smoothed_noise(self, rng, frames, state, cutoff_hz):
        alpha = float(np.exp(-2.0 * np.pi * cutoff_hz / self.samplerate))
        raw = rng.uniform(-1.0, 1.0, size=frames)
        out = np.empty(frames, dtype=np.float64)
        prev = state
        for i, sample in enumerate(raw):
            prev = alpha * prev + (1.0 - alpha) * sample
            out[i] = prev
        return out, prev

    def _read(self, loop, positions):
        loop_len = len(loop)
        positions = np.asarray(positions, dtype=np.float64) % loop_len
        idx0 = np.floor(positions).astype(np.int64)
        idx1 = (idx0 + 1) % loop_len
        frac = positions - idx0
        return loop[idx0] * (1.0 - frac) + loop[idx1] * frac
