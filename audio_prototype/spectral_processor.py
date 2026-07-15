import numpy as np

N_PARTIALS = 24
FFT_SIZE = 4096
HOP_SIZE = 1024


def analyze_loop(loop_array, samplerate, n_partials=N_PARTIALS,
                 fft_size=FFT_SIZE, hop_size=HOP_SIZE):
    """Precompute the loop's 'spectral movie': per-frame strongest partials.

    Runs offline at load time (never in the audio callback). Returns freqs
    and amps arrays of shape [n_frames, n_partials] plus the analysis
    frame_rate in frames per second of original audio.
    """
    loop_array = np.asarray(loop_array, dtype=np.float64)
    if len(loop_array) < fft_size:
        loop_array = np.pad(loop_array, (0, fft_size - len(loop_array)))

    window = np.hanning(fft_size)
    starts = np.arange(0, len(loop_array) - fft_size + 1, hop_size)
    bin_freqs = np.fft.rfftfreq(fft_size, 1.0 / samplerate)

    freqs = np.zeros((len(starts), n_partials))
    amps = np.zeros((len(starts), n_partials))
    for i, s in enumerate(starts):
        mag = np.abs(np.fft.rfft(loop_array[s:s + fft_size] * window))
        # local-maxima peak picking, strongest first
        peaks = np.where((mag[1:-1] > mag[:-2]) & (mag[1:-1] > mag[2:]))[0] + 1
        if len(peaks) == 0:
            continue
        top = peaks[np.argsort(mag[peaks])[::-1][:n_partials]]
        freqs[i, :len(top)] = bin_freqs[top]
        amps[i, :len(top)] = mag[top]

    peak = amps.max()
    if peak > 0:
        amps /= peak
    return {"freqs": freqs, "amps": amps, "frame_rate": samplerate / hop_size}


class SpectralProcessor:
    """Per-layer oscillator-bank resynthesis of the precomputed analysis.

    Each active layer is an independent voice scanning the spectral movie:
    hue -> pitch shift (+/-7 st, red centered), bpm -> scan speed,
    sat -> blur (frame smoothing), val -> voice level.
    """

    VOICE_LEVEL = 0.3

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self.analysis = None
        self._voices = {}

    def set_analysis(self, analysis):
        self.analysis = analysis
        self._voices = {}

    def process(self, loop_array, frames, layers):
        out = np.zeros(frames)
        if self.analysis is None or not layers:
            self._voices = {}
            return out.astype(np.float32)

        freqs_movie = self.analysis["freqs"]
        amps_movie = self.analysis["amps"]
        n_frames = freqs_movie.shape[0]
        n_partials = freqs_movie.shape[1]
        t = np.arange(frames) / self.samplerate

        active = set()
        for layer in layers:
            vid = layer["id"]
            active.add(vid)
            voice = self._voices.get(vid)
            if voice is None:
                voice = {
                    "phases": np.zeros(n_partials),
                    "scan": 0.0,
                    "freqs": freqs_movie[0].copy(),
                    "amps": amps_movie[0].copy(),
                }
                self._voices[vid] = voice

            hue = layer["hue"]
            semitones = 14.0 * (hue if hue <= 0.5 else hue - 1.0)
            shift = 2.0 ** (semitones / 12.0)
            scan_rate = (layer["bpm"] / 120.0) * self.analysis["frame_rate"]
            # sat -> blur: more saturation = slower tracking = more smear
            blur = 0.5 + 0.45 * layer["sat"]
            level = self.VOICE_LEVEL * layer["val"]

            frame_idx = int(voice["scan"]) % n_frames
            voice["freqs"] = blur * voice["freqs"] + (1.0 - blur) * freqs_movie[frame_idx]
            voice["amps"] = blur * voice["amps"] + (1.0 - blur) * amps_movie[frame_idx]
            voice["scan"] = (voice["scan"] + scan_rate * frames / self.samplerate) % n_frames

            omega = 2.0 * np.pi * voice["freqs"] * shift  # rad/s per partial
            out += level * np.sum(
                voice["amps"][:, None]
                * np.sin(voice["phases"][:, None] + omega[:, None] * t[None, :]),
                axis=0,
            )
            voice["phases"] = (voice["phases"] + omega * frames / self.samplerate) % (
                2.0 * np.pi
            )

        self._voices = {k: v for k, v in self._voices.items() if k in active}
        out /= max(1.0, np.sqrt(len(layers)))
        return out.astype(np.float32)
