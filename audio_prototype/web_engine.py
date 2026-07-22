"""Browser-oriented audio orchestrator.

Unlike audio_engine.AudioEngine (which owns a sounddevice output stream
and decodes files via soundfile), WebEngine has no device or file I/O of
its own -- a JS Worker drives it by calling generate_block(frames)
repeatedly and hands it already-decoded samples via load_loop(). It
reuses the exact same effect classes as the desktop engine.
"""

import numpy as np

from crowd import CrowdState, EntryGestureTracker
from layers import LayerRegistry
from modulation import RmsLimiter, combine_layers, sat_to_unit, soft_clip, val_to_unit
from microcosm_processor import MicrocosmProcessor
from reverb import SchroederReverb
from spectral_stretch import SpectralSmear
from synth_source import SynthVoiceBank
from tape_modulator import TapeModulator, tape_column_controls
from wet_bus import WetBusManager

DEFAULT_SAMPLE_RATE = 44100
MAX_LOOP_SECONDS = 600.0
REVERB_DEFAULT_FEEDBACK = 0.84
REVERB_DEFAULT_CUTOFF = 7800.0
REVERB_SMOOTHING = 0.1
MICRO_FAMILIES = ("microloop", "granules", "glitch", "multidelay")


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
        self._seed = seed
        self.mode = "loop"
        self.registry = LayerRegistry()
        self.modulator = TapeModulator(samplerate=samplerate, seed=seed)
        self.microcosm = MicrocosmProcessor(samplerate, seed=seed)
        self.reverb = SchroederReverb(samplerate)
        self.wet_bus = WetBusManager(samplerate)
        self.entry_gestures = EntryGestureTracker(samplerate)
        self.wet_limiter = RmsLimiter(target_rms=0.35)
        self.reverb_mix = 0.975
        self.wet_dry = 0.5
        self._rv_feedback = REVERB_DEFAULT_FEEDBACK
        self._rv_cutoff = REVERB_DEFAULT_CUTOFF
        self.loop_array = None
        self.synth = SynthVoiceBank(samplerate, seed=seed)
        self.spectral_smear = SpectralSmear(samplerate, seed=seed)
        self.synth_tape = {}

    def set_mode(self, mode):
        """Switch modes and reset per-session patch/DSP state."""
        if mode not in ("loop", "synth"):
            raise ValueError(f"Unknown mode {mode!r}; expected 'loop' or 'synth'")
        self.mode = mode
        self.registry = LayerRegistry()
        self.microcosm = MicrocosmProcessor(self.samplerate, seed=self._seed)
        self.entry_gestures = EntryGestureTracker(self.samplerate)
        self.spectral_smear = SpectralSmear(self.samplerate, seed=self._seed)
        self.synth.reset()
        self.synth_tape = {}

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
        micro_layers = [l for l in layers if l["engine"] in MICRO_FAMILIES]
        reverb_layers = [l for l in layers if l["engine"] == "reverb"]
        zeros = np.zeros(frames, dtype=np.float32)

        combined = combine_layers(tape_layers)
        tape_controls = tape_column_controls(tape_layers)
        avg_hue = sum(l["hue"] for l in tape_layers) / len(tape_layers) if tape_layers else 0.0
        avg_sat = sum(l["sat"] for l in tape_layers) / len(tape_layers) if tape_layers else 0.5
        avg_val = sum(l["val"] for l in tape_layers) / len(tape_layers) if tape_layers else 1.0

        crowd = CrowdState.from_layers(layers)
        entry = self.entry_gestures.process(layers, frames, crowd.density)

        source_pos = self.modulator._read_pos
        base = self.modulator.process(
            self.loop_array,
            frames,
            combined["warble_depth"],
            combined["bloom_depth"] * (1.0 + entry.engine_gain("tape")),
            combined["rate_hz"],
            hue=avg_hue,
            sat=avg_sat,
            val=avg_val,
            tape_controls=tape_controls,
        )

        if not layers:
            return base.astype(np.float32)

        wet_raw = self.microcosm.process(
            self.loop_array, frames, micro_layers, source_pos=source_pos
        )
        n_wet = len(micro_layers)
        n_rv = len(reverb_layers)

        if reverb_layers:
            weights = np.array(
                [0.2 + l["sat"] + l["val"] for l in reverb_layers], dtype=np.float64
            )
            sats = np.array([l["sat"] for l in reverb_layers], dtype=np.float64)
            vals = np.array([l["val"] for l in reverb_layers], dtype=np.float64)
            bpms = np.array([l["bpm"] for l in reverb_layers], dtype=np.float64)
            rv_val = float(np.average(vals, weights=weights))
            rv_bpm = float(np.average(bpms, weights=weights))
            rv_sat_unit = float(np.average([sat_to_unit(s) for s in sats], weights=weights))
            target_fb = bpm_to_reverb_feedback(rv_bpm)
            target_cut = val_to_reverb_cutoff(rv_val)
            rv_density = min(1.0, np.sqrt(len(reverb_layers) / 6.0))
            rv_size = min(1.0, 0.48 + 0.38 * rv_sat_unit + 0.30 * rv_density)
            rv_diffusion = min(1.0, 0.55 + 0.30 * rv_sat_unit + 0.25 * rv_density)
        else:
            target_fb = REVERB_DEFAULT_FEEDBACK
            target_cut = REVERB_DEFAULT_CUTOFF
            rv_size = 0.35
            rv_diffusion = 0.45

        controls = self.wet_bus.controls(wet_voice_count=n_wet, reverb_layer_count=n_rv)
        target_fb = max(0.62, target_fb - controls["feedback_trim"])
        target_cut = max(700.0, target_cut * controls["cutoff_scale"])
        self._rv_feedback += REVERB_SMOOTHING * (target_fb - self._rv_feedback)
        self._rv_cutoff += REVERB_SMOOTHING * (target_cut - self._rv_cutoff)
        self.reverb.set_feedback(self._rv_feedback)
        self.reverb.set_cutoff(self._rv_cutoff)
        self.reverb.set_space(style="wash", size=rv_size, diffusion=rv_diffusion)

        managed_wet_raw = self.wet_bus.process(
            wet_raw, wet_voice_count=n_wet, reverb_layer_count=n_rv
        )
        # Reverb-only layers add no signal of their own -- they only shape
        # the room -- matching the desktop app's semantics.
        reverb_input = managed_wet_raw if reverb_layers else zeros
        reverb_wet = self.reverb.process(reverb_input) if reverb_layers else zeros
        wet = self.wet_limiter.process(managed_wet_raw + self.reverb_mix * reverb_wet)

        mix = float(np.clip(self.wet_dry, 0.0, 1.0))
        dry_gain = min(1.0, 2.0 * (1.0 - mix))
        wet_gain = min(1.0, 2.0 * mix)
        return soft_clip(dry_gain * base + wet_gain * wet).astype(np.float32)
