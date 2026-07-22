import numpy as np

from soundscape_harmony import HarmonicField, ROLE_WEIGHTS, midi_to_hz


def test_midi_to_hz_a4_is_440():
    assert abs(midi_to_hz(69) - 440.0) < 1e-6


def test_field_midi_for_role_uses_root_and_semitone_offsets():
    field = HarmonicField(root_midi=62)
    assert field.midi_for_role("root") == 62
    assert field.midi_for_role("fifth") == 62 + 7
    assert field.midi_for_role("fifth", octave_offset=1) == 62 + 7 + 12


def test_field_excludes_tension_when_disabled():
    field = HarmonicField(root_midi=62, tension_enabled=False)
    assert "tension" not in field.roles()
    rng = np.random.default_rng(0)
    for _ in range(50):
        assert field.weighted_role(rng) != "tension"


def test_weighted_role_matches_declared_weights_over_many_draws():
    field = HarmonicField(root_midi=62)
    rng = np.random.default_rng(1)
    counts = {r: 0 for r in field.roles()}
    n = 20000
    for _ in range(n):
        counts[field.weighted_role(rng)] += 1
    for role, weight in ROLE_WEIGHTS.items():
        assert abs(counts[role] / n - weight) < 0.02

from soundscape_harmony import (
    DETUNE_CENTS_RANGE,
    PitchAllocator,
    RegisterOccupancy,
    band_for_hz,
)


def test_band_for_hz_matches_named_ranges():
    assert band_for_hz(80) == "sub"
    assert band_for_hz(300) == "low"
    assert band_for_hz(1000) == "mid"
    assert band_for_hz(4000) == "high"
    assert band_for_hz(10000) == "air"


def test_register_occupancy_tracks_and_releases():
    occ = RegisterOccupancy()
    occ.register(1, "sub")
    occ.register(2, "sub")
    assert occ.counts()["sub"] == 2
    occ.release(1)
    assert occ.counts()["sub"] == 1
    occ.release(1)  # releasing twice is a no-op
    assert occ.counts()["sub"] == 1


def test_allocator_avoids_crowded_low_registers_at_high_density():
    field = HarmonicField(root_midi=24)  # very low root -> "root" role starts in "sub"
    allocator = PitchAllocator(field)
    rng = np.random.default_rng(2)
    assignment = allocator.allocate(1, rng, density=0.9, detune_class="foreground")
    assert assignment.octave >= 1  # pushed up out of the crowded low register


def test_allocator_detune_respects_class_range():
    field = HarmonicField(root_midi=62)
    allocator = PitchAllocator(field)
    rng = np.random.default_rng(3)
    for _ in range(50):
        a = allocator.allocate(4, rng, density=0.1, detune_class="granular")
        assert abs(a.detune_cents) <= DETUNE_CENTS_RANGE["granular"]
        allocator.release(4)


def test_allocator_release_frees_register_slot():
    field = HarmonicField(root_midi=62)
    allocator = PitchAllocator(field)
    rng = np.random.default_rng(4)
    allocator.allocate(1, rng, density=0.0)
    before = sum(allocator.occupancy.counts().values())
    allocator.release(1)
    after = sum(allocator.occupancy.counts().values())
    assert after == before - 1
