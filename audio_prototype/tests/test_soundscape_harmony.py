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
