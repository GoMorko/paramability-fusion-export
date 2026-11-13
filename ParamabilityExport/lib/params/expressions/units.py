"""Length and angle units: the words Fusion reads, the factors to mm and degrees, and the unit powers of a value."""
import math

# Parameter units, and the design's default length unit, in mm.
LENGTH_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8, "um": 0.001}
DEG_PER_RAD = 180.0 / math.pi

# Unit words Fusion reads in an expression, in mm or degrees.
_LENGTH_WORDS = dict(LENGTH_MM, **{
    "millimeter": 1.0, "centimeter": 10.0, "meter": 1000.0, "hm": 100000.0, "micron": 0.001, "µ": 0.001,
    "inch": 25.4, '"': 25.4, "foot": 304.8, "yd": 914.4, "yard": 914.4, "mi": 1609344.0, "mile": 1609344.0,
    "mil": 0.0254, "nauticalMile": 1852000.0,
})
_ANGLE_WORDS = {
    "deg": 1.0, "degree": 1.0, "degrees": 1.0, "°": 1.0, "˚": 1.0, "grad": 0.9,
    "rad": DEG_PER_RAD, "radian": DEG_PER_RAD, "radians": DEG_PER_RAD,
}
_LOOSE_WORDS = {w.lower(): w for w in list(_LENGTH_WORDS) + list(_ANGLE_WORDS)}

# Unit powers of a value: (length, angle).
SCALAR = (0, 0)
LENGTH = (1, 0)
ANGLE = (0, 1)


def unit_factor(word, loose=False):
    """(dim, factor to mm or degrees) for a unit word, or None when it is not a length or angle unit.

    `loose` also matches other letter cases; it is safe only where a unit is expected (after a value).
    """
    if loose and word not in _LENGTH_WORDS and word not in _ANGLE_WORDS:
        word = _LOOSE_WORDS.get(word.lower(), word)
    if word in _LENGTH_WORDS:
        return LENGTH, _LENGTH_WORDS[word]
    if word in _ANGLE_WORDS:
        return ANGLE, _ANGLE_WORDS[word]
    return None


def internal_factor(dim):
    """Factor from Fusion's internal numbers (cm, radians) to mm and degrees, for a value of `dim`."""
    return 10.0 ** dim[0] * DEG_PER_RAD ** dim[1]
