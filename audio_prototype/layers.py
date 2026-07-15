import threading

ENGINES = (
    "tape",
    "spectral",
    "granular",
    "microloop",
    "granules",
    "glitch",
    "multidelay",
    "reverb",
)


class LayerRegistry:
    """Thread-safe registry of active 'sends' (color+BPM layers).

    The audio callback thread reads via snapshot() every block; the GUI
    thread mutates via add()/remove() on user action. All access goes
    through a single lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._layers = {}
        self._sources = {}
        self._next_id = 1

    def add(self, hue, sat, val, bpm, engine="tape"):
        if engine not in ENGINES:
            raise ValueError(f"Unknown engine {engine!r}; expected one of {ENGINES}")
        with self._lock:
            layer_id = self._next_id
            self._next_id += 1
            self._layers[layer_id] = {
                "id": layer_id, "hue": hue, "sat": sat, "val": val, "bpm": bpm,
                "engine": engine,
            }
            return layer_id

    def add_source(self, hue, sat, val, bpm):
        with self._lock:
            source_id = self._next_id
            self._next_id += 1
            self._sources[source_id] = {
                "id": source_id,
                "hue": hue,
                "sat": sat,
                "val": val,
                "bpm": bpm,
                "route": None,
            }
            return source_id

    def connect_source(self, source_id, engine, row, col):
        if engine not in ENGINES:
            raise ValueError(f"Unknown engine {engine!r}; expected one of {ENGINES}")
        with self._lock:
            source = self._sources[source_id]
            source["route"] = {
                "engine": engine,
                "patch_row": row,
                "patch_col": col,
            }
            self._layers[source_id] = {
                "id": source_id,
                "source_id": source_id,
                "hue": source["hue"],
                "sat": source["sat"],
                "val": source["val"],
                "bpm": source["bpm"],
                "engine": engine,
                "patch_row": row,
                "patch_col": col,
            }

    def disconnect_source(self, source_id):
        with self._lock:
            source = self._sources.get(source_id)
            if source is not None:
                source["route"] = None
            self._layers.pop(source_id, None)

    def remove_source(self, source_id):
        with self._lock:
            self._sources.pop(source_id, None)
            self._layers.pop(source_id, None)

    def sources_snapshot(self):
        with self._lock:
            return [dict(source) for source in self._sources.values()]

    def remove(self, layer_id):
        with self._lock:
            self._layers.pop(layer_id, None)

    def snapshot(self):
        with self._lock:
            return [dict(layer) for layer in self._layers.values()]
