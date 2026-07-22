"""Synth-mode ambient effects built for generated tones.

The loop effects rearrange source audio. This processor is intentionally
different: it reads each generated synth voice at unison and turns it into
slow bloom, halo, tide, resonance, or space layers for sound-bath use.
"""

import numpy as np

from modulation import clamp, sat_to_unit, soft_clip, val_to_unit


ROLE_BY_ROW = ("stretch", "delay", "reverb", "stereo", "shape")
ROLE_BY_ENGINE = {
    "microloop": "stretch",
    "granules": "delay",
    "glitch": "reverb",
    "multidelay": "stereo",
    "tape": "shape",
}


def synth_bath_role(layer):
    if "patch_row" in layer:
        row = int(clamp(layer["patch_row"], 0, len(ROLE_BY_ROW) - 1))
        return ROLE_BY_ROW[row]
    return ROLE_BY_ENGINE.get(layer["engine"], "halo")


def synth_bath_controls(layer):
    col = int(clamp(layer.get("patch_col", 2), 0, 4))
    bpm = clamp(layer["bpm"], 20.0, 300.0)
    bpm_u = (bpm - 20.0) / 280.0
    sat = sat_to_unit(layer["sat"])
    val = val_to_unit(layer["val"])
    depth = 0.42 + 0.11 * col
    return {
        "role": synth_bath_role(layer),
        "column": col,
        "depth": depth,
        "motion_hz": 1.0 / (7.5 - 4.4 * bpm_u),
        "tone": 0.18 + 0.52 * val,
        "diffusion": 0.24 + 0.12 * col + 0.18 * sat,
        "level": 0.22 + 0.58 * val,
    }


