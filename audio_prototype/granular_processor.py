import numpy as np

GRAIN_MIN_SECONDS = 0.06
GRAIN_MAX_SECONDS = 0.25
BURST_GRAINS = 4
BURST_JITTER_SECONDS = 0.08


class GranularProcessor:
    """Per-layer grain streams sampled from the loop.

    hue -> grain pitch shift (+/-12 st, red centered), bpm -> grain bursts
    at the heartbeat period, sat -> grain size, val -> stream level.
    Grains are rendered into a per-voice overlap-add buffer at trigger
    time, so per-block cost is just mixing.
    """

    STREAM_LEVEL = 0.5

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._seed = seed
        self._voices = {}

    def _new_voice(self, vid, frames):
        seed = None if self._seed is None else self._seed + vid
        return {
            "rng": np.random.default_rng(seed),
            "buffer": np.zeros(frames),
            "until_pulse": 0,
        }

    def process(self, loop_array, frames, layers):
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
                (GRAIN_MAX_SECONDS + BURST_JITTER_SECONDS) * self.samplerate * 2
            )
            if len(voice["buffer"]) < min_len:
                voice["buffer"] = np.concatenate(
                    [voice["buffer"], np.zeros(min_len - len(voice["buffer"]))]
                )

            hue = layer["hue"]
            semitones = 24.0 * (hue if hue <= 0.5 else hue - 1.0)
            ratio = 2.0 ** (semitones / 12.0)
            grain_len = int(
                (GRAIN_MIN_SECONDS
                 + layer["sat"] * (GRAIN_MAX_SECONDS - GRAIN_MIN_SECONDS))
                * self.samplerate
            )
            level = self.STREAM_LEVEL * layer["val"]
            pulse_period = int(self.samplerate * 60.0 / max(layer["bpm"], 1.0))

            t = voice["until_pulse"]
            while t < frames:
                self._emit_burst(voice, loop_array, t, grain_len, ratio, level)
                t += pulse_period
            voice["until_pulse"] = t - frames

            out += voice["buffer"][:frames]
            voice["buffer"] = np.concatenate(
                [voice["buffer"][frames:], np.zeros(frames)]
            )

        self._voices = {k: v for k, v in self._voices.items() if k in active}
        out /= max(1.0, np.sqrt(len(layers)))
        return out.astype(np.float32)

    def _emit_burst(self, voice, loop_array, offset, grain_len, ratio, level):
        rng = voice["rng"]
        loop_len = len(loop_array)
        for _ in range(BURST_GRAINS):
            jitter = int(rng.uniform(0, BURST_JITTER_SECONDS) * self.samplerate)
            start = int(rng.uniform(0, loop_len))
            src_len = max(2, int(grain_len * ratio))
            idx = (start + np.arange(src_len)) % loop_len
            src = loop_array[idx]
            # compress src_len samples into grain_len -> pitch shift by ratio
            grain = np.interp(
                np.linspace(0.0, src_len - 1.0, grain_len),
                np.arange(src_len),
                src,
            )
            grain *= np.hanning(grain_len) * level * rng.uniform(0.6, 1.0)
            pos = offset + jitter
            end = pos + grain_len
            if end > len(voice["buffer"]):
                voice["buffer"] = np.concatenate(
                    [voice["buffer"], np.zeros(end - len(voice["buffer"]))]
                )
            voice["buffer"][pos:end] += grain
