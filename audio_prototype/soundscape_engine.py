"""Top-level orchestration for the Evolving Soundscape Synthesizer, Phase 1
(spec section 11-13). Owns the harmonic pitch allocator, density/priority
state, and the source/transform banks; generate_block() is the per-block
entry point a desktop audio callback or the harness script (Task 16) calls
each buffer."""

import numpy as np

from modulation import RmsLimiter, soft_clip
from soundscape_density import DensityGainSmoother, ROLE_GAIN, assign_voice_roles
from soundscape_harmony import HarmonicField, PitchAllocator
from soundscape_sources import SourceBank
from soundscape_transforms import TransformBank


class SoundscapePatch:
    __slots__ = ("id", "hue", "sat", "val", "bpm", "source_preset", "transform_preset")

    def __init__(self, patch_id, hue, sat, val, bpm, source_preset, transform_preset):
        self.id = patch_id
        self.hue = hue
        self.sat = sat
        self.val = val
        self.bpm = bpm
        self.source_preset = source_preset
        self.transform_preset = transform_preset


class SoundscapeEngine:
    def __init__(self, samplerate=44100, seed=None, root_midi=62):
        self.samplerate = samplerate
        self.field = HarmonicField(root_midi=root_midi)
        self.allocator = PitchAllocator(self.field)
        self.sources = SourceBank(samplerate, seed=seed)
        self.transforms = TransformBank(samplerate, seed=seed)
        self.gain_smoother = DensityGainSmoother()
        self.limiter = RmsLimiter(target_rms=0.3)
        self._patches = {}
        self._assignments = {}
        self._connect_order = []
        self._next_id = 1

    def connect_patch(self, hue, sat, val, bpm, source_preset, transform_preset=None):
        pid = self._next_id
        self._next_id += 1
        self._patches[pid] = SoundscapePatch(pid, hue, sat, val, bpm, source_preset, transform_preset)
        self._connect_order.append(pid)
        return pid

    def disconnect_patch(self, pid):
        self._patches.pop(pid, None)
        self._connect_order = [p for p in self._connect_order if p != pid]
        self.allocator.release(pid)
        self._assignments.pop(pid, None)

    def set_patch_transform(self, pid, transform_preset):
        patch = self._patches.get(pid)
        if patch is not None:
            patch.transform_preset = transform_preset

    def generate_block(self, frames):
        patches = list(self._patches.values())
        active_ids = [p.id for p in patches]
        self.sources.sync(active_ids)
        self.transforms.sync(active_ids)

        if not patches:
            return np.zeros(frames, dtype=np.float32)

        density = min(1.0, len(patches) / 20.0)
        roles = assign_voice_roles(self._connect_order)
        voice_gain = self.gain_smoother.update(len(patches))

        mix = np.zeros(frames, dtype=np.float64)
        for patch in patches:
            if patch.id not in self._assignments:
                detune_class = "granular" if patch.source_preset.startswith("granular") else "foreground"
                rng = np.random.default_rng(patch.id)
                self._assignments[patch.id] = self.allocator.allocate(patch.id, rng, density, detune_class)
            assignment = self._assignments[patch.id]
            role_gain = ROLE_GAIN[roles.get(patch.id, "dormant")]
            if role_gain <= 0.0:
                continue
            voice = self.sources.render(
                patch.id, patch.source_preset, assignment,
                patch.hue, patch.sat, patch.val, patch.bpm, frames,
            )
            if patch.transform_preset:
                voice = self.transforms.render(patch.id, patch.transform_preset, voice, patch.bpm)
            mix += voice * role_gain * voice_gain

        mixed = self.limiter.process(mix.astype(np.float32))
        return soft_clip(mixed).astype(np.float32)
