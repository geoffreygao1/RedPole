from soundscape_engine import SoundscapeEngine
from synth_tab import SynthPatchModel, SYNTH_PATCH_LIMIT, source_preset_id, transform_preset_id


def _model():
    return SynthPatchModel(SoundscapeEngine(samplerate=44100, seed=1))


def test_assign_colors_the_jack_but_stays_silent():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    assert cid in m.sources
    cell = m.assign_source_to_generator(cid, (2, 0))     # pluck/piano
    assert cell == (2, 0)
    assert cid not in m.sources                          # single-use: consumed
    p = m.placements[(2, 0)]
    assert p["source_id"] == source_preset_id(2, 0)
    assert p["pid"] is None                              # silent: no engine voice yet
    assert m.engine._patches == {}


def test_cabling_to_modifier_starts_the_voice_and_pulling_it_silences_again():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    m.assign_source_to_generator(cid, (2, 0))
    m.set_placement_transform((2, 0), (0, 0))            # cable to delay_1
    p = m.placements[(2, 0)]
    assert p["pid"] is not None                          # now sounding
    assert p["transform_id"] == transform_preset_id(0, 0)
    assert m.engine._patches[p["pid"]].source_preset == source_preset_id(2, 0)
    assert m.engine._patches[p["pid"]].transform_preset == transform_preset_id(0, 0)
    m.set_placement_transform((2, 0), None)              # pull the cable
    assert m.placements[(2, 0)]["pid"] is None           # silent again
    assert m.engine._patches == {}


def test_retarget_modifier_keeps_one_voice():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    m.assign_source_to_generator(cid, (2, 0))
    m.set_placement_transform((2, 0), (0, 0))
    pid = m.placements[(2, 0)]["pid"]
    m.set_placement_transform((2, 0), (1, 2))            # different modifier
    assert m.placements[(2, 0)]["pid"] == pid            # same voice, retargeted
    assert m.engine._patches[pid].transform_preset == transform_preset_id(1, 2)


def test_assign_onto_occupied_jack_replaces_previous_placement():
    m = _model()
    c1 = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff0000")
    c2 = m.add_source(0.05, 0.68, 0.94, 90.0, "#ff8800")
    m.assign_source_to_generator(c1, (1, 1))
    m.set_placement_transform((1, 1), (0, 0))            # first is sounding
    pid1 = m.placements[(1, 1)]["pid"]
    m.assign_source_to_generator(c2, (1, 1))             # same jack
    assert pid1 not in m.engine._patches                 # old voice disconnected
    assert len(m.placements) == 1
    assert m.placements[(1, 1)]["color"] == "#ff8800"
    assert m.placements[(1, 1)]["pid"] is None           # replacement starts silent


def test_move_silent_placement_reassigns_source_and_stays_silent():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    m.assign_source_to_generator(cid, (2, 0))            # pluck/piano
    new = m.move_placement((2, 0), (2, 1))               # -> pluck/guitar
    assert new == (2, 1)
    assert (2, 0) not in m.placements
    assert m.placements[(2, 1)]["source_id"] == source_preset_id(2, 1)
    assert m.placements[(2, 1)]["pid"] is None
    assert m.engine._patches == {}


def test_move_sounding_placement_reconnects_with_new_source():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    m.assign_source_to_generator(cid, (2, 0))
    m.set_placement_transform((2, 0), (0, 0))
    old_pid = m.placements[(2, 0)]["pid"]
    m.move_placement((2, 0), (3, 4))                     # pad row, col V
    p = m.placements[(3, 4)]
    assert old_pid not in m.engine._patches              # old voice gone
    assert p["pid"] is not None and p["pid"] != old_pid  # reconnected
    assert m.engine._patches[p["pid"]].source_preset == source_preset_id(3, 4)
    assert m.engine._patches[p["pid"]].transform_preset == transform_preset_id(0, 0)


def test_remove_placement_disconnects_and_frees_jack():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    m.assign_source_to_generator(cid, (3, 2))
    m.set_placement_transform((3, 2), (0, 0))
    pid = m.placements[(3, 2)]["pid"]
    m.remove_placement((3, 2))
    assert pid not in m.engine._patches
    assert (3, 2) not in m.placements


def test_combined_cap_counts_sources_plus_placements():
    m = _model()
    for _ in range(SYNTH_PATCH_LIMIT):
        assert m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800") is not None
    assert m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800") is None   # at cap
    assert m.total_count() == SYNTH_PATCH_LIMIT


def test_assign_unknown_source_returns_none():
    m = _model()
    assert m.assign_source_to_generator(999, (0, 0)) is None
