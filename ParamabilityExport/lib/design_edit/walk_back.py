"""Bring the design back the way a try took it away. A sketch with two solutions that a try left on its other solution
often comes back when the size returns from the other side of its start value, or in small steps, as when the person
drags the value in Fusion. Only parameters change: the caller puts every parameter back to its saved expression after
each attempt (`restore.restore_parameters`) and checks the design. Pure: the store is passed in."""
from ..package.units import internal_to_unit, unit_kind
from .apply import RowBuildError, apply_row_values

ATTEMPTS = 2  # the other side of the start value, then the walk from the value tried
OTHER_SIDE_SHARE = 0.1  # how far past the start value the first attempt goes, as a share of the way the try went
WALK_STEPS = 4  # the walk sets the values this many steps apart, the last step being the start value
SAME_VALUE = 1e-9  # a value this near its start value was not moved by the try


def start_values(store, names, units):
    """{name: value now} in each parameter's own unit, as the values of a row are given. A value that cannot be read
    is left out."""
    out = {}
    for name in names:
        try:
            out[name] = internal_to_unit(store.read_value(name), units[name])
        except Exception:
            continue
    return out


def _whole(value):
    return abs(value - round(value)) <= SAME_VALUE


def _count(units, name, tried, base):
    """True for a count: a parameter without a unit whose start value and tried value are whole numbers. Fusion also
    gives no unit to a ratio such as 1.8, which must step by fractions like a length."""
    return unit_kind(units.get(name)) == "count" and _whole(tried) and _whole(base)


def settings(values, start, units, attempt):
    """The values to set, in turn, for attempt number `attempt` (0: the other side, 1: the walk) of bringing back what a
    try that set `values` (`{name: value}` in each parameter's own unit) moved away from `start`. Only the parameters
    the try moved are set; the start values come after, through the caller's restore. Empty when the try moved
    nothing or the attempt does not exist. A count steps by whole numbers."""
    moved = {n: (v, start[n]) for n, v in values.items() if n in start and abs(v - start[n]) > SAME_VALUE}
    if not moved or attempt not in range(ATTEMPTS):
        return []
    if attempt == 0:
        side = {}
        for name, (tried, base) in moved.items():
            step = OTHER_SIDE_SHARE * (tried - base)
            if _count(units, name, tried, base):
                step = 1.0 if step > 0 else -1.0
            side[name] = base - step
        return [side]
    out = []
    for k in range(1, WALK_STEPS):
        walk = {}
        for name, (tried, base) in moved.items():
            value = tried + (base - tried) * k / WALK_STEPS
            walk[name] = float(round(value)) if _count(units, name, tried, base) else value
        out.append(walk)
    return out


def walk(store, units, steps, baseline=None):
    """Set each of `steps` in turn and rebuild (`apply.apply_row_values`). A step Fusion refuses or cannot build is
    passed over: the walk goes on to the next. Leaves the last step's values set; the caller puts them back."""
    for step in steps:
        try:
            apply_row_values(store, units, step, baseline)
        except RowBuildError:
            continue
