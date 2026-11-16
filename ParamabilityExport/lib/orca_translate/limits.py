"""How far an Orca variable may move before a step that Orca would fail on stops fitting.

Orca variables have no ranges, and Orca stops the whole rebuild on a round, chamfer or thread it cannot make. Such a
step is checked at the current sizes. `ranges` then finds, for each free variable that the step's bound fields read,
how far the variable may go down and up (the other variables keep their values) while the check still passes, and
`tell` adds it to that parameter's line, so the person knows where the step stops fitting.

Some steps Orca builds wrong past a limit, without an error (an extrude "To" a face that a variable moves past its
start, a taper that shrinks its outline to nothing, a swept outline that grows into its path). `guard` tells those
limits the same way, also a limit far from the current value, and where it cannot tell one it unbinds the fields, so
they keep their numbers. `tell` leaves out a limit far from the current value: Orca stops with an error there.

Each told limit is a `Limit`: the words on the parameter's line, with the numbers they give.

A field that sizes a shape (`POSITIVE`: a sketch width, height or radius, a round, a hole, a thickness, a thread)
never fits at zero or below, whatever the step's check says, and the lower limit of a variable that drives one is
told even when it is small: the person sees where the shape stops, never a limit below zero.

The search walks out from the current value in growing steps until the check fails, then halves the gap. The
growing steps can jump over a band where the check fails, so the search then tests evenly spaced values on each side
between the current value and the end it found (for a side with no end, up to `FAR` times the current value away)
and pulls the end in to the first value that fails. It finds the nearest value each way where the step stops
fitting, as far as these tests show, and assumes the step fits everywhere between.
"""
import math
import re

from ..design_model.dimension_sizes import size_env
from ..params.expressions.errors import ExpressionError
from ..params.size_table import FREE
from .formulas import orca_value, variable_values

# Steps out from the current value: the first is this share of it (or of 1 when it is 0), each next one twice as
# long, at most this many.
_FIRST_STEP = 0.25
_STEPS = 16
# The gap to a limit is halved until it is this share of the value (at least of 1), at most `_HALVINGS` times: fine
# enough that a limit on a round number is told as that number (`_shown`).
_HALVINGS = 40
_FINE = 1e-9
# Evenly spaced values tested on each side, between the current value and the end the walk found.
_SAMPLES = 32
# `tell` shows a limit only within this factor of the current value.
FAR = 10.0
# A lower limit this close to zero says only "keep it above zero", which a size always is.
_AT_ZERO = 1e-3
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Fields that size a shape: at zero or below the shape vanishes or turns inside out, so a value there never fits, and
# the lower limit of a variable that drives one is told even when it is small (it is where the shape stops).
POSITIVE = frozenset((
    "width", "height", "radius", "dressup_size", "hole_diameter", "hole_depth", "hole_cbore_diameter",
    "hole_cbore_depth", "hole_csink_diameter", "shell_thickness", "thicken_thickness", "rib_thickness",
    "thread_diameter", "thread_radius", "thread_pitch", "thread_height", "thread_depth", "helix_pitch",
    "helix_radius", "plane_u_size", "plane_v_size",
))


