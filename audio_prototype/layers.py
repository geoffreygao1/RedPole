import threading

ENGINES = ("tape", "spectral", "granular", "reverb")


class LayerRegistry:
    """Thread-safe registry of active 'sends' (color+BPM layers).

    The audio callback thread reads via snapshot() every block; the GUI
    thread mutates via add()/remove() on user action. All access goes
    through a single lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._layers = {}
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

    def remove(self, layer_id):
        with self._lock:
            self._layers.pop(layer_id, None)

    def snapshot(self):
        with self._lock:
            return [dict(layer) for layer in self._layers.values()]
