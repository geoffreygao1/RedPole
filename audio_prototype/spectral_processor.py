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
    """Per-layer oscillator-bank resynthesis; implemented in the next task."""

    def __init__(self, samplerate, seed=None):
        self.samplerate = samplerate
        self.analysis = None
        self._voices = {}
