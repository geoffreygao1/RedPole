import numpy as np

from modulation import hue_to_bipolar, sat_to_unit, val_to_unit

GRAIN_MIN_SECONDS = 0.06
GRAIN_MAX_SECONDS = 0.25
GRAIN_JITTER_SECONDS = 0.025
SOURCE_JITTER_SECONDS = 0.12
GRAINS_PER_EVENT = 2
EVENT_INTERVAL_JITTER = 0.65
FOCUS_BASE_HZ = 1200.0
FOCUS_SPAN_OCTAVES = 2.0
SEARCH_MIN_SECONDS = 0.08
SEARCH_MAX_SECONDS = 0.55
SMEAR_MIN_SECONDS = 0.12
SMEAR_MAX_SECONDS = 0.75
CANDIDATES_PER_GRAIN = 4
OCTAVE_THRESHOLD = 0.5
FULL_DENSITY_LAYERS = 2.0


def _clamp(value, min_v, max_v):
    return max(min_v, min(max_v, value))


def granular_focus_controls(layer):
    sat = sat_to_unit(layer["sat"])
    val = val_to_unit(layer["val"])
    bpm = _clamp(layer["bpm"], 20.0, 300.0)
    bpm_norm = (bpm - 20.0) / 280.0
    return {
        "centroid_target": FOCUS_BASE_HZ
        * 2.0 ** (FOCUS_SPAN_OCTAVES * hue_to_bipolar(layer["hue"])),
        "search_radius": SEARCH_MAX_SECONDS
        - sat * (SEARCH_MAX_SECONDS - SEARCH_MIN_SECONDS),
        "source_smear": SMEAR_MAX_SECONDS
        - bpm_norm * (SMEAR_MAX_SECONDS - SMEAR_MIN_SECONDS),
        "grain_interval": 0.18 + 0.22 * (1.0 - val),
        "event_jitter": EVENT_INTERVAL_JITTER,
    }


def granular_octave_ratio(layer):
    return 1.0


def granular_pitch_ratios(layer):
    return (1.0,)


def granular_pitch_weights(layer):
    return (1.0,)


def _spectral_centroid(x, samplerate):
    x = np.asarray(x, dtype=np.float64)
    if len(x) == 0:
        return 0.0, 0.0
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    energy = float(np.sum(mag))
    if energy <= 1e-12:
        return 0.0, 0.0
    freqs = np.fft.rfftfreq(len(x), 1.0 / samplerate)
    return float(np.sum(freqs * mag) / energy), energy


