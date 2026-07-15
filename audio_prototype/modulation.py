import numpy as np

MAX_WARBLE_DEPTH = 0.02
MAX_BLOOM_DEPTH = 0.6
PER_LAYER_MIN_WARBLE = 0.001
PER_LAYER_MAX_WARBLE = 0.004
PER_LAYER_MIN_BLOOM = 0.02
PER_LAYER_MAX_BLOOM = 0.12


def clamp(value, min_v, max_v):
    return max(min_v, min(max_v, value))


def bpm_to_hz(bpm):
    return bpm / 60.0


def hue_to_warble_depth(hue_norm):
    hue_norm = clamp(hue_norm, 0.0, 1.0)
    return PER_LAYER_MIN_WARBLE + hue_norm * (PER_LAYER_MAX_WARBLE - PER_LAYER_MIN_WARBLE)


def sat_val_to_bloom_depth(sat, val):
    sat = clamp(sat, 0.0, 1.0)
    val = clamp(val, 0.0, 1.0)
    avg = (sat + val) / 2.0
    return PER_LAYER_MIN_BLOOM + avg * (PER_LAYER_MAX_BLOOM - PER_LAYER_MIN_BLOOM)


def combine_layers(layers):
    if not layers:
        return {"warble_depth": 0.0, "bloom_depth": 0.0, "rate_hz": 0.0}

    warble_depth = clamp(
        sum(hue_to_warble_depth(l["hue"]) for l in layers), 0.0, MAX_WARBLE_DEPTH
    )
    bloom_depth = clamp(
        sum(sat_val_to_bloom_depth(l["sat"], l["val"]) for l in layers),
        0.0,
        MAX_BLOOM_DEPTH,
    )
    rate_hz = sum(bpm_to_hz(l["bpm"]) for l in layers) / len(layers)
    return {"warble_depth": warble_depth, "bloom_depth": bloom_depth, "rate_hz": rate_hz}


def soft_clip(x, threshold=0.9):
    """Identity below `threshold`; tanh-compresses toward +/-1 above it.

    Note: the tanh argument is (|x| - threshold), NOT divided by
    (1 - threshold) -- dividing by that small gap makes the argument blow
    up for even modest overshoots (e.g. ~41 at x=5, threshold=0.9), which
    saturates tanh to exactly 1.0 in float64 and turns this into a hard
    clip, defeating the purpose of a soft clipper.
    """
    x = np.asarray(x)
    over = np.abs(x) > threshold
    compressed = np.sign(x) * (threshold + (1.0 - threshold) * np.tanh(np.abs(x) - threshold))
    return np.where(over, compressed, x)
