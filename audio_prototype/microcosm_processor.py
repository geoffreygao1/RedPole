import numpy as np

from modulation import clamp, hue_to_bipolar, hue_to_unit, sat_to_unit, val_to_unit

FAMILIES = ("microloop", "granules", "glitch", "multidelay")
FAMILY_VARIANTS = {
    "microloop": ("mosaic", "seq", "jump"),
    "granules": ("haze", "tunnel", "strum"),
    "glitch": ("blocks", "interrupt", "arp"),
    "multidelay": ("pattern", "warp"),
}
EVENT_DENSITY_TARGET = 3.0
MAX_EVENTS_PER_BLOCK = 3
EVENT_JITTER = 0.55
OUTPUT_LEVEL = 0.62


def event_cap_for_frames(frames):
    if frames <= 256:
        return 1
    if frames <= 512:
        return 2
    return MAX_EVENTS_PER_BLOCK


def microcosm_variant(layer):
    variants = FAMILY_VARIANTS[layer["engine"]]
    if "patch_col" in layer:
        col = clamp(layer["patch_col"], 0, 4)
        idx = int(round(col * (len(variants) - 1) / 4.0))
        return variants[idx]
    hue = min(0.999999, hue_to_unit(layer["hue"]))
    return variants[min(len(variants) - 1, int(hue * len(variants)))]


def microloop_pitch_ratios(layer):
    col = int(clamp(layer.get("patch_col", 2), 0, 4))
    return (
        (0.5, 1.0),
        (0.5, 1.0, 1.0),
        (0.5, 1.0, 2.0),
        (1.0, 1.0, 2.0),
        (0.5, 1.0, 2.0, 4.0),
    )[col]


def microloop_pitch_weights(layer):
    col = int(clamp(layer.get("patch_col", 2), 0, 4))
    return (
        (0.42, 0.58),
        (0.34, 0.46, 0.20),
        (0.42, 0.32, 0.26),
        (0.28, 0.42, 0.30),
        (0.40, 0.20, 0.25, 0.15),
    )[col]


def pitch_weights_for_ratios(ratios, low_bias=1.0):
    weights = []
    for ratio in ratios:
        if ratio < 1.0:
            weights.append(0.48 * low_bias)
        elif ratio == 1.0:
            weights.append(0.34)
        else:
            weights.append(0.18 / ratio)
    total = sum(weights)
    return tuple(w / total for w in weights)


def microcosm_controls(layer):
    engine = layer["engine"]
    bpm = clamp(layer["bpm"], 20.0, 300.0)
    sat = sat_to_unit(layer["sat"])
    val = val_to_unit(layer["val"])
    bpm_norm = (bpm - 20.0) / 280.0
    base_interval = 0.18 + 0.62 * (1.0 - bpm_norm)
    base_event = 0.035 + 0.18 * sat
    timing = {
        "microloop": (4.3, 3.5),
        "granules": (1.0, 1.0),
        "glitch": (1.15, 0.58),
        "multidelay": (2.8, 1.25),
    }[engine]
    pitch_ratios = (
        (0.5, 1.0, 2.0, 4.0)
        if engine == "glitch"
        else microloop_pitch_ratios(layer)
        if engine == "microloop"
        else (0.5, 1.0, 2.0)
    )
    pitch_weights = (
        microloop_pitch_weights(layer)
        if engine == "microloop"
        else pitch_weights_for_ratios(
            pitch_ratios,
            low_bias=1.25 if engine in ("granules", "glitch", "multidelay") else 1.0,
        )
    )
    return {
        "interval_seconds": base_interval * timing[0],
        "event_seconds": base_event * timing[1],
        "grain_seconds": (
            0.16 + 0.18 * sat
            if engine == "granules"
            else 0.035 + 0.09 * sat
        ),
        "delay_base_seconds": base_interval * (1.55 if engine == "multidelay" else 0.45),
        "source_spread_seconds": 0.08 + 0.65 * (1.0 - bpm_norm),
        "level": 0.25 + 0.75 * val,
        "tone": hue_to_bipolar(layer["hue"]),
        "pitch_ratios": pitch_ratios,
        "pitch_weights": pitch_weights,
        "octave_down_gain": 1.28 if engine == "microloop" else 1.18,
        "variant": microcosm_variant(layer),
    }


