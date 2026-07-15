import numpy as np

from modulation import clamp, hue_to_bipolar, sat_to_unit, val_to_unit

N_PARTIALS = 24
FFT_SIZE = 4096
HOP_SIZE = 1024
LIVE_FEEDBACK_GAIN = 0.85
FOCUS_SPAN_OCTAVES = 2.0
BANDWIDTH_MIN_OCTAVES = 0.45
BANDWIDTH_MAX_OCTAVES = 2.5
MIN_ACTIVE_PARTIALS = 2
SOURCE_ENVELOPE_WINDOW = 256
MISSING_PARTIAL_RELEASE = 0.35
PHASE_DIFFUSION_BASE = 0.007
PHASE_DIFFUSION_SAT = 0.022
DECLICK_SAMPLES = 128


def spectral_focus_controls(freqs, amps, layer):
    freqs = np.asarray(freqs, dtype=np.float64)
    amps = np.asarray(amps, dtype=np.float64)
    valid = (freqs > 0.0) & (amps > 0.0)
    if not np.any(valid):
        natural_focus = 440.0
    else:
        weights = amps[valid] / np.sum(amps[valid])
        natural_focus = float(np.exp(np.sum(weights * np.log(freqs[valid]))))

    focus_hz = natural_focus * 2.0 ** (
        FOCUS_SPAN_OCTAVES * hue_to_bipolar(layer["hue"])
    )
    bandwidth = (
        BANDWIDTH_MAX_OCTAVES
        - sat_to_unit(layer["sat"])
        * (BANDWIDTH_MAX_OCTAVES - BANDWIDTH_MIN_OCTAVES)
    )
    density = int(
        round(
            MIN_ACTIVE_PARTIALS
            + val_to_unit(layer["val"]) * (len(freqs) - MIN_ACTIVE_PARTIALS)
        )
    )
    return {
        "focus_hz": focus_hz,
        "bandwidth_octaves": bandwidth,
        "density": max(MIN_ACTIVE_PARTIALS, min(len(freqs), density)),
    }


def apply_spectral_focus(freqs, amps, layer):
    freqs = np.asarray(freqs, dtype=np.float64)
    amps = np.asarray(amps, dtype=np.float64)
    shaped = np.zeros_like(amps)
    valid = (freqs > 0.0) & (amps > 0.0)
    if not np.any(valid):
        return shaped

    controls = spectral_focus_controls(freqs, amps, layer)
    distance = np.abs(np.log2(freqs[valid] / controls["focus_hz"]))
    sigma = max(controls["bandwidth_octaves"], 1e-6)
    weights = np.exp(-0.5 * (distance / sigma) ** 2)
    shaped_valid = amps[valid] * weights

    keep = min(controls["density"], np.count_nonzero(valid))
    if keep < len(shaped_valid):
        threshold_idx = np.argsort(shaped_valid)[::-1][:keep]
        sparse = np.zeros_like(shaped_valid)
        sparse[threshold_idx] = shaped_valid[threshold_idx]
        shaped_valid = sparse

    shaped[valid] = shaped_valid
    return shaped


def _read_loop_segment(loop_array, start, frames):
    idx = (int(start) + np.arange(frames)) % len(loop_array)
    return np.asarray(loop_array, dtype=np.float64)[idx]


def source_amplitude_envelope(loop_array, start, frames):
    segment = _read_loop_segment(loop_array, start, frames)
    window = min(SOURCE_ENVELOPE_WINDOW, max(1, frames))
    kernel = np.ones(window, dtype=np.float64) / window
    rms = np.sqrt(np.convolve(segment * segment, kernel, mode="same"))
    peak = float(np.max(np.abs(loop_array)))
    if peak <= 1e-9:
        return np.zeros(frames, dtype=np.float64)
    return np.clip(rms / peak, 0.0, 1.0)


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
    voice scans the analysis movie with the source. When a live_frame
    is supplied (realtime output analysis), the voice smooths toward that
    frame instead -- bpm sets tracking speed, and the feedback gain keeps
    self-resynthesis from running away. Either way: hue -> spectral focus,
    sat -> bandwidth, val -> density and voice level.
    """

    VOICE_LEVEL = 0.24

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self._seed = seed
        self.analysis = None
        self._voices = {}
        self._last_output = 0.0

    def set_analysis(self, analysis):
        self.analysis = analysis
        self._voices = {}
        self._last_output = 0.0

    def process(self, loop_array, frames, layers, live_frame=None, scan_start=None):
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
                initial_scan = 0.0 if scan_start is None else float(scan_start)
                frame_idx = int(initial_scan) % n_frames
                voice = {
                    "rng": np.random.default_rng(
                        None if self._seed is None else self._seed + vid
                    ),
                    "phases": np.zeros(n_partials),
                    "scan": initial_scan,
                    "freqs": freqs_movie[frame_idx].copy(),
                    "amps": amps_movie[frame_idx].copy(),
                }
                self._voices[vid] = voice

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
                voice["scan"] = (
                    voice["scan"]
                    + self.analysis["frame_rate"] * frames / self.samplerate
                ) % n_frames
                # sat -> blur: more saturation = slower tracking = more smear
                alpha = 0.5 + 0.45 * layer["sat"]

            previous_amps = voice["amps"].copy()
            voice["freqs"] = alpha * voice["freqs"] + (1.0 - alpha) * target_freqs
            target_amps = apply_spectral_focus(target_freqs, target_amps, layer)
            amp_alpha = np.where(
                target_amps < voice["amps"],
                min(alpha, MISSING_PARTIAL_RELEASE),
                alpha,
            )
            voice["amps"] = amp_alpha * voice["amps"] + (1.0 - amp_alpha) * target_amps

            omega = 2.0 * np.pi * voice["freqs"]  # rad/s per partial
            amp_ramp = np.linspace(0.0, 1.0, frames)
            amp_curve = (
                previous_amps[:, None]
                + (voice["amps"] - previous_amps)[:, None] * amp_ramp[None, :]
            )
            diffusion_amount = PHASE_DIFFUSION_BASE + PHASE_DIFFUSION_SAT * layer["sat"]
            phase_steps = voice["rng"].normal(
                0.0, diffusion_amount, size=(n_partials, frames)
            )
            phase_steps[:, 0] = 0.0
            phase_diffusion = np.cumsum(phase_steps, axis=1)
            rendered = np.sum(
                amp_curve
                * np.sin(
                    voice["phases"][:, None]
                    + omega[:, None] * t[None, :]
                    + phase_diffusion
                ),
                axis=0,
            )
            partial_gain = np.maximum(1.0, np.sum(np.abs(amp_curve), axis=0))
            if scan_start is None:
                source_sample = voice["scan"] * HOP_SIZE
            else:
                source_sample = float(scan_start) * HOP_SIZE
            source_env = source_amplitude_envelope(loop_array, source_sample, frames)
            out += level * source_env * rendered / partial_gain
            voice["phases"] = (voice["phases"] + omega * frames / self.samplerate) % (
                2.0 * np.pi
            )

        self._voices = {k: v for k, v in self._voices.items() if k in active}
        out /= max(1.0, np.sqrt(len(layers)))
        out = self._declick(out)
        return out.astype(np.float32)

    def _declick(self, out):
        if len(out) == 0:
            return out
        correction = out[0] - self._last_output
        n = min(DECLICK_SAMPLES, len(out))
        if n > 0:
            out = out.copy()
            out[:n] -= correction * np.linspace(1.0, 0.0, n, endpoint=False)
        self._last_output = float(out[-1])
        return out
