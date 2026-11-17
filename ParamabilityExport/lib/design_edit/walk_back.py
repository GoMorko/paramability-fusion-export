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
ROWS_BACK = 3  # rows run since a sketch last read as at its start that are walked back before the next row, at most
END_TRIES = 16  # walks of one size each after the tries, over all the sketches still off their start, at most
KEPT = 24  # attempts kept for the report (`record`); the count of all attempts is kept apart
KINDS = ("other side", "walk")  # the kind of each attempt number, for the report
AT_CHECK = "steps"  # `at` of an attempt made because a timeline step stayed worse after a row
AT_END = "end"  # `at` of an attempt made after the tries


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
    passed over: the walk goes on to the next. Leaves the last step's values set; the caller puts them back. Returns
    the number of steps passed over."""
    failed = 0
    for step in steps:
        try:
            apply_row_values(store, units, step, baseline)
        except RowBuildError:
            failed += 1
    return failed


def record(row, attempt, steps, at=None):
    """The report entry of one attempt: the key of the row walked back, the kind of the attempt (`KINDS`), the values
    set in turn and, when given, where it ran (`at`: the key of the row about to run, `AT_CHECK` or `AT_END`). The
    caller adds `failed`, the steps Fusion refused or could not build, and `back`, whether the sketches read as at
    their start after it."""
    entry = {"row": row, "kind": KINDS[attempt] if attempt in range(len(KINDS)) else attempt,
             "set": [{name: round(value, 6) for name, value in step.items()} for step in steps]}
    if at is not None:
        entry["at"] = at
    return entry


def distinct_last(rows, limit):
    """The last `limit` of `rows` (each with its `values`), the last first, a row that sets the same values as a later
    one left out: a row run again repeats the values of its first run."""
    seen, out = set(), []
    for row in reversed(rows):
        key = tuple(sorted((row.get("values") or {}).items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out[:limit]


def one_size_moves(rows, start):
    """`(row, {name: value})` for each size that `rows` (each with its `values`, in the order they ran) set away from
    its value in `start`, once per side of that value: the value of the last row that set it on that side. A size
    that only one of the rows moved brings a sketch back as well as a whole row can, and a row that moved several
    sizes does not hide which of them flipped it. The last rows come first: a sketch with two solutions keeps the
    one its last move gave it."""
    seen, out = set(), []
    for row in reversed(rows):
        for name, value in (row.get("values") or {}).items():
            base = start.get(name)
            if base is None or abs(value - base) <= SAME_VALUE or (name, value > base) in seen:
                continue
            seen.add((name, value > base))
            out.append((row, {name: value}))
    return out
