"""Synth-mode sound source: seed wavetables, a consonant drone pitch-set,
and per-voice rendering into slightly-different-length looping buffers.

Loop mode feeds one shared audio loop into every effect; synth mode gives
each connected jack its own rendered tone. This module owns *what a voice
sounds like*; web_engine owns how voices are summed and effected.
"""

import numpy as np

WAVETABLE_LEN = 2048
DEFAULT_SEED_COUNT = 6


class SeedBank:
    """A small bank of single-cycle wavetables, synthesized once.

    Each seed is spectrally rich: a harmonic series with a seed-specific
    tilt and randomized partial phases. Higher-index seeds keep more upper
    harmonics. Deterministic given `seed`.
    """

    def __init__(self, count=DEFAULT_SEED_COUNT, length=WAVETABLE_LEN, seed=None):
        self.length = int(length)
        rng = np.random.default_rng(seed)
        self.tables = [self._make_table(rng, i, int(count)) for i in range(int(count))]

    def _make_table(self, rng, index, count):
        n = self.length
        phase = 2.0 * np.pi * np.arange(n) / n
        spread = index / max(1, count - 1)
        n_harmonics = 3 + int(round(spread * 9))
        tilt = 1.65 - 0.35 * spread
        table = np.zeros(n, dtype=np.float64)
        for h in range(1, n_harmonics + 1):
            amp = 1.0 / (h ** tilt)
            table += amp * np.sin(h * phase + rng.uniform(0.0, 2.0 * np.pi))
        peak = float(np.max(np.abs(table)))
        if peak > 1e-9:
            table /= peak
        return table

    def table(self, index):
        return self.tables[int(index) % len(self.tables)]

    def __len__(self):
        return len(self.tables)


# Drone pitch palette: restrained mid-register ratios around an A=432 reference.
# The first voices include close neighbors for beating, some harmonic anchors,
# and some non-chord neighboring tones. Assigned by slot/join order, not by color.
DRONE_ROOT_HZ = 216.0
DRONE_RATIOS = (
    1.0,
    1.012,
    1.5,
    1.3333333333333333,
    2.0,
    1.02,
    2.25,
    1.875,
)
DRONE_REGISTER_CYCLES = (1.0, 1.5, 0.75, 1.25)
HARMONY_RATIOS = {
    "open": DRONE_RATIOS,
    "lydian_add9": (
        1.0,
        9.0 / 8.0,
        5.0 / 4.0,
        45.0 / 32.0,
        3.0 / 2.0,
        5.0 / 3.0,
        2.0,
        81.0 / 64.0,
    ),
    "minor9": (
        1.0,
        9.0 / 8.0,
        6.0 / 5.0,
        4.0 / 3.0,
        3.0 / 2.0,
        9.0 / 5.0,
        2.0,
        7.0 / 4.0,
    ),
    "sus_cluster": (
        1.0,
        16.0 / 15.0,
        9.0 / 8.0,
        4.0 / 3.0,
        3.0 / 2.0,
        16.0 / 9.0,
        2.0,
        10.0 / 9.0,
    ),
}