class GranularProcessor:
    """Per-layer grain streams sampled from the loop.

    hue -> source-band focus plus octave-only grain pitch, bpm -> source
    motion, sat -> grain size and focus width, val -> stream level.
    Grains are rendered into a per-voice overlap-add buffer at trigger
    time, so per-block cost is just mixing.
    """

    STREAM_LEVEL = 0.65  # +30% per user request (was 0.5)

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._seed = seed
        self._voices = {}

    def _new_voice(self, vid, frames):
        seed = None if self._seed is None else self._seed + vid
        return {
            "rng": np.random.default_rng(seed),
            "buffer": np.zeros(frames),
            "until_grain": 0,
        }

    def process(self, loop_array, frames, layers, source_pos=0):
        out = np.zeros(frames)
        if not layers or len(loop_array) == 0:
            self._voices = {}
            return out.astype(np.float32)

        active = set()
        for layer in layers:
            vid = layer["id"]
            active.add(vid)
            voice = self._voices.get(vid)
            if voice is None:
                voice = self._new_voice(vid, frames)
                self._voices[vid] = voice

            min_len = frames + int(
                (GRAIN_MAX_SECONDS + GRAIN_JITTER_SECONDS) * self.samplerate * 2
            )
            if len(voice["buffer"]) < min_len:
                voice["buffer"] = np.concatenate(
                    [voice["buffer"], np.zeros(min_len - len(voice["buffer"]))]
                )

            grain_len = int(
                (GRAIN_MIN_SECONDS
                + sat_to_unit(layer["sat"]) * (GRAIN_MAX_SECONDS - GRAIN_MIN_SECONDS))
                * self.samplerate
            )
            level = self.STREAM_LEVEL * val_to_unit(layer["val"])
            controls = granular_focus_controls(layer)
            controls["event_probability"] = min(1.0, FULL_DENSITY_LAYERS / len(layers))
            ratios = granular_pitch_ratios(layer)
            ratio_weights = granular_pitch_weights(layer)
            grain_interval = max(1, int(controls["grain_interval"] * self.samplerate))

            t = voice["until_grain"]
            while t < frames:
                if voice["rng"].random() < controls["event_probability"]:
                    self._emit_event(
                        voice, loop_array, t, grain_len, ratios, ratio_weights, level,
                        source_pos + t, controls
                    )
                t += self._next_grain_interval(voice, grain_interval, controls)
            voice["until_grain"] = t - frames

            out += voice["buffer"][:frames]
            voice["buffer"] = np.concatenate(
                [voice["buffer"][frames:], np.zeros(frames)]
            )

        self._voices = {k: v for k, v in self._voices.items() if k in active}
        out /= max(1.0, np.sqrt(len(layers)))
        return out.astype(np.float32)

    def _next_grain_interval(self, voice, grain_interval, controls):
        rng = voice["rng"]
        jitter = controls["event_jitter"]
        scale = rng.uniform(1.0 - jitter, 1.0 + jitter)
        return max(1, int(grain_interval * scale))

    def _emit_event(
        self, voice, loop_array, offset, grain_len, ratios, ratio_weights, level, source_pos, controls
    ):
        rng = voice["rng"]
        for grain_index in range(GRAINS_PER_EVENT):
            ratio = float(rng.choice(ratios, p=ratio_weights))
            if grain_index == 0:
                source_offset = 0
            else:
                source_offset = int(
                    rng.uniform(-controls["source_smear"], controls["source_smear"])
                    * self.samplerate
                )
            event_offset = offset + int(
                rng.uniform(0.0, GRAIN_JITTER_SECONDS) * self.samplerate
            )
            self._emit_grain(
                voice,
                loop_array,
                event_offset,
                grain_len,
                ratio,
                (level * (1.18 if ratio < 1.0 else 1.0)) / np.sqrt(GRAINS_PER_EVENT),
                source_pos + source_offset,
                controls,
            )

    def _emit_grain(
        self, voice, loop_array, offset, grain_len, ratio, level, source_pos, controls
    ):
        rng = voice["rng"]
        loop_len = len(loop_array)
        start = self._select_source_start(
            voice, loop_array, source_pos, grain_len, controls
        )
        src_len = max(2, int(grain_len * ratio))
        start -= src_len // 3
        idx = (start + np.arange(src_len)) % loop_len
        src = loop_array[idx]
        grain = np.interp(
            np.linspace(0.0, src_len - 1.0, grain_len),
            np.arange(src_len),
            src,
        )
        grain *= np.hanning(grain_len) * level * rng.uniform(0.6, 1.0)
        pos = offset
        end = pos + grain_len
        if end > len(voice["buffer"]):
            voice["buffer"] = np.concatenate(
                [voice["buffer"], np.zeros(end - len(voice["buffer"]))]
            )
        voice["buffer"][pos:end] += grain

    def _select_source_start(self, voice, loop_array, source_pos, grain_len, controls):
        rng = voice["rng"]
        loop_len = len(loop_array)
        radius = int(
            (controls["search_radius"] + controls["source_smear"]) * self.samplerate
        )
        candidates = [int(source_pos)]
        if radius > 0:
            candidates.extend(
                int(source_pos + rng.integers(-radius, radius + 1))
                for _ in range(CANDIDATES_PER_GRAIN - 1)
            )

        target = controls["centroid_target"]
        best_start = candidates[0]
        best_score = float("inf")
        for start in candidates:
            idx = (start + np.arange(grain_len)) % loop_len
            centroid, energy = _spectral_centroid(loop_array[idx], self.samplerate)
            if energy <= 1e-12 or centroid <= 0.0:
                score = float("inf")
            else:
                score = abs(np.log2(centroid / target)) - 0.02 * np.log1p(energy)
            if score < best_score:
                best_score = score
                best_start = start
        return best_start