class SynthBathProcessor:
    """Unison-only synth wet processor for ambient sound-bath layers."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._seed = seed
        self._voices = {}
        self.debug_read_ratios = []

    def process(self, frames, layers, source_arrays, source_positions=None, low_cpu=False):
        self.debug_read_ratios = []
        if not layers:
            self._voices = {}
            return np.zeros(frames, dtype=np.float32)

        source_positions = source_positions or {}
        out = np.zeros(frames, dtype=np.float64)
        active = set()

        for layer in layers:
            vid = int(layer["id"])
            source = None if source_arrays is None else source_arrays.get(vid)
            if source is None or len(source) == 0:
                continue

            active.add(vid)
            voice = self._voice_for(vid)
            controls = synth_bath_controls(layer)
            source_pos = int(source_positions.get(vid, 0))
            block = self._read_unison(np.asarray(source, dtype=np.float64), source_pos, frames)
            if low_cpu:
                out += self._process_role_light(block, voice, controls)
            else:
                out += self._process_role(block, voice, controls)

        self._voices = {k: v for k, v in self._voices.items() if k in active}
        if active:
            out /= max(1.0, np.sqrt(len(active)))
        return soft_clip(out, threshold=0.86).astype(np.float32)

    def _voice_for(self, vid):
        voice = self._voices.get(vid)
        if voice is not None:
            return voice
        seed = None if self._seed is None else self._seed + vid * 71
        rng = np.random.default_rng(seed)
        voice = {
            "rng": rng,
            "phase": rng.uniform(0.0, 2.0 * np.pi),
            "lp": 0.0,
            "delay_buffers": {},
            "delay_positions": {},
        }
        self._voices[vid] = voice
        return voice

    def _read_unison(self, source, start, frames):
        self.debug_read_ratios.append(1.0)
        idx = (int(start) + np.arange(frames)) % len(source)
        return source[idx.astype(np.int64)]

    def _process_role(self, x, voice, controls):
        role = controls["role"]
        phase = voice["phase"] + 2.0 * np.pi * controls["motion_hz"] * len(x) / self.samplerate
        voice["phase"] = phase % (2.0 * np.pi)
        lfo = 0.5 + 0.5 * np.sin(
            phase + 2.0 * np.pi * controls["motion_hz"] * np.arange(len(x)) / self.samplerate
        )
        swell = 0.68 + controls["depth"] * 0.22 * lfo

        if role == "stretch":
            body = self._one_pole(x, voice, coeff=0.006 + 0.018 * controls["tone"])
            smear = self._delay(voice, "stretch_smear", body, 0.38 + 0.08 * controls["column"], 0.34, 0.34)
            return (0.42 * body + smear) * swell * controls["level"]
        if role == "delay":
            tone = self._one_pole(x, voice, coeff=0.02 + 0.04 * controls["tone"])
            a = self._delay(voice, "delay_a", tone, 0.16 + 0.05 * controls["column"], 0.24, 0.26)
            b = self._delay(voice, "delay_b", tone, 0.31 + 0.08 * controls["column"], 0.28, 0.20)
            return (0.22 * tone + a + b) * (0.72 + 0.22 * controls["diffusion"])
        if role == "reverb":
            washed = self._one_pole(x, voice, coeff=0.008 + 0.018 * controls["tone"])
            early = self._delay(voice, "reverb_early", washed, 0.09 + 0.02 * controls["column"], 0.18, 0.18)
            late = self._delay(voice, "reverb_late", washed + early, 0.72 + 0.11 * controls["column"], 0.42, 0.36)
            return (0.16 * washed + early + late) * controls["level"]
        if role == "stereo":
            body = self._one_pole(x, voice, coeff=0.018 + 0.035 * controls["tone"])
            drift = (0.58 + 0.36 * lfo) * body
            width = self._delay(voice, "stereo_width", body, 0.018 + 0.009 * controls["column"], 0.08, 0.22)
            return (drift + width) * (0.74 + 0.20 * controls["diffusion"])

        body = self._one_pole(x, voice, coeff=0.026 + 0.07 * controls["tone"])
        shaped = soft_clip(body * (1.1 + 0.22 * controls["column"]), threshold=0.72)
        tail = self._delay(voice, "shape_tail", shaped, 0.24 + 0.04 * controls["column"], 0.16, 0.14)
        return (0.72 * shaped + tail) * (0.72 + 0.18 * lfo) * controls["level"]

    def _process_role_light(self, x, voice, controls):
        role = controls["role"]
        phase = voice["phase"] + 2.0 * np.pi * controls["motion_hz"] * len(x) / self.samplerate
        voice["phase"] = phase % (2.0 * np.pi)
        lfo = 0.5 + 0.5 * np.sin(
            phase + 2.0 * np.pi * controls["motion_hz"] * np.arange(len(x)) / self.samplerate
        )
        swell = 0.66 + controls["depth"] * 0.18 * lfo
        col = controls["column"]

        if role == "stretch":
            body = self._smooth_fast(voice, "stretch_body", x, taps=64 + 16 * col)
            smear = self._delay_fast(voice, "stretch_smear", body, 0.32 + 0.05 * col, 0.24)
            return (0.50 * body + smear) * swell * controls["level"]
        if role == "delay":
            tone = self._smooth_fast(voice, "delay_tone", x, taps=14 + 4 * col)
            a = self._delay_fast(voice, "delay_a", tone, 0.13 + 0.04 * col, 0.20)
            b = self._delay_fast(voice, "delay_b", tone, 0.29 + 0.06 * col, 0.17)
            return (0.30 * tone + a + b) * (0.68 + 0.20 * controls["diffusion"])
        if role == "reverb":
            washed = self._smooth_fast(voice, "reverb_wash", x, taps=96 + 24 * col)
            early = self._delay_fast(voice, "reverb_early", washed, 0.08 + 0.018 * col, 0.14)
            late = self._delay_fast(voice, "reverb_late", washed, 0.46 + 0.08 * col, 0.28)
            return (0.18 * washed + early + late) * controls["level"]
        if role == "stereo":
            body = self._smooth_fast(voice, "stereo_body", x, taps=10 + 3 * col)
            drift = (0.56 + 0.30 * lfo) * body
            width = self._delay_fast(voice, "stereo_width", body, 0.012 + 0.006 * col, 0.18)
            return (drift + width) * (0.70 + 0.16 * controls["diffusion"])

        body = self._smooth_fast(voice, "shape_body", x, taps=8 + 2 * col)
        shaped = soft_clip(body * (1.05 + 0.16 * col), threshold=0.76)
        tail = self._delay_fast(voice, "shape_tail", shaped, 0.18 + 0.035 * col, 0.12)
        return (0.76 * shaped + tail) * (0.70 + 0.16 * lfo) * controls["level"]

    def _smooth_fast(self, voice, key, x, taps):
        taps = max(2, int(taps))
        buffers = voice["delay_buffers"]
        hist_key = f"{key}_hist"
        history = buffers.get(hist_key)
        if history is None or len(history) != taps - 1:
            history = np.zeros(taps - 1, dtype=np.float64)
        combined = np.concatenate([history, x])
        kernel = np.ones(taps, dtype=np.float64) / float(taps)
        y = np.convolve(combined, kernel, mode="valid")
        buffers[hist_key] = combined[-(taps - 1) :].copy()
        return y

    def _delay_fast(self, voice, key, x, seconds, wet):
        delay_len = max(1, int(seconds * self.samplerate))
        buffers = voice["delay_buffers"]
        buf = buffers.get(key)
        if buf is None or len(buf) != delay_len:
            buf = np.zeros(delay_len, dtype=np.float64)

        combined = np.concatenate([buf, x])
        out = combined[: len(x)].copy()
        buffers[key] = combined[len(x) : len(x) + delay_len].copy()
        return float(wet) * out

    def _one_pole(self, x, voice, coeff):
        coeff = float(clamp(coeff, 0.001, 1.0))
        y = np.empty_like(x, dtype=np.float64)
        state = float(voice["lp"])
        for i, sample in enumerate(x):
            state += coeff * (sample - state)
            y[i] = state
        voice["lp"] = state
        return y

    def _delay(self, voice, key, x, seconds, feedback, wet):
        delay_len = max(1, int(seconds * self.samplerate))
        buffers = voice["delay_buffers"]
        positions = voice["delay_positions"]
        buf = buffers.get(key)
        if buf is None or len(buf) != delay_len:
            buf = np.zeros(delay_len, dtype=np.float64)
            buffers[key] = buf
            positions[key] = 0

        pos = int(positions[key])
        out = np.empty_like(x, dtype=np.float64)
        for i, sample in enumerate(x):
            delayed = buf[pos]
            out[i] = delayed
            buf[pos] = sample + delayed * feedback
            pos = (pos + 1) % delay_len
        positions[key] = pos
        return wet * out