class MicrocosmProcessor:
    """Sparse source-derived event processor inspired by Microcosm families."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._seed = seed
        self._voices = {}

    def process(self, loop_array, frames, layers, source_pos=0):
        if not layers or len(loop_array) == 0:
            self._voices = {}
            return np.zeros(frames, dtype=np.float32)

        loop = np.asarray(loop_array)
        out = np.zeros(frames, dtype=np.float64)
        active = set()
        density_probability = min(1.0, EVENT_DENSITY_TARGET / max(1, len(layers)))
        max_events = event_cap_for_frames(frames)
        events_this_block = 0

        for layer in layers:
            family = layer["engine"]
            if family not in FAMILIES:
                continue
            vid = layer["id"]
            active.add(vid)
            voice = self._voices.get(vid)
            if voice is None:
                seed = None if self._seed is None else self._seed + vid * 17
                rng = np.random.default_rng(seed)
                voice = {
                    "rng": rng,
                    "buffer": np.zeros(frames, dtype=np.float64),
                    "until_event": int(rng.uniform(0.0, 0.2) * self.samplerate),
                }
                self._voices[vid] = voice

            min_len = frames + int(1.2 * self.samplerate)
            if len(voice["buffer"]) < min_len:
                voice["buffer"] = np.concatenate(
                    [voice["buffer"], np.zeros(min_len - len(voice["buffer"]))]
                )

            controls_key = (
                family,
                layer["hue"],
                layer["sat"],
                layer["val"],
                layer["bpm"],
                layer.get("patch_col"),
            )
            if voice.get("controls_key") != controls_key:
                voice["controls"] = microcosm_controls(layer)
                voice["controls_key"] = controls_key
            controls = voice["controls"]
            t = voice["until_event"]
            while t < frames:
                if (
                    events_this_block < max_events
                    and voice["rng"].random() < density_probability
                ):
                    self._emit_event(
                        voice,
                        loop,
                        family,
                        t,
                        int(source_pos + t),
                        controls,
                    )
                    events_this_block += 1
                t += self._next_interval(voice, controls)
            voice["until_event"] = t - frames

            buffer = voice["buffer"]
            out += buffer[:frames]
            buffer[:-frames] = buffer[frames:]
            buffer[-frames:] = 0.0

        self._voices = {k: v for k, v in self._voices.items() if k in active}
        out *= OUTPUT_LEVEL / max(1.0, np.sqrt(len(layers)))
        return np.tanh(out).astype(np.float32)

    def _next_interval(self, voice, controls):
        scale = voice["rng"].uniform(1.0 - EVENT_JITTER, 1.0 + EVENT_JITTER)
        return max(1, int(controls["interval_seconds"] * scale * self.samplerate))

    def _emit_event(self, voice, loop, family, offset, source_pos, controls):
        if family == "microloop":
            self._emit_microloop(voice, loop, offset, source_pos, controls)
        elif family == "granules":
            self._emit_granules(voice, loop, offset, source_pos, controls)
        elif family == "glitch":
            self._emit_glitch(voice, loop, offset, source_pos, controls)
        elif family == "multidelay":
            self._emit_multidelay(voice, loop, offset, source_pos, controls)

    def _emit_microloop(self, voice, loop, offset, source_pos, controls):
        variant = controls["variant"]
        if variant == "mosaic":
            self._emit_mosaic(voice, loop, offset, source_pos, controls)
        elif variant == "seq":
            self._emit_seq(voice, loop, offset, source_pos, controls)
        elif variant == "jump":
            self._emit_jump(voice, loop, offset, source_pos, controls)

    def _emit_mosaic(self, voice, loop, offset, source_pos, controls):
        rng = voice["rng"]
        grain_len = max(512, int(controls["event_seconds"] * 0.75 * self.samplerate))
        repeats = int(rng.integers(2, 5))
        step = max(256, int(grain_len * rng.uniform(0.72, 1.35)))
        start = self._smeared_source(rng, source_pos, controls)
        ratios = controls["pitch_ratios"]
        weights = controls["pitch_weights"]
        for i in range(repeats):
            ratio = rng.choice(ratios, p=weights)
            segment = self._read_ratio(loop, start, grain_len, ratio)
            gain = controls["level"] * (0.85 ** i) * rng.uniform(0.65, 1.0)
            if ratio < 1.0:
                gain *= controls["octave_down_gain"]
            self._add(voice, offset + i * step, segment, gain, smear=0.35)

    def _emit_seq(self, voice, loop, offset, source_pos, controls):
        rng = voice["rng"]
        step_len = max(320, int(controls["event_seconds"] * 0.45 * self.samplerate))
        steps = int(rng.integers(3, 7))
        ratios = controls["pitch_ratios"]
        weights = controls["pitch_weights"]
        for i in range(steps):
            ratio = rng.choice(ratios, p=weights)
            jitter = int(rng.uniform(-0.08, 0.08) * self.samplerate)
            start = self._smeared_source(rng, source_pos + jitter, controls)
            segment = self._tilt_filter(
                self._read_ratio(loop, start, step_len, ratio),
                amount=(-0.45 + 0.15 * i),
            )
            self._add(
                voice,
                offset + i * int(step_len * 0.8),
                segment,
                controls["level"] * rng.uniform(0.45, 0.8)
                * (controls["octave_down_gain"] if ratio < 1.0 else 1.0),
                smear=0.25,
            )

    def _emit_jump(self, voice, loop, offset, source_pos, controls):
        rng = voice["rng"]
        loop_len = max(2048, int(controls["event_seconds"] * 0.55 * self.samplerate))
        repeats = int(rng.integers(2, 4))
        step = max(512, int(loop_len * rng.uniform(0.72, 1.18)))
        ratios = controls["pitch_ratios"]
        weights = np.asarray(controls["pitch_weights"], dtype=np.float64)
        weights = weights / np.sum(weights)
        non_unison = [r for r in ratios if r != 1.0]
        start = self._smeared_source(rng, source_pos, controls)
        for i in range(repeats):
            if i == 0 and non_unison:
                non_unison_weights = np.asarray(
                    [
                        controls["pitch_weights"][ratios.index(ratio)]
                        for ratio in non_unison
                    ],
                    dtype=np.float64,
                )
                non_unison_weights = non_unison_weights / np.sum(non_unison_weights)
                ratio = rng.choice(non_unison, p=non_unison_weights)
            else:
                ratio = rng.choice(ratios, p=weights)
            segment = self._read_ratio(loop, start + i * loop_len, loop_len, ratio)
            if rng.random() < 0.25:
                segment = segment[::-1]
            gain = controls["level"] * (0.78 ** i)
            if ratio == 0.5:
                gain *= controls["octave_down_gain"]
            self._add(
                voice,
                offset + i * step,
                segment,
                gain,
                smear=0.38,
            )

    def _emit_granules(self, voice, loop, offset, source_pos, controls):
        variant = controls["variant"]
        if variant == "haze":
            self._emit_haze(voice, loop, offset, source_pos, controls)
        elif variant == "tunnel":
            self._emit_tunnel(voice, loop, offset, source_pos, controls)
        elif variant == "strum":
            self._emit_strum(voice, loop, offset, source_pos, controls)

    def _emit_haze(self, voice, loop, offset, source_pos, controls):
        rng = voice["rng"]
        grain_base = controls["grain_seconds"] * self.samplerate
        for _ in range(int(rng.integers(3, 6))):
            grain_len = max(2048, int(rng.uniform(0.75, 1.45) * grain_base))
            start = self._smeared_source(rng, source_pos, controls)
            ratio = rng.choice(controls["pitch_ratios"], p=controls["pitch_weights"])
            segment = self._read_ratio(loop, start, grain_len, ratio)
            gain = controls["level"] * rng.uniform(0.22, 0.5)
            if ratio < 1.0:
                gain *= controls["octave_down_gain"]
            self._add(
                voice,
                offset + int(rng.uniform(0.0, 0.32) * self.samplerate),
                self._diffuse(segment, rng),
                gain,
                smear=0.85,
            )

    def _emit_tunnel(self, voice, loop, offset, source_pos, controls):
        rng = voice["rng"]
        drone_len = max(3072, int(rng.uniform(1.15, 2.1) * controls["grain_seconds"] * self.samplerate))
        start = self._smeared_source(rng, source_pos, controls)
        ratio = rng.choice((0.5, 1.0), p=(0.62, 0.38))
        segment = self._read_ratio(loop, start, drone_len, ratio)
        segment = self._tilt_filter(segment, amount=controls["tone"])
        for i in range(int(rng.integers(2, 5))):
            delay = int(i * drone_len * rng.uniform(0.35, 0.75))
            gain = controls["level"] * (0.44 ** i)
            if ratio < 1.0:
                gain *= controls["octave_down_gain"]
            self._add(
                voice,
                offset + delay,
                segment,
                gain,
                smear=0.7,
            )

    def _emit_strum(self, voice, loop, offset, source_pos, controls):
        rng = voice["rng"]
        grain_len = max(1536, int(rng.uniform(0.55, 1.05) * controls["grain_seconds"] * self.samplerate))
        chain = int(rng.integers(3, 6))
        direction = -1 if controls["tone"] < 0 else 1
        for i in range(chain):
            start = source_pos - direction * int((i + 1) * controls["source_spread_seconds"] * 0.18 * self.samplerate)
            start += int(rng.uniform(-0.03, 0.03) * self.samplerate)
            ratio = (
                0.5
                if i == chain - 1 and controls["tone"] < 0.65
                else 2.0
                if i == chain - 1 and controls["tone"] > 0.65
                else 1.0
            )
            segment = self._read_ratio(loop, start, grain_len, ratio)
            gain = controls["level"] * (0.78 ** i)
            if ratio < 1.0:
                gain *= controls["octave_down_gain"]
            self._add(
                voice,
                offset + int(i * grain_len * rng.uniform(0.45, 0.85)),
                segment,
                gain,
                smear=0.45,
            )

    def _emit_glitch(self, voice, loop, offset, source_pos, controls):
        variant = controls["variant"]
        if variant == "blocks":
            self._emit_blocks(voice, loop, offset, source_pos, controls)
        elif variant == "interrupt":
            self._emit_interrupt(voice, loop, offset, source_pos, controls)
        elif variant == "arp":
            self._emit_arp(voice, loop, offset, source_pos, controls)

    def _emit_blocks(self, voice, loop, offset, source_pos, controls):
        rng = voice["rng"]
        block_len = max(64, int(rng.uniform(0.025, 0.09) * self.samplerate))
        start = self._smeared_source(rng, source_pos, controls)
        ratio = rng.choice(controls["pitch_ratios"], p=controls["pitch_weights"])
        segment = self._read_ratio(loop, start, block_len, ratio)
        if rng.random() < 0.35:
            segment = segment[::-1]
        if controls["tone"] > 0.25:
            segment = self._bitcrush(segment, bits=6)
        repeats = int(rng.integers(1, 4))
        for i in range(repeats):
            gain = controls["level"] * 0.8
            if ratio < 1.0:
                gain *= controls["octave_down_gain"]
            self._add(
                voice,
                offset + i * block_len,
                segment,
                gain,
                smear=0.08,
            )

    def _emit_interrupt(self, voice, loop, offset, source_pos, controls):
        rng = voice["rng"]
        burst_len = max(96, int(rng.uniform(0.045, 0.12) * self.samplerate))
        start = self._smeared_source(rng, source_pos, controls)
        for i in range(int(rng.integers(2, 5))):
            ratio = rng.choice(controls["pitch_ratios"], p=controls["pitch_weights"])
            segment = self._read_ratio(loop, start + i * burst_len, burst_len, ratio)
            if i % 2:
                segment = self._tilt_filter(segment, amount=controls["tone"])
            gain = controls["level"] * rng.uniform(0.35, 0.75)
            if ratio < 1.0:
                gain *= controls["octave_down_gain"]
            self._add(
                voice,
                offset + int(i * burst_len * rng.uniform(0.55, 1.2)),
                segment,
                gain,
                smear=0.42,
            )

    def _emit_arp(self, voice, loop, offset, source_pos, controls):
        rng = voice["rng"]
        step_len = max(64, int(rng.uniform(0.025, 0.075) * self.samplerate))
        steps = int(rng.integers(5, 9))
        ratios = controls["pitch_ratios"]
        weights = controls["pitch_weights"]
        for i in range(steps):
            ratio = rng.choice(ratios, p=weights)
            start = source_pos - int((steps - i) * step_len * rng.uniform(0.6, 1.4))
            segment = self._read_ratio(loop, start, step_len, ratio)
            if controls["tone"] > 0.5:
                segment = self._bitcrush(segment, bits=7)
            gain = controls["level"] * (0.86 ** i)
            if ratio < 1.0:
                gain *= controls["octave_down_gain"]
            self._add(
                voice,
                offset + i * int(step_len * 0.78),
                segment,
                gain,
                smear=0.28,
            )

    def _emit_multidelay(self, voice, loop, offset, source_pos, controls):
        if controls["variant"] == "pattern":
            self._emit_pattern_delay(voice, loop, offset, source_pos, controls)
        else:
            self._emit_warp_delay(voice, loop, offset, source_pos, controls)

    def _emit_pattern_delay(self, voice, loop, offset, source_pos, controls):
        rng = voice["rng"]
        tap_len = max(1024, int(rng.uniform(0.12, 0.30) * self.samplerate))
        start = self._smeared_source(rng, source_pos, controls)
        segment = self._read_ratio(loop, start, tap_len, 1.0)
        patterns = (
            (0.0, 0.5, 1.0),
            (0.0, 0.25, 0.75, 1.0),
            (0.0, 0.33, 0.67, 1.33),
            (0.0, 0.375, 0.75, 1.5),
        )
        pattern = patterns[int(rng.integers(0, len(patterns)))]
        base = controls["delay_base_seconds"] * self.samplerate
        for i, step in enumerate(pattern):
            gain = controls["level"] * (0.62 ** i)
            self._add(voice, offset + int(step * base), segment, gain, smear=0.75)

    def _emit_warp_delay(self, voice, loop, offset, source_pos, controls):
        rng = voice["rng"]
        tap_len = max(1024, int(rng.uniform(0.13, 0.36) * self.samplerate))
        start = self._smeared_source(rng, source_pos, controls)
        base = controls["delay_base_seconds"] * 1.2 * self.samplerate
        for i, step in enumerate((0.0, 0.42, 0.9, 1.4)):
            ratio = 0.5 if i >= 2 else 1.0
            segment = self._read_ratio(loop, start + i * tap_len, tap_len, ratio)
            segment = self._tilt_filter(segment, amount=controls["tone"] * (i + 1) / 4.0)
            if i % 2:
                segment = segment[::-1]
            gain = controls["level"] * (0.55 ** i)
            if ratio < 1.0:
                gain *= controls["octave_down_gain"]
            self._add(
                voice,
                offset + int(step * base),
                segment,
                gain,
                smear=0.85,
            )

    def _smeared_source(self, rng, source_pos, controls):
        spread = int(controls["source_spread_seconds"] * self.samplerate)
        tone_offset = int(controls["tone"] * 0.08 * self.samplerate)
        if spread <= 0:
            return source_pos + tone_offset
        return source_pos + tone_offset + int(rng.integers(-spread, spread + 1))

    def _add(self, voice, offset, segment, gain, smear=0.0):
        if offset < 0:
            segment = segment[-offset:]
            offset = 0
        if len(segment) == 0:
            return
        window = np.hanning(len(segment))
        event = segment * window * gain
        end = offset + len(event)
        if end > len(voice["buffer"]):
            voice["buffer"] = np.concatenate(
                [voice["buffer"], np.zeros(end - len(voice["buffer"]))]
            )
        voice["buffer"][offset:end] += event
        if smear <= 0.0:
            return
        tail = self._event_tail(event, smear)
        tail_offset = offset + max(1, int(len(event) * 0.45))
        tail_end = tail_offset + len(tail)
        if tail_end > len(voice["buffer"]):
            voice["buffer"] = np.concatenate(
                [voice["buffer"], np.zeros(tail_end - len(voice["buffer"]))]
            )
        voice["buffer"][tail_offset:tail_end] += tail

    def _read_ratio(self, loop, start, length, ratio):
        return self._read(loop, start + np.arange(length) * ratio)

    def _read(self, loop, positions):
        loop_len = len(loop)
        positions = np.asarray(positions, dtype=np.float64) % loop_len
        idx0 = np.floor(positions).astype(np.int64)
        idx1 = (idx0 + 1) % loop_len
        frac = positions - idx0
        return loop[idx0] * (1.0 - frac) + loop[idx1] * frac

    def _diffuse(self, segment, rng):
        if len(segment) < 4:
            return segment
        taps = int(rng.integers(2, 5))
        out = segment.astype(np.float64).copy()
        for i in range(1, taps + 1):
            shift = max(1, int(i * len(segment) / (taps + 2)))
            out[shift:] += segment[:-shift] * (0.35 / i)
        return out / max(1.0, np.max(np.abs(out)) / max(1e-9, np.max(np.abs(segment))))

    def _tilt_filter(self, segment, amount):
        amount = clamp(amount, -1.0, 1.0)
        x = np.asarray(segment, dtype=np.float64)
        if len(x) == 0:
            return x
        kernel_len = max(4, min(96, int(12 + 84 * (1.0 - abs(amount)))))
        kernel = np.hanning(kernel_len)
        kernel /= max(1e-12, float(np.sum(kernel)))
        low = np.convolve(x, kernel, mode="same")
        high = x - low
        if amount < 0.0:
            return (1.0 + abs(amount) * 0.8) * low
        return low + (0.35 + 0.65 * amount) * high

    def _bitcrush(self, segment, bits=7):
        steps = float(2 ** max(2, int(bits)))
        return np.round(np.asarray(segment) * steps) / steps

    def _event_tail(self, event, smear):
        event = np.asarray(event, dtype=np.float64)
        if len(event) == 0:
            return event
        smear = clamp(smear, 0.0, 1.0)
        tail_len = max(1, int(len(event) * (1.0 + 0.9 * smear)))
        source = event[::-1]
        positions = np.linspace(0.0, len(source) - 1, tail_len)
        idx0 = np.floor(positions).astype(np.int64)
        idx1 = np.minimum(idx0 + 1, len(source) - 1)
        frac = positions - idx0
        tail = source[idx0] * (1.0 - frac) + source[idx1] * frac
        if len(tail) == 0:
            return tail
        envelope = np.linspace(1.0, 0.0, len(tail)) ** 1.4
        tail *= envelope * (0.18 + 0.32 * smear)
        delay = max(1, len(tail) // 5)
        tail[delay:] += tail[:-delay] * 0.28 * smear
        return tail
