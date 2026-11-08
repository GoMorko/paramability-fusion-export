"""Unit helpers. Fusion stores lengths in cm and angles in radians."""
import math

LENGTH_UNITS = {"mm", "cm", "m", "in", "ft", "um"}
ANGLE_UNITS = {"deg", "rad", "degree", "degrees", "radian", "radians"}
COUNT_UNITS = {"", "unitless", "no units"}

_NORMAL = {"degree": "deg", "degrees": "deg", "radian": "rad", "radians": "rad"}


def unit_kind(unit):
    """Return 'length', 'angle', 'count', or 'unknown' for a unit the tables do not list (never read as a count)."""
    u = (unit or "").strip().lower()
    if u in LENGTH_UNITS:
        return "length"
    if u in ANGLE_UNITS:
        return "angle"
    if u in COUNT_UNITS:
        return "count"
    return "unknown"


def manifest_unit(unit):
    """Return the manifest unit: 'mm', 'deg' or ''."""
    kind = unit_kind(unit)
    return {"length": "mm", "angle": "deg"}.get(kind, "")


def cm_to_mm(value):
    return value * 10.0


def rad_to_deg(value):
    return math.degrees(value)


def to_manifest_value(value, unit):
    """Convert a Fusion internal value (cm, rad, plain) to manifest numbers, rounded to 6 places."""
    kind = unit_kind(unit)
    if kind == "unknown":
        raise ValueError(f"The unit \"{unit}\" is not supported.")
    if kind == "length":
        value = cm_to_mm(value)
    elif kind == "angle":
        value = rad_to_deg(value)
    return round(value, 6)


_PER_CM = {"mm": 10.0, "cm": 1.0, "m": 0.01, "in": 1 / 2.54, "ft": 1 / 30.48, "um": 10000.0}


def internal_to_unit(value, unit):
    """Convert a Fusion internal value (cm, rad, plain) to the number Fusion shows in the given unit.

    A unit outside the tables is returned unconverted; callers must not offer such a parameter (kind 'unsupported').
    """
    kind = unit_kind(unit)
    if kind == "length":
        return value * _PER_CM[(unit or "").strip().lower()]
    if kind == "angle":
        u = _NORMAL.get((unit or "").strip().lower(), (unit or "").strip().lower())
        return value if u == "rad" else rad_to_deg(value)
    return value
