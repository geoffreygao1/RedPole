"""Shared harmonic field for soundscape voices (spec section 6, 17).

All tonal/modal voices pull pitches from one shared pitch set instead of
choosing arbitrary independent notes. This module owns the pitch set,
per-role weighting, register occupancy, and the pitch allocator (Task 3).
"""

import numpy as np

PENTATONIC_SEMITONES = (0, 2, 5, 7, 10)   # suspended pentatonic, spec 17.8

ROLE_SEMITONES = {
    "root": 0,
    "fifth": 7,
    "fourth": 5,
    "ninth": 2,
    "seventh": 10,
    "tension": 1,          # minor second above root, spec 17.8
}

ROLE_WEIGHTS = {           # spec 17.3
    "root": 0.32,
    "fifth": 0.24,
    "fourth": 0.16,
    "ninth": 0.14,
    "seventh": 0.10,
    "tension": 0.04,
}


def midi_to_hz(midi):
    return 440.0 * (2.0 ** ((np.asarray(midi, dtype=np.float64) - 69.0) / 12.0))


class HarmonicField:
    """The current shared tonal center + pitch set (spec 17.3). A future
    Phase 4 plan will make root_midi/tension_enabled evolve over time
    (spec 6.7's HarmonicState); for Phase 1 it is fixed at construction."""

    def __init__(self, root_midi=62, tension_enabled=True):
        self.root_midi = int(root_midi)
        self.tension_enabled = tension_enabled

    def roles(self):
        if self.tension_enabled:
            return tuple(ROLE_WEIGHTS.keys())
        return tuple(r for r in ROLE_WEIGHTS if r != "tension")

    def weighted_role(self, rng):
        roles = self.roles()
        weights = np.array([ROLE_WEIGHTS[r] for r in roles], dtype=np.float64)
        weights /= weights.sum()
        return roles[int(rng.choice(len(roles), p=weights))]

    def semitone_for_role(self, role):
        return ROLE_SEMITONES[role]

    def midi_for_role(self, role, octave_offset=0):
        return self.root_midi + self.semitone_for_role(role) + 12 * int(octave_offset)
