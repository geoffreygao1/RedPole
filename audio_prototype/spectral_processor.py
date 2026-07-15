import numpy as np

from modulation import clamp, hue_to_bipolar

N_PARTIALS = 24
FFT_SIZE = 4096
HOP_SIZE = 1024
PITCH_SPAN_SEMITONES = 7.0
LIVE_FEEDBACK_GAIN = 0.85


def _extract_partials(mag, bin_freqs, n_partials):
    """Pick the strongest local-maxima peaks from a magnitude spectrum."""
    freqs = np.zeros(n_partials)
    amps = np.zeros(n_partials)
    peaks = np.where((mag[1:-1] > mag[:-2]) & (mag[1:-1] > mag[2:]))[0] + 1
    if len(peaks) == 0:
        return freqs, amps
    top = peaks[np.argsort(mag[peaks])[::-1][:n_partials]]
    freqs[:len(top)] = bin_freqs[top]
    amps[:len(top)] = mag[top]
    return freqs, amps


def analyze_frame(window, samplerate, n_partials=N_PARTIALS):
    """Single-frame partial extraction for live-output analysis.

    Amps are TRUE amplitudes (a sine of amplitude A reports ~A), NOT
    normalized to the frame's max. Per-frame normalization made even a
    fading output re-excite the feedback voices at full level, so the
    loop could never decay.
    """
    window = np.asarray(window, dtype=np.float64)
    hann = np.hanning(len(window))
    mag = np.abs(np.fft.rfft(window * hann))
    bin_freqs = np.fft.rfftfreq(len(window), 1.0 / samplerate)
    freqs, amps = _extract_partials(mag, bin_freqs, n_partials)
    # windowed-FFT peak of a sine with amplitude A is A * sum(hann) / 2
    amps *= 2.0 / np.sum(hann)
    return freqs, amps


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
        freqs[i], amps[i] = _extract_partials(mag, bin_freqs, n_partials)

    peak = amps.max()
    if peak > 0:
        amps /= peak
    return {"freqs": freqs, "amps": amps, "frame_rate": samplerate / hop_size}


class SpectralProcessor:
    """Per-layer oscillator-bank resynthesis.

    Each active layer is an independent voice. In precomputed mode the
    voice scans the analysis movie (bpm -> scan speed). When a live_frame
    is supplied (realtime output analysis), the voice smooths toward that
    frame instead -- bpm sets tracking speed, and the feedback gain keeps
    self-resynthesis from running away. Either way: hue -> pitch shift
    (+/-7 st across the finger gamut), sat -> blur, val -> voice level.
    """

    VOICE_LEVEL = 0.35

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self.analysis = None
        self._voices = {}

    def set_analysis(self, analysis):
        self.analysis = analysis
        self._voices = {}

    def process(self, loop_array, frames, layers, live_frame=None):
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

            semitones = PITCH_SPAN_SEMITONES * hue_to_bipolar(layer["hue"])
            shift = 2.0 ** (semitones / 12.0)
            level = self.VOICE_LEVEL * layer["val"]

            if live_frame is not None:
                target_freqs, target_amps = live_frame
                # divide by voice count so N voices all hearing the same
                # output can't multiply each other back above unity gain
                target_amps = target_amps * (LIVE_FEEDBACK_GAIN / len(layers))
                # bpm -> tracking speed (fast pulse = tight tracking),
                # sat adds smear on top
                alpha = clamp(0.97 - 0.5 * (layer["bpm"] / 300.0), 0.3, 0.97)
                alpha = clamp(alpha + 0.02 + 0.2 * layer["sat"], 0.0, 0.985)
            else:
                frame_idx = int(voice["scan"]) % n_frames
                target_freqs = freqs_movie[frame_idx]
                target_amps = amps_movie[frame_idx]
                scan_rate = (layer["bpm"] / 120.0) * self.analysis["frame_rate"]
                voice["scan"] = (
                    voice["scan"] + scan_rate * frames / self.samplerate
                ) % n_frames
                # sat -> blur: more saturation = slower tracking = more smear
                alpha = 0.5 + 0.45 * layer["sat"]

            voice["freqs"] = alpha * voice["freqs"] + (1.0 - alpha) * target_freqs
            voice["amps"] = alpha * voice["amps"] + (1.0 - alpha) * target_amps

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
