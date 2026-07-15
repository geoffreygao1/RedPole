from dataclasses import dataclass

import numpy as np

ENGINES = (
    "tape",
    "granular",
    "spectral",
    "microloop",
    "granules",
    "glitch",
    "multidelay",
    "reverb",
)


@dataclass(frozen=True)
class CrowdState:
    count: int
    density: float
    bpm_mean: float
    bpm_activity: float
    brightness_mean: float
    brightness_activity: float
    engine_weights: dict

    @classmethod
    def from_layers(cls, layers):
        if not layers:
            return cls(
                count=0,
                density=0.0,
                bpm_mean=0.0,
                bpm_activity=0.0,
                brightness_mean=0.0,
                brightness_activity=0.0,
                engine_weights={engine: 0.0 for engine in ENGINES},
            )

        count = len(layers)
        bpms = np.array([layer["bpm"] for layer in layers], dtype=np.float64)
        vals = np.array([layer["val"] for layer in layers], dtype=np.float64)
        engine_counts = {
            engine: sum(1 for layer in layers if layer["engine"] == engine)
            for engine in ENGINES
        }
        weighted_counts = {
            engine: float(np.sqrt(engine_counts[engine])) for engine in ENGINES
        }
        weight_total = sum(weighted_counts.values())

        return cls(
            count=count,
            density=float(min(1.0, np.sqrt(count / 20.0))),
            bpm_mean=float(np.mean(bpms)),
            bpm_activity=float(min(1.0, np.std(bpms) / 80.0)),
            brightness_mean=float(np.mean(vals)),
            brightness_activity=float(min(1.0, np.std(vals) / 0.35)),
            engine_weights={
                engine: (
                    weighted_counts[engine] / weight_total
                    if weight_total > 0.0
                    else 0.0
                )
                for engine in ENGINES
            },
        )


@dataclass(frozen=True)
class EntryGestureState:
    gains: dict
    active_count: int

    def engine_gain(self, engine):
        return self.gains.get(engine, 0.0)


class EntryGestureTracker:
    """Short notices for new participants before they fade into the crowd."""

    def __init__(self, samplerate, duration_seconds=6.0, max_active=6):
        self.samplerate = samplerate
        self.duration_frames = max(1, int(duration_seconds * samplerate))
        self.max_active = max(1, int(max_active))
        self._seen_ids = set()
        self._gestures = []
        self._sequence = 0

    def process(self, layers, frames, density):
        for layer in layers:
            layer_id = layer["id"]
            if layer_id in self._seen_ids:
                continue
            self._seen_ids.add(layer_id)
            self._sequence += 1
            self._gestures.append(
                {
                    "id": layer_id,
                    "engine": layer["engine"],
                    "age": 0,
                    "val": layer["val"],
                    "sequence": self._sequence,
                }
            )

        self._gestures = sorted(
            self._gestures,
            key=lambda gesture: gesture["sequence"],
            reverse=True,
        )[: self.max_active]

        density_trim = 1.0 / (1.0 + 0.8 * max(0.0, min(1.0, density)))
        gains = {engine: 0.0 for engine in ENGINES}
        active = []
        for gesture in self._gestures:
            progress = gesture["age"] / self.duration_frames
            if progress < 1.0:
                # A quick perceptual onset, then a slow fade into the bed.
                envelope = (1.0 - progress) ** 1.6
                gains[gesture["engine"]] += (
                    0.28 * gesture["val"] * envelope * density_trim
                )
                active.append(gesture)
            gesture["age"] += frames

        self._gestures = [
            gesture
            for gesture in active
            if gesture["age"] < self.duration_frames
        ]
        gains = {
            engine: min(0.5, float(gain))
            for engine, gain in gains.items()
        }
        return EntryGestureState(gains=gains, active_count=len(self._gestures))
