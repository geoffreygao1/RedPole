import threading

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
    assert snap[0] == {"id": layer_id, "hue": 0.1, "sat": 0.5, "val": 0.5, "bpm": 70}


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
