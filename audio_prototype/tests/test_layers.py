import threading

import pytest

from layers import LayerRegistry


def test_add_returns_unique_ids():
    reg = LayerRegistry()
    id1 = reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
    id2 = reg.add(hue=0.2, sat=0.6, val=0.6, bpm=80)
    assert id1 != id2


def test_snapshot_reflects_added_layers():
    reg = LayerRegistry()
    layer_id = reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
    snap = reg.snapshot()
    assert len(snap) == 1
    assert snap[0] == {
        "id": layer_id, "hue": 0.1, "sat": 0.5, "val": 0.5, "bpm": 70,
        "engine": "tape",
    }


def test_add_with_engine_assignment():
    reg = LayerRegistry()
    reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70, engine="granular")
    assert reg.snapshot()[0]["engine"] == "granular"


def test_reverb_is_a_valid_engine():
    reg = LayerRegistry()
    reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70, engine="reverb")
    assert reg.snapshot()[0]["engine"] == "reverb"


def test_microcosm_families_are_valid_engines():
    reg = LayerRegistry()
    for engine in ("microloop", "granules", "glitch", "multidelay"):
        reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70, engine=engine)

    assert [layer["engine"] for layer in reg.snapshot()] == [
        "microloop",
        "granules",
        "glitch",
        "multidelay",
    ]


def test_add_rejects_unknown_engine():
    reg = LayerRegistry()
    with pytest.raises(ValueError):
        reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70, engine="delay")


def test_add_source_does_not_create_active_layer_until_connected():
    reg = LayerRegistry()
    source_id = reg.add_source(hue=0.1, sat=0.5, val=0.5, bpm=70)

    assert reg.snapshot() == []
    assert reg.sources_snapshot() == [
        {
            "id": source_id,
            "hue": 0.1,
            "sat": 0.5,
            "val": 0.5,
            "bpm": 70,
            "route": None,
        }
    ]


def test_connect_source_creates_active_layer_with_patch_metadata():
    reg = LayerRegistry()
    source_id = reg.add_source(hue=0.1, sat=0.5, val=0.5, bpm=70)

    reg.connect_source(source_id, engine="granules", row=1, col=3)

    assert reg.snapshot() == [
        {
            "id": source_id,
            "source_id": source_id,
            "hue": 0.1,
            "sat": 0.5,
            "val": 0.5,
            "bpm": 70,
            "engine": "granules",
            "patch_row": 1,
            "patch_col": 3,
        }
    ]
    assert reg.sources_snapshot()[0]["route"] == {
        "engine": "granules",
        "patch_row": 1,
        "patch_col": 3,
    }


def test_reconnecting_source_moves_existing_route():
    reg = LayerRegistry()
    source_id = reg.add_source(hue=0.1, sat=0.5, val=0.5, bpm=70)

    reg.connect_source(source_id, engine="granules", row=1, col=3)
    reg.connect_source(source_id, engine="glitch", row=2, col=0)

    snap = reg.snapshot()
    assert len(snap) == 1
    assert snap[0]["engine"] == "glitch"
    assert snap[0]["patch_row"] == 2
    assert snap[0]["patch_col"] == 0


def test_disconnect_source_removes_active_layer_but_keeps_source():
    reg = LayerRegistry()
    source_id = reg.add_source(hue=0.1, sat=0.5, val=0.5, bpm=70)
    reg.connect_source(source_id, engine="granules", row=1, col=3)

    reg.disconnect_source(source_id)

    assert reg.snapshot() == []
    assert reg.sources_snapshot()[0]["route"] is None


def test_remove_source_removes_source_and_route():
    reg = LayerRegistry()
    source_id = reg.add_source(hue=0.1, sat=0.5, val=0.5, bpm=70)
    reg.connect_source(source_id, engine="granules", row=1, col=3)

    reg.remove_source(source_id)

    assert reg.snapshot() == []
    assert reg.sources_snapshot() == []


def test_remove_deletes_only_that_layer():
    reg = LayerRegistry()
    id1 = reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
    id2 = reg.add(hue=0.2, sat=0.6, val=0.6, bpm=80)
    reg.remove(id1)
    snap = reg.snapshot()
    assert len(snap) == 1
    assert snap[0]["bpm"] == 80
    assert id2 is not None


def test_remove_unknown_id_is_noop():
    reg = LayerRegistry()
    reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
    reg.remove(9999)
    assert len(reg.snapshot()) == 1


def test_snapshot_is_a_copy():
    reg = LayerRegistry()
    reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
    snap = reg.snapshot()
    snap.append({"hue": 1, "sat": 1, "val": 1, "bpm": 1})
    assert len(reg.snapshot()) == 1


def test_concurrent_add_remove_does_not_crash():
    reg = LayerRegistry()

    def worker():
        for _ in range(50):
            layer_id = reg.add(hue=0.1, sat=0.5, val=0.5, bpm=70)
            reg.snapshot()
            reg.remove(layer_id)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert reg.snapshot() == []
