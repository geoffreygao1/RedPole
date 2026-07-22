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
        n_harmonics = 4 + int(round(spread * 20))
        tilt = 1.2 - 0.5 * spread
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


# Consonant drone pitch-set: just-intonation ratios over a low root, ordered
# so arriving voices fill the drone in with registral spread. Assigned by
# slot/join order, not by color.
DRONE_ROOT_HZ = 55.0
DRONE_RATIOS = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0)


def drone_pitch_hz(order_index):
    """Return the consonant drone pitch for a voice order index."""
    order_index = int(order_index)
    ratio = DRONE_RATIOS[order_index % len(DRONE_RATIOS)]
    octave = order_index // len(DRONE_RATIOS)
    return DRONE_ROOT_HZ * ratio * (2.0 ** octave)


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


VOICE_LOOP_SECONDS = 4.0
LOOP_LENGTH_JITTER = 0.06
MAX_DETUNE_CENTS = 8.0


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

    def __init__(self, samplerate, seed=None, seed_bank=None):
        self.samplerate = samplerate
        self._seed = seed
        self.seeds = seed_bank if seed_bank is not None else SeedBank(seed=seed)
        self._voices = {}

    def _order_index(self, layer):
        if "patch_row" in layer and "patch_col" in layer:
            return int(layer["patch_row"]) * 5 + int(layer["patch_col"])
        return int(layer["id"]) - 1

    def _voice_key(self, layer):
        return (layer["hue"], layer["sat"], layer["val"], self._order_index(layer))

    def _make_voice(self, layer):
        vid = int(layer["id"])
        rng = np.random.default_rng(
            None if self._seed is None else self._seed + vid * 101
        )
        order = self._order_index(layer)
        cents = rng.uniform(-MAX_DETUNE_CENTS, MAX_DETUNE_CENTS)
        pitch_hz = drone_pitch_hz(order) * (2.0 ** (cents / 1200.0))
        jitter = 1.0 + rng.uniform(-LOOP_LENGTH_JITTER, LOOP_LENGTH_JITTER)
        loop_len = max(
            self.seeds.length * 4, int(VOICE_LOOP_SECONDS * self.samplerate * jitter)
        )
        timbre = voice_timbre_from_color(
            layer["hue"], layer["sat"], layer["val"], len(self.seeds)
        )
        buffer = self._render(self.seeds.table(timbre["seed_index"]), pitch_hz, loop_len)
        return {
            "buffer": buffer,
            "pos": 0.0,
            "pitch_hz": pitch_hz,
            "timbre": timbre,
            "key": self._voice_key(layer),
        }

    def _render(self, table, pitch_hz, loop_len):
        inc = pitch_hz * self.seeds.length / self.samplerate
        idx = (np.arange(loop_len) * inc) % self.seeds.length
        i0 = np.floor(idx).astype(np.int64)
        i1 = (i0 + 1) % self.seeds.length
        frac = idx - i0
        buf = table[i0] * (1.0 - frac) + table[i1] * frac
        return _loop_crossfade(buf.astype(np.float64), fade=min(256, loop_len // 8))

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
        return block.astype(np.float64)

    def buffer_for(self, vid):
        voice = self._voices.get(int(vid))
        return None if voice is None else voice["buffer"]

    def read_pos(self, vid):
        voice = self._voices.get(int(vid))
        return 0.0 if voice is None else voice["pos"]

    def reset(self):
        self._voices = {}
