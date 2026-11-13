"""The app's functions as they work on numbers: degree based trigonometry, `mod`, `round` and the rest."""
import math


def _quarter_turns(x):
    """x degrees as a whole number of quarter turns (0 to 3), or None."""
    q = x / 90.0
    return int(q) % 4 if q == int(q) else None


def _sin(x):
    q = _quarter_turns(x)
    return (0.0, 1.0, 0.0, -1.0)[q] if q is not None else math.sin(math.radians(x))


def _cos(x):
    q = _quarter_turns(x)
    return (1.0, 0.0, -1.0, 0.0)[q] if q is not None else math.cos(math.radians(x))


def _tan(x):
    q = _quarter_turns(x)
    if q is None:
        return math.tan(math.radians(x))
    if q % 2:
        raise ValueError("tan of a quarter turn has no value")
    return 0.0


def _mod(a, b):
    if b == 0:
        raise ValueError("mod by zero")
    return a - b * math.floor(a / b)


# App function name -> (argument count, None for 2 or more; function over the argument list)
APP_FUNCTIONS = {
    "abs": (1, lambda a: abs(a[0])),
    "acos": (1, lambda a: math.degrees(math.acos(a[0]))),
    "asin": (1, lambda a: math.degrees(math.asin(a[0]))),
    "atan": (1, lambda a: math.degrees(math.atan(a[0]))),
    "atan2": (2, lambda a: math.degrees(math.atan2(a[0], a[1]))),
    "ceil": (1, lambda a: math.ceil(a[0])),
    "clamp": (3, lambda a: min(max(a[0], a[1]), a[2])),
    "cos": (1, lambda a: _cos(a[0])),
    "exp": (1, lambda a: math.exp(a[0])),
    "floor": (1, lambda a: math.floor(a[0])),
    "ln": (1, lambda a: math.log(a[0])),
    "log": (1, lambda a: math.log10(a[0])),
    "max": (None, max),
    "min": (None, min),
    "mod": (2, lambda a: _mod(a[0], a[1])),
    "pi": (0, lambda a: math.pi),
    "pow": (2, lambda a: math.pow(a[0], a[1])),
    "round": (1, lambda a: math.floor(a[0] + 0.5)),
    "sign": (1, lambda a: (a[0] > 0) - (a[0] < 0)),
    "sin": (1, lambda a: _sin(a[0])),
    "sqrt": (1, lambda a: math.sqrt(a[0])),
    "tan": (1, lambda a: _tan(a[0])),
}
