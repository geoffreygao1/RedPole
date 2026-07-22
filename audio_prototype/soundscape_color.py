"""Calibrated color mapping for the soundscape system (spec section 5.1-5.4).

The scanner only produces red-to-orange hues; warmth/brightness/saturation
are the continuous timbral macros every source/transform engine reads
instead of treating color as a preset selector.
"""

from modulation import hue_to_unit, sat_to_unit, val_to_unit


def calibrate_color(hue, sat, val):
    return {
        "warmth": float(hue_to_unit(hue)),        # 0 = deepest red, 1 = most orange
        "brightness": float(val_to_unit(val)),
        "saturation": float(sat_to_unit(sat)),
    }
