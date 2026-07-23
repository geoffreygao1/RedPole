from soundscape_engine import SoundscapeEngine
from synth_tab import SynthPatchModel, SYNTH_PATCH_LIMIT, source_preset_id, transform_preset_id


def _model():
    return SynthPatchModel(SoundscapeEngine(samplerate=44100, seed=1))


def test_send_then_assign_consumes_source_and_creates_source_only_voice():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    assert cid in m.sources
    pid = m.assign_source_to_generator(cid, (0, 1))     # additive_2
    assert cid not in m.sources                          # single-use: consumed
    assert m.voices[pid]["source_id"] == source_preset_id(0, 1)
    assert m.voices[pid]["transform_cell"] is None
    assert m.jack_to_pid[(0, 1)] == pid
    assert m.engine._patches[pid].transform_preset is None


def test_cable_generator_to_modifier_sets_and_clears_transform():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    pid = m.assign_source_to_generator(cid, (0, 0))
    m.set_voice_transform(pid, (2, 3))                   # pitch_4
    assert m.voices[pid]["transform_id"] == transform_preset_id(2, 3)
    assert m.engine._patches[pid].transform_preset == transform_preset_id(2, 3)
    m.set_voice_transform(pid, None)
    assert m.voices[pid]["transform_cell"] is None
    assert m.engine._patches[pid].transform_preset is None


def test_assign_onto_occupied_jack_replaces_previous_voice():
    m = _model()
    c1 = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff0000")
    c2 = m.add_source(0.05, 0.68, 0.94, 90.0, "#ff8800")
    p1 = m.assign_source_to_generator(c1, (1, 1))
    p2 = m.assign_source_to_generator(c2, (1, 1))        # same jack
    assert p1 not in m.engine._patches                   # old voice disconnected
    assert m.jack_to_pid[(1, 1)] == p2
    assert len(m.voices) == 1


def test_remove_voice_frees_jack_and_disconnects():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    pid = m.assign_source_to_generator(cid, (3, 2))
    m.remove_voice(pid)
    assert pid not in m.engine._patches
    assert (3, 2) not in m.jack_to_pid
    assert pid not in m.voices


def test_combined_cap_counts_sources_plus_voices():
    m = _model()
    for _ in range(SYNTH_PATCH_LIMIT):
        assert m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800") is not None
    assert m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800") is None   # at cap
    assert m.total_count() == SYNTH_PATCH_LIMIT


def test_assign_unknown_source_returns_none():
    m = _model()
    assert m.assign_source_to_generator(999, (0, 0)) is None
