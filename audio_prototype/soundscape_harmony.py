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

    def __init__(self, root_midi=48, tension_enabled=True):
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


REGISTER_BANDS = (                     # spec 9.4 Hz ranges, spec 17.5 names
    ("sub", 40.0, 120.0),
    ("low", 120.0, 500.0),
    ("mid", 500.0, 2000.0),
    ("high", 2000.0, 6000.0),
    ("air", 6000.0, 14000.0),
)

REGISTER_LIMITS = {"sub": 2, "low": 3, "mid": 5, "high": 7, "air": 8}   # spec 17.5

DETUNE_CENTS_RANGE = {                 # spec 6.6
    "foreground": 4.0,
    "background": 8.0,
    "granular": 15.0,
    "texture": 30.0,                   # "unconstrained, but low in level"
}


def band_for_hz(hz):
    for name, lo, hi in REGISTER_BANDS:
        if lo <= hz < hi:
            return name
    return "air" if hz >= REGISTER_BANDS[-1][2] else "sub"


class RegisterOccupancy:
    def __init__(self):
        self._counts = {name: 0 for name, _, _ in REGISTER_BANDS}
        self._by_voice = {}

    def counts(self):
        return dict(self._counts)

    def register(self, vid, band):
        self.release(vid)
        self._counts[band] += 1
        self._by_voice[vid] = band

    def release(self, vid):
        band = self._by_voice.pop(vid, None)
        if band is not None:
            self._counts[band] -= 1

    def is_crowded(self, band):
        return self._counts[band] >= REGISTER_LIMITS[band]


class PitchAssignment:
    __slots__ = ("pitch_class", "octave", "detune_cents", "harmonic_role", "midi")

    def __init__(self, pitch_class, octave, detune_cents, harmonic_role, midi):
        self.pitch_class = pitch_class
        self.octave = octave
        self.detune_cents = detune_cents
        self.harmonic_role = harmonic_role
        self.midi = midi


class PitchAllocator:
    """Assigns each connected voice a pitch from the shared HarmonicField,
    preferring registers that are not already crowded and pushing sparse
    upper extensions as density rises (spec 6.5)."""

    def __init__(self, field, occupancy=None):
        self.field = field
        self.occupancy = occupancy if occupancy is not None else RegisterOccupancy()

    def allocate(self, vid, rng, density, detune_class="foreground"):
        role = self.field.weighted_role(rng)
        octave_offset = 0
        for _ in range(4):
            midi = self.field.midi_for_role(role, octave_offset)
            band = band_for_hz(midi_to_hz(midi))
            if not self.occupancy.is_crowded(band):
                break
            octave_offset += 1
        else:
            octave_offset = int(rng.integers(1, 3))
            midi = self.field.midi_for_role(role, octave_offset)
            band = band_for_hz(midi_to_hz(midi))
        if density > 0.6 and band in ("sub", "low"):
            octave_offset += 1
            midi = self.field.midi_for_role(role, octave_offset)
            band = band_for_hz(midi_to_hz(midi))
        detune_limit = DETUNE_CENTS_RANGE.get(detune_class, DETUNE_CENTS_RANGE["foreground"])
        detune_cents = float(rng.uniform(-detune_limit, detune_limit))
        self.occupancy.register(vid, band)
        return PitchAssignment(
            pitch_class=self.field.semitone_for_role(role) % 12,
            octave=octave_offset,
            detune_cents=detune_cents,
            harmonic_role=role,
            midi=midi + detune_cents / 100.0,
        )

    def release(self, vid):
        self.occupancy.release(vid)