def drone_pitch_hz(order_index, harmony_mode="open"):
    """Return the restrained drone pitch for a voice order index."""
    order_index = int(order_index)
    ratios = HARMONY_RATIOS["open"]
    ratio = ratios[order_index % len(ratios)]
    cycle = (order_index // len(ratios)) % len(DRONE_REGISTER_CYCLES)
    return DRONE_ROOT_HZ * ratio * DRONE_REGISTER_CYCLES[cycle]


def voice_timbre_from_color(hue, sat, val, seed_count):
    """Map finger-scan color to synth voice timbre in one small pure function."""
    from modulation import hue_to_unit, sat_to_unit, val_to_unit

    seed_count = int(seed_count)
    seed_index = int(min(seed_count - 1, int(hue_to_unit(hue) * seed_count)))
    return {
        "seed_index": max(0, seed_index),
        "spread": sat_to_unit(sat),
        "brightness": val_to_unit(val),
    }


def voice_character_for_slot(slot_index):
    """Return one stable generative voice recipe for a 5x5 patch slot."""
    slot_index = int(slot_index) % 25
    row = slot_index // 5
    col = slot_index % 5
    role = (
        "low_bed",
        "warm_mid",
        "air",
        "shimmer",
        "soft_pulse",
        "bell_wash",
    )[(row + 2 * col) % 6]
    role_defaults = {
        "low_bed": (0.18, 0.025, 0.16, 0.015, 0.16, 0.025),
        "warm_mid": (0.34, 0.035, 0.30, 0.025, 0.20, 0.035),
        "air": (0.42, 0.070, 0.58, 0.040, 0.24, 0.020),
        "shimmer": (0.52, 0.030, 0.48, 0.105, 0.18, 0.070),
        "soft_pulse": (0.30, 0.040, 0.34, 0.035, 0.44, 0.030),
        "bell_wash": (0.58, 0.020, 0.42, 0.125, 0.20, 0.085),
    }
    wave_mix, noise, filter_focus, shimmer, pulse, halo = role_defaults[role]
    return {
        "slot_index": slot_index,
        "role": role,
        "wave_mix": round(wave_mix + 0.01 * ((slot_index * 3) % 5), 4),
        "noise": round(noise + 0.004 * ((slot_index + col) % 4), 4),
        "filter": round(filter_focus + 0.018 * row + 0.01 * col, 4),
        "shimmer": round(shimmer + 0.004 * ((row + col) % 3), 4),
        "pulse": round(pulse + 0.015 * ((2 * row + col) % 4), 4),
        "halo": round(halo + 0.003 * ((3 * row + col) % 2), 4),
    }


def voice_params_from_scan(hue, sat, val, bpm, tone_mode="scan", harmony_mode="open"):
    """Map scan values directly to audible synth parameters."""
    from modulation import hue_to_unit, sat_to_unit, val_to_unit

    hue_u = hue_to_unit(hue)
    sat_u = sat_to_unit(sat)
    val_u = val_to_unit(val)
    bpm_u = float(np.clip((float(bpm) - 45.0) / 135.0, 0.0, 1.0))

    return {
        "harmony_mode": harmony_mode if harmony_mode in HARMONY_RATIOS else "open",
        "seed_index": max(0, min(DEFAULT_SEED_COUNT - 1, int(hue_u * DEFAULT_SEED_COUNT))),
        "brightness": val_u,
        "motion": sat_u,
        "spectral_focus": hue_u,
        "loop_seconds": 3.8 - 2.4 * bpm_u,
        "event_duty": 0.92 - 0.46 * bpm_u,
        "breath_seconds": 6.4 - 3.6 * bpm_u,
        "attack_seconds": 0.18 - 0.11 * val_u,
        "release_seconds": 0.32 + 0.35 * (1.0 - bpm_u),
    }


VOICE_LOOP_SECONDS = 2.5
LOOP_LENGTH_JITTER = 0.06


def _loop_crossfade(buf, fade):
    """Crossfade the loop seam so the wrap from buf[-1] to buf[0] is click-free."""
    fade = int(fade)
    if fade <= 0 or len(buf) < 2 * fade:
        return buf
    ramp = np.linspace(0.0, 1.0, fade)
    head = buf[:fade].copy()
    tail = buf[-fade:].copy()
    buf = buf.copy()
    buf[:fade] = head * ramp + tail * (1.0 - ramp)
    return buf[: len(buf) - fade]


class SynthVoiceBank:
    """Owns one rendered voice per connected layer id."""

    def __init__(
        self,
        samplerate,
        seed=None,
        seed_bank=None,
        tone_mode="scan",
        harmony_mode="open",
    ):
        self.samplerate = samplerate
        self._seed = seed
        self.seeds = seed_bank if seed_bank is not None else SeedBank(seed=seed)
        self.tone_mode = tone_mode
        self.harmony_mode = harmony_mode
        self._voices = {}
        self._samples = []
        self._sample_version = 0

    def set_options(self, tone_mode=None, harmony_mode=None):
        if tone_mode is not None and tone_mode != self.tone_mode:
            self.tone_mode = tone_mode
        if harmony_mode is not None and harmony_mode != self.harmony_mode:
            self.harmony_mode = harmony_mode

    def load_sample(self, name, samples):
        """Store one decoded local C sample for synth-mode source playback."""
        array = np.asarray(samples, dtype=np.float64).reshape(-1)
        if len(array) == 0:
            return
        array = array - float(np.mean(array))
        peak = float(np.max(np.abs(array)))
        if peak > 1e-9:
            array = 0.72 * (array / peak)
        fade = min(2048, max(0, len(array) // 12))
        if fade > 8:
            array = _loop_crossfade(array, fade)
        self._samples.append({"name": str(name), "buffer": array.astype(np.float64)})
        self._sample_version += 1
        self._voices = {}

    def sample_count(self):
        return len(self._samples)

    def _order_index(self, layer):
        if "output_slot" in layer:
            return int(layer["output_slot"])
        return int(layer.get("source_id", layer["id"])) - 1

    def _voice_key(self, layer):
        return (
            layer["hue"],
            layer["sat"],
            layer["val"],
            layer["bpm"],
            self._order_index(layer),
            self._sample_version,
        )

    def _make_voice(self, layer):
        if self._samples:
            return self._make_sample_voice(layer)

        vid = int(layer["id"])
        rng = np.random.default_rng(
            None if self._seed is None else self._seed + vid * 101
        )
        order = self._order_index(layer)
        params = voice_params_from_scan(
            layer["hue"],
            layer["sat"],
            layer["val"],
            layer["bpm"],
            self.tone_mode,
            self.harmony_mode,
        )
        pitch_hz = drone_pitch_hz(order, params["harmony_mode"])
        jitter = 1.0 + rng.uniform(-LOOP_LENGTH_JITTER, LOOP_LENGTH_JITTER)
        loop_len = max(
            self.seeds.length * 3, int(params["loop_seconds"] * self.samplerate * jitter)
        )
        params = {
            **params,
            **voice_character_for_slot(order),
            "source": "generated",
        }
        buffer = self._render(
            self.seeds.table(params["seed_index"]),
            pitch_hz,
            loop_len,
            params,
            rng,
        )
        effect_buffer = buffer
        return {
            "buffer": buffer,
            "buffer_for_effects": effect_buffer,
            "pos": 0.0,
            "pitch_hz": pitch_hz,
            "timbre": params,
            "key": self._voice_key(layer),
        }

    def _make_sample_voice(self, layer):
        order = self._order_index(layer)
        params = voice_params_from_scan(
            layer["hue"],
            layer["sat"],
            layer["val"],
            layer["bpm"],
            self.tone_mode,
            self.harmony_mode,
        )
        sample = self._samples[order % len(self._samples)]
        env_period = max(0.35, params["loop_seconds"])
        env_period_frames = max(1, int(round(env_period * self.samplerate)))
        env_buffer = self._build_sample_envelope(env_period_frames, env_period, params)
        return {
            "buffer": sample["buffer"],
            "buffer_for_effects": sample["buffer"],
            "pos": 0.0,
            "env_pos": 0.0,
            "env_period": env_period,
            "env_buffer": env_buffer,
            "env_duty": params["event_duty"],
            "env_attack": params["attack_seconds"],
            "env_release": params["release_seconds"],
            # Loaded files are assumed to be in C for this MVP. We do not
            # repitch them; this nominal value is kept for diagnostics/tests.
            "pitch_hz": DRONE_ROOT_HZ,
            "timbre": {
                **params,
                **voice_character_for_slot(order),
                "source": "sample",
                "sample_name": sample["name"],
            },
            "key": self._voice_key(layer),
        }

    def _render(self, table, pitch_hz, loop_len, timbre, rng):
        inc = pitch_hz * self.seeds.length / self.samplerate
        idx = (np.arange(loop_len) * inc) % self.seeds.length
        i0 = np.floor(idx).astype(np.int64)
        i1 = (i0 + 1) % self.seeds.length
        frac = idx - i0
        buf = table[i0] * (1.0 - frac) + table[i1] * frac
        seconds = np.arange(loop_len, dtype=np.float64) / self.samplerate
        harmonic = np.sin(
            2.0
            * np.pi
            * pitch_hz
            * (1.0 + 0.5 * timbre["wave_mix"])
            * seconds
            + rng.uniform(0.0, 2.0 * np.pi)
        )
        halo = np.sin(
            2.0
            * np.pi
            * pitch_hz
            * 2.0
            * seconds
            + rng.uniform(0.0, 2.0 * np.pi)
        )
        noise = rng.normal(0.0, 1.0, loop_len)
        noise = self._soften(noise, 0.08 + 0.3 * timbre["filter"])
        buf = (
            (0.72 - 0.32 * timbre["wave_mix"]) * buf
            + (0.16 + 0.24 * timbre["wave_mix"]) * harmonic
            + timbre["halo"] * halo
            + timbre["noise"] * noise
        )
        buf = self._shape_character(buf.astype(np.float64), timbre, pitch_hz)
        breath_seconds = timbre["breath_seconds"] * rng.uniform(0.88, 1.16)
        phase = rng.uniform(0.0, 2.0 * np.pi)
        motion = 0.08 + 0.18 * timbre["motion"] + 0.06 * timbre["pulse"]
        breath = (1.0 - motion) + motion * (
            0.5 + 0.5 * np.sin(2.0 * np.pi * seconds / breath_seconds + phase)
        )
        envelope = breath * self._gate_envelope(loop_len, timbre)
        buf *= envelope
        fade_len = min(loop_len // 4, 8192)
        if fade_len > 1:
            fade = np.ones(loop_len, dtype=np.float64)
            fade[:fade_len] = np.linspace(0.0, 1.0, fade_len) ** 1.6
            buf *= fade
        peak = float(np.max(np.abs(buf)))
        if peak > 1e-9:
            buf = 0.72 * (buf / peak)
        return _loop_crossfade(buf, fade=min(512, loop_len // 8))

    def _gate_envelope(self, loop_len, timbre):
        seconds = np.arange(loop_len, dtype=np.float64) / self.samplerate
        period_pos = seconds / max(0.1, timbre["loop_seconds"])
        phase_pos = period_pos - np.floor(period_pos)
        duty = timbre["event_duty"]
        gate = np.ones(loop_len, dtype=np.float64)
        release = max(0.01, timbre["release_seconds"] / max(0.1, timbre["loop_seconds"]))
        gap_start = max(0.0, duty - release)
        gate = np.where(
            phase_pos < gap_start,
            1.0,
            np.clip((duty - phase_pos) / max(1e-6, release), 0.0, 1.0),
        )
        attack = max(0.005, timbre["attack_seconds"] / max(0.1, timbre["loop_seconds"]))
        gate *= np.clip(phase_pos / attack, 0.0, 1.0)
        return gate

    def _shape_character(self, x, timbre, pitch_hz):
        brightness = timbre["brightness"]
        focus = 0.5 * timbre["spectral_focus"] + 0.5 * timbre["filter"]
        body = self._soften(x, 0.18 + 0.62 * brightness * focus)
        if timbre["shimmer"] <= 0.04:
            return body
        t = np.arange(len(x), dtype=np.float64) / self.samplerate
        shimmer = np.sin(2.0 * np.pi * pitch_hz * 3.0 * t) * timbre["shimmer"]
        return body + self._soften(shimmer, brightness)

    def _soften(self, x, brightness):
        brightness = float(np.clip(brightness, 0.0, 1.0))
        kernel_len = int(round(28 - 18 * brightness))
        kernel_len = max(5, kernel_len | 1)
        kernel = np.hanning(kernel_len)
        kernel /= max(1e-12, float(np.sum(kernel)))
        return np.convolve(x, kernel, mode="same")

    def block(self, layers, frames):
        active = set()
        out = {}
        for layer in layers:
            vid = int(layer["id"])
            active.add(vid)
            voice = self._voices.get(vid)
            if voice is None or voice["key"] != self._voice_key(layer):
                voice = self._make_voice(layer)
                self._voices[vid] = voice
            out[vid] = self._read_block(voice, frames)
        self._voices = {k: v for k, v in self._voices.items() if k in active}
        return out

    def _read_block(self, voice, frames):
        buf = voice["buffer"]
        n = len(buf)
        idx = (voice["pos"] + np.arange(frames)) % n
        block = buf[idx.astype(np.int64)]
        voice["pos"] = float((voice["pos"] + frames) % n)
        if voice["timbre"].get("source") == "sample":
            block = block * self._sample_envelope(voice, frames)
        return block.astype(np.float64)

    def _build_sample_envelope(self, period_frames, period_seconds, params):
        phase = np.arange(period_frames, dtype=np.float64) / max(1, period_frames)
        duty = float(np.clip(params["event_duty"], 0.08, 1.0))
        attack = max(1.0 / period_frames, params["attack_seconds"] / period_seconds)
        release = max(1.0 / period_frames, params["release_seconds"] / period_seconds)
        sustain_end = max(0.0, duty - release)
        gate = np.where(
            phase < sustain_end,
            1.0,
            np.clip((duty - phase) / release, 0.0, 1.0),
        )
        gate *= np.clip(phase / attack, 0.0, 1.0)
        return gate.astype(np.float64)

    def _sample_envelope(self, voice, frames):
        env = voice["env_buffer"]
        idx = (int(voice["env_pos"]) + np.arange(frames)) % len(env)
        voice["env_pos"] = float((voice["env_pos"] + frames) % len(env))
        return env[idx.astype(np.int64)]

    def buffer_for(self, vid):
        voice = self._voices.get(int(vid))
        return None if voice is None else voice["buffer"]

    def read_pos(self, vid):
        voice = self._voices.get(int(vid))
        return 0.0 if voice is None else voice["pos"]

    def reset(self):
        self._voices = {}