def _free(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _reads(variables, texts):
    """The variables the formulas `texts` read, with every variable those read."""
    found, todo = set(), [n for t in texts for n in _NAME.findall(t or "")]
    while todo:
        name = todo.pop()
        if name in variables and name not in found:
            found.add(name)
            todo.extend(_NAME.findall(variables[name] or ""))
    return found


def _numbers(fields, values):
    out = []
    for feature, field in fields:
        text = feature.expr.get(field)
        out.append(orca_value(text, values) if text else float(getattr(feature, field)))
    return out


def _shaped(fields, numbers):
    """True when every field that sizes a shape (`POSITIVE`) stays above zero."""
    return all(n > 0 for (_, field), n in zip(fields, numbers) if field in POSITIVE)


def _sizing(variables, fields):
    """The variables that a field sizing a shape (`POSITIVE`) reads."""
    return _reads(variables, [feature.expr.get(field) for feature, field in fields if field in POSITIVE])


def ranges(ctx, fields, ok):
    """`{Orca variable: (low, high)}` for each free variable the bound `fields` ((feature, field name) pairs) read:
    the values, around the current one, at which `ok(numbers of the fields)` still holds; None for a side with no
    limit found. Variables the check does not limit are left out."""
    return _search(ctx, fields, ok)[0]


def _search(ctx, fields, ok):
    """`(ranges, unsure)`: the ranges as `ranges` gives them, and the free variables read whose check does not hold
    (or cannot be worked out) at the current values. A value that takes a field sizing a shape to zero or below
    does not fit (`_shaped`), whatever `ok` says."""
    variables = ctx.variables()
    texts = [feature.expr.get(field) for feature, field in fields]
    out, unsure = {}, []
    for name in sorted(_reads(variables, texts)):
        current = _free(variables[name])
        if current is None:
            continue

        def fits(x, name=name):
            try:
                values = variable_values(dict(variables, **{name: repr(float(x))}))
                numbers = _numbers(fields, values)
                return _shaped(fields, numbers) and bool(ok(numbers))
            except (ExpressionError, ArithmeticError, ValueError):
                return False

        if not fits(current):
            unsure.append(name)
            continue
        found = bounds(fits, current)
        if found != (None, None):
            out[name] = found
    return out, unsure


def bounds(fits, current):
    """`(low, high)`: the last values below and above `current` at which `fits(value)` holds, None for a side where
    it holds as far as the search looks. `fits(current)` must hold."""
    found = [_edge(fits, current, -1), _edge(fits, current, 1)]
    reach = FAR * (abs(current) or 1.0)
    for n, sign in enumerate((-1, 1)):
        end = found[n] if found[n] is not None else current + sign * reach
        good = current
        for k in range(1, _SAMPLES + 1):
            value = current + (end - current) * k / _SAMPLES
            if not fits(value):
                found[n] = _halve(fits, good, value)
                break
            good = value
    return found[0], found[1]


def tell_found(ctx, found):
    """Add the limits `{Orca variable: (low, high)}` to the parameters' lines, also those far from the current value,
    for a step Orca builds wrong, without an error, past them. Returns `({Orca variable: Limit}, [Orca variables
    without a parameter line])`."""
    return _tell(ctx, found, False)


def _edge(fits, current, sign):
    """The last value from `current` toward `sign` at which `fits` holds, or None when it holds as far as looked."""
    step = abs(current) * _FIRST_STEP or _FIRST_STEP
    good = current
    for _ in range(_STEPS):
        trial = good + sign * step
        if not fits(trial):
            return _halve(fits, good, trial)
        good, step = trial, step * 2.0
    return None


def _halve(fits, good, bad):
    """The last value from `good` (where `fits` holds) toward `bad` (where it fails) at which it holds."""
    for _ in range(_HALVINGS):
        if abs(bad - good) <= _FINE * max(1.0, abs(good)):
            break
        mid = (good + bad) / 2.0
        if fits(mid):
            good = mid
        else:
            bad = mid
    return good


def _shown(value, sign):
    """A limit as a short number, rounded toward the side where the step still fits."""
    digits = 2 if abs(value) < 10 else 1
    scale = 10 ** digits
    value = round(value, 6)  # a limit found a hair past a round number is that number
    number = (math.floor if sign > 0 else math.ceil)(value * scale) / scale
    return ("%.*f" % (digits, number)).rstrip("0").rstrip(".")


class Limit(str):
    """The words of a told limit ("keep Round under 4.5 mm"), with the Orca `variable` and the `low` and `high`
    numbers they give (rounded as told; None for a side with no limit told)."""

    def __new__(cls, text, variable, low, high):
        made = super().__new__(cls, text)
        made.variable, made.low, made.high = variable, low, high
        return made


def words(name, low, high, current, unit="", near=True, floor=False):
    """The `Limit` for a range around `current`, such as "keep Round under 4.5 mm", or None when it says nothing.
    With `near` (a step Orca stops on with an error), a lower limit at zero or below is told only for a value below
    zero (a taper angle), and a limit far from the current value (a lower one under a tenth of it, a higher one over
    ten times it) is not worth telling and is not shown. Without `near` (a step Orca builds wrong past the limit),
    every limit is told except a lower one where the value reaches zero, which a size never goes below: an offset
    that may go below zero is told how far. With `floor` (a size Orca cannot make near zero, such as a round), a
    lower limit above zero is always told, however small."""
    kept = low if floor and low is not None and low > 0 else None
    if near and low is not None and not (low > _AT_ZERO or current < 0):
        low = None
    if not near and low is not None and abs(low) <= _AT_ZERO:
        low = None
    if near:
        low = low if low is not None and abs(current) / FAR < abs(low) < abs(current) * FAR else None
        high = high if high is not None and high < abs(current) * FAR else None
    if low is None:
        low = kept
    low_text = _shown(low, -1) if low is not None else None
    high_text = _shown(high, 1) if high is not None else None
    if low_text is not None and high_text is not None:
        text = "keep %s between %s and %s%s" % (name, low_text, high_text, unit)
    elif high_text is not None:
        text = "keep %s under %s%s" % (name, high_text, unit)
    elif low_text is not None:
        text = "keep %s over %s%s" % (name, low_text, unit)
    else:
        return None
    return Limit(text, name, None if low_text is None else float(low_text),
                 None if high_text is None else float(high_text))


def tell(ctx, fields, ok, floor=False):
    """Work out `ranges` and add each limit near the current value to the line of the parameter behind its variable
    (`ctx.follows`). For a step Orca stops on with an error past the limit; `floor` as for `words`. Returns
    `{Orca variable: Limit}`."""
    return _tell(ctx, _search(ctx, fields, ok)[0], True, floor, _sizing(ctx.variables(), fields))[0]


def tell_sizes(ctx, fields, names, ok):
    """`tell` with `floor`, for a check that also reads sizes the bound `fields` do not: each free size that the
    fields read or that `names` (Fusion names) holds is walked (the others kept), and `ok(numbers of the fields, size
    values)` gets the size values as `dimension_sizes.size_env` gives them. Returns `({Orca variable: Limit},
    [Orca variables whose limits cannot be told: the check does not hold at the current values, or the variable
    has no parameter line])`."""
    if ctx.table is None:
        return {}, []
    variables = ctx.variables()
    wanted = _reads(variables, [feature.expr.get(field) for feature, field in fields])
    found, unsure = {}, []
    for entry in ctx.table.entries:
        name = ctx.names.get(entry.size_name) if entry.size_name else None
        if entry.state != FREE or name is None or not (name in wanted or entry.name in names):
            continue

        def fits(x, entry=entry, name=name):
            try:
                values = variable_values(dict(variables, **{name: repr(float(x))}))
                numbers = _numbers(fields, values)
                return _shaped(fields, numbers) and bool(ok(numbers, size_env(ctx.table, {entry.name: x})))
            except (ExpressionError, ArithmeticError, ValueError):
                return False

        if not fits(entry.value):
            unsure.append(name)
            continue
        limit = bounds(fits, entry.value)
        if limit != (None, None):
            found[name] = limit
    told, missing = _tell(ctx, found, True, True)
    return told, unsure + missing


def lineless(ctx, found):
    """The Orca variables of `found` that have no parameter line to tell their limits on."""
    if ctx.table is None:
        return list(found)
    lines = {ctx.names.get(e.size_name) for e in ctx.table.entries if e.size_name}
    return [name for name in found if name not in lines]


def _tell(ctx, found, near, floor=False, sizing=()):
    """`({Orca variable: Limit}, [Orca variables with a limit that has no parameter line])`. `floor` as for `words`,
    for every variable or for those in `sizing` (variables that size a shape)."""
    told, untold = {}, []
    if ctx.table is None:
        return told, untold
    by_variable = {ctx.names.get(e.size_name): e for e in ctx.table.entries if e.size_name}
    variables = ctx.variables()
    for name, (low, high) in found.items():
        entry = by_variable.get(name)
        if entry is None:
            untold.append(name)
            continue
        unit = {"length": " mm", "angle": " degrees"}.get(entry.kind, "")
        text = words(name, low, high, _free(variables.get(name)) if name in variables else entry.value, unit, near,
                     floor or name in sizing)
        if text is None:
            continue
        where = ctx.follows.setdefault(entry.name, [])
        if text not in where:
            where.append(text)
        told[name] = text
    return told, untold


def guard(ctx, fields, ok, reason):
    """`tell` for a step that Orca builds wrong, without an error, where `ok` fails. `fields` are (feature, field
    name, where) triples, `where` as the field was bound (`Context.bind`). A variable whose limit cannot be told (the
    check fails at the current values, or the variable has no parameter line) is not left to chance: every field
    that reads it is unbound and keeps its number, and the sizes it read get `reason`. Returns `{Orca variable:
    Limit}`. Every limit found is told, also one far from the current value."""
    pairs = [(f, n) for f, n, _ in fields]
    found, unsure = _search(ctx, pairs, ok)
    told, untold = _tell(ctx, found, False, sizing=_sizing(ctx.variables(), pairs))
    loose = set(unsure) | set(untold)
    if not loose:
        return told
    variables = ctx.variables()
    for feature, field, where in fields:
        text = feature.expr.get(field)
        if text is None or not loose & _reads(variables, [text]):
            continue
        del feature.expr[field]
        for record in [b for b in ctx.bound if b["feature"] == feature.name and b["field"] == field]:
            ctx.bound.remove(record)
            for name in record["reads"]:
                if where in ctx.follows.get(name, []):
                    ctx.follows[name].remove(where)
                    if not ctx.follows[name]:
                        del ctx.follows[name]
            ctx.doubt(record["reads"], reason)
    return {name: text for name, text in told.items() if name not in loose}
