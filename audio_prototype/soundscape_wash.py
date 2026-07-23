"""Global reverb + feedback-delay 'wash' for the soundbath synth output.

Applied to the SoundscapeEngine mono mix before the RMS limiter (whose job
includes taming reverb feedback). The tail keeps ringing on a zero input, so
notes bloom and decay after their voices are removed.
"""

import numpy as np

from reverb import SchroederReverb


class FeedbackDelay:
    """Single feedback delay line. Delay length >= block size, so a block's
    read indices never overlap its writes and the whole block vectorizes."""

    def __init__(self, samplerate, seconds=2.0, feedback=0.5):
        self.n = max(1, int(seconds * samplerate))
        self.buf = np.zeros(self.n, dtype=np.float64)
        self.pos = 0
        self.feedback = float(np.clip(feedback, 0.0, 0.95))

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        frames = len(x)
        if frames == 0:
            return x
        if frames > self.n:                      # tiny-delay fallback (not used at 2 s)
            out = np.empty(frames)
            buf, pos, n, fb = self.buf, self.pos, self.n, self.feedback
            for i in range(frames):
                d = buf[pos]
                out[i] = d
                buf[pos] = x[i] + d * fb
                pos = (pos + 1) % n
            self.pos = pos
            return out
        ridx = (np.arange(frames) + self.pos) % self.n
        out = self.buf[ridx].copy()
        self.buf[ridx] = x + out * self.feedback
        self.pos = (self.pos + frames) % self.n
        return out


class SoundscapeWash:
    # The reverb slider goes past unity so the top end is extra washy: the wet
    # level rises to 1.5x and the comb feedback (decay length) lengthens with it.
    REVERB_MAX = 1.5

    def __init__(self, samplerate, reverb_amount=0.35, delay_amount=0.2):
        self.samplerate = samplerate
        self.reverb = SchroederReverb(samplerate)
        self.reverb.set_space("wash", size=0.9, diffusion=0.7)
        self.delay = FeedbackDelay(samplerate, seconds=2.0, feedback=0.5)
        self.reverb_amount = 0.0
        self.delay_amount = 0.0
        self.set_reverb(reverb_amount)
        self.set_delay(delay_amount)

    def set_reverb(self, amount):
        self.reverb_amount = float(np.clip(amount, 0.0, self.REVERB_MAX))
        # Longer decay as the slider climbs (0.90 -> 0.96 at max).
        self.reverb.set_feedback(min(0.96, 0.90 + 0.04 * self.reverb_amount))

    def set_delay(self, amount):
        self.delay_amount = float(np.clip(amount, 0.0, 1.0))

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        wet_delay = self.delay.process(x) * self.delay_amount
        wet_reverb = np.asarray(self.reverb.process(x + wet_delay), dtype=np.float64) * self.reverb_amount
        return (x + wet_delay + wet_reverb).astype(np.float32)
