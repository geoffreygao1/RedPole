"""Browser-oriented audio orchestrator.

Unlike audio_engine.AudioEngine (which owns a sounddevice output stream
and decodes files via soundfile), WebEngine has no device or file I/O of
its own -- a JS Worker drives it by calling generate_block(frames)
repeatedly and hands it already-decoded samples via load_loop(). It
reuses the exact same effect classes as the desktop engine.
"""

import numpy as np

from layers import LayerRegistry
from modulation import RmsLimiter, combine_layers, soft_clip, val_to_unit
from microcosm_processor import MicrocosmProcessor
from reverb import SchroederReverb
from tape_modulator import TapeModulator, tape_column_controls
from wet_bus import WetBusManager

DEFAULT_SAMPLE_RATE = 44100
MAX_LOOP_SECONDS = 600.0
REVERB_DEFAULT_FEEDBACK = 0.84
REVERB_DEFAULT_CUTOFF = 7800.0
REVERB_SMOOTHING = 0.1


def bpm_to_reverb_feedback(bpm):
    """Slow, calm pulses open a long wash; fast pulses tighten the room."""
    return min(0.985, max(0.82, 0.99 - 0.00025 * bpm))


def val_to_reverb_cutoff(val):
    """Dark crimsons give a muffled tail; bright pinks keep it airy."""
    return 800.0 + 7000.0 * val_to_unit(val)


class WebEngine:
    """Browser-oriented orchestrator: no device I/O, no file decoding --
    just generate_block(frames) and load_loop(samples), driven by a JS
    Worker. Reuses the exact same effect classes as the desktop engine.

    The base signal always routes through TapeModulator.process(), even
    with zero tape layers -- combine_layers([]) gives zero warble/bloom
    depth, which TapeModulator already treats as an exact, continuous
    passthrough. This keeps self.modulator._read_pos as the single
    position tracker at all times, so tape layers coming and going never
    causes a read-position jump.
    """

    def __init__(self, samplerate=DEFAULT_SAMPLE_RATE, seed=None):
        self.samplerate = samplerate
        self.registry = LayerRegistry()
        self.modulator = TapeModulator(samplerate=samplerate, seed=seed)
        self.microcosm = MicrocosmProcessor(samplerate, seed=seed)
        self.reverb = SchroederReverb(samplerate)
        self.wet_bus = WetBusManager(samplerate)
        self.wet_limiter = RmsLimiter(target_rms=0.35)
        self.reverb_mix = 0.975
        self.wet_dry = 0.5
        self._rv_feedback = REVERB_DEFAULT_FEEDBACK
        self._rv_cutoff = REVERB_DEFAULT_CUTOFF
        self.loop_array = None

    def load_loop(self, samples):
        array = np.asarray(samples, dtype=np.float32)
        max_len = int(MAX_LOOP_SECONDS * self.samplerate)
        if len(array) > max_len:
            array = array[:max_len]
        self.loop_array = array

    def generate_block(self, frames):
        if self.loop_array is None:
            raise RuntimeError("No loop loaded; call load_loop() first")

        layers = self.registry.snapshot()
        tape_layers = [l for l in layers if l["engine"] == "tape"]

        combined = combine_layers(tape_layers)
        tape_controls = tape_column_controls(tape_layers)
        avg_hue = sum(l["hue"] for l in tape_layers) / len(tape_layers) if tape_layers else 0.0
        avg_sat = sum(l["sat"] for l in tape_layers) / len(tape_layers) if tape_layers else 0.5
        avg_val = sum(l["val"] for l in tape_layers) / len(tape_layers) if tape_layers else 1.0

        base = self.modulator.process(
            self.loop_array,
            frames,
            combined["warble_depth"],
            combined["bloom_depth"],
            combined["rate_hz"],
            hue=avg_hue,
            sat=avg_sat,
            val=avg_val,
            tape_controls=tape_controls,
        )
        return base.astype(np.float32)
