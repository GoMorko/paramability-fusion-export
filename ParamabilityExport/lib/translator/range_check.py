"""What a formula over the sizes does across their ranges.

A rule such as "stays above zero" cannot be settled at each size's own ends: `width - 2 * wall` is positive with
width and wall both at their minimum, and zero with width at its minimum and wall at its maximum. This module tests a
formula at the corners of the ranges of the sizes it reads, so callers ask one question instead of building their own
settings.

    span = sweep(table, "width - 2 * wall", ("width", "wall"))
    span.low, span.high, span.failed       # smallest and largest value found, and whether any setting failed
    span.above(0.0)                        # True when it stays above 0 everywhere (False when any setting failed)

Settings tested (`corners`): the current values, each read size at either end alone with the others at their current
values, and the corners of the ranges. With up to MAX_CORNER_SIZES sizes read, every corner is tested (at most 64
settings). With more, the sample is bounded to MAX_SETTINGS and always the same for the same sizes: all sizes low, all
sizes high, then pairs of sizes at opposite ends and corners picked by a generator seeded from the sizes read.

Arguments:
  table   the size table (`sizes` by recipe name, `size_name` of a Fusion name).
  reads   Fusion names of the sizes the formula reads (`Quantity.reads`); a name that is not a size with a range is
          left at its current value.
  bounds  optional {recipe size name: (low, high)} that replaces the range of a size, for a range under test.
  extra   settings ({recipe size name: value}) tested besides the corners, for example states the probe built.

`size_env` gives the values of every size at a setting; `largest_share` and `smallest_share` find where a rule
starts or stops holding while a range is moved toward its value.
"""
import random
from itertools import combinations, product

from ..params.expressions import ExpressionError, evaluate

MAX_CORNER_SIZES = 6
MAX_SETTINGS = 256
STEPS = 40

_FAILURES = (ExpressionError, ValueError, ZeroDivisionError, OverflowError)


def size_env(table, overrides):
    """Size values by recipe name: the free sizes (with `overrides`), then every derived size."""
    env = {name: size["value"] for name, size in table.sizes.items() if "value" in size}
    env.update(overrides)
    pending = {name: size["expr"] for name, size in table.sizes.items() if "expr" in size}
    while pending:
        progressed = False
        for name, formula in list(pending.items()):
            try:
                env[name] = evaluate(formula, env)
            except ExpressionError:
                continue
            del pending[name]
            progressed = True
        if not progressed:
            raise ExpressionError("A derived size cannot be worked out.")
    return env


class Span:
    """The smallest and largest value of a formula over the settings, and whether any setting could not be worked out.

    `low` and `high` are None when no setting gave a number."""

    def __init__(self, low=None, high=None, failed=False):
        self.low, self.high, self.failed = low, high, failed

    def above(self, limit):
        """True when every value is above `limit` and no setting failed."""
        return not self.failed and (self.low is None or self.low > limit)

    def at_least(self, limit):
        """True when every value is `limit` or more and no setting failed."""
        return not self.failed and (self.low is None or self.low >= limit)

    def at_most(self, limit):
        """True when every value is `limit` or less and no setting failed."""
        return not self.failed and (self.high is None or self.high <= limit)

    def below(self, limit):
        """True when every value is below `limit` and no setting failed."""
        return not self.failed and (self.high is None or self.high < limit)


def _ends(table, reads, bounds):
    """{recipe size name: (low, high)} of the read sizes that have a range."""
    out = {}
    for name in reads:
        size_name = table.size_name(name)
        if size_name is None or size_name in out:
            continue
        if bounds is not None and size_name in bounds:
            out[size_name] = tuple(bounds[size_name])
        elif "min" in table.sizes.get(size_name, {}):
            out[size_name] = (table.sizes[size_name]["min"], table.sizes[size_name]["max"])
    return out


def corners(table, reads, bounds=None):
    """The size settings to test, as [{recipe size name: value}]; the first is the current values."""
    ends = _ends(table, reads, bounds)
    names = list(ends)
    out = [{}]
    for name in names:
        out += [{name: ends[name][0]}, {name: ends[name][1]}]
    if len(names) < 2:
        return out
    if len(names) <= MAX_CORNER_SIZES:
        return out + [dict(zip(names, pick)) for pick in product(*(ends[n] for n in names))]
    out += [{n: ends[n][0] for n in names}, {n: ends[n][1] for n in names}]
    pairs = [{a: x, b: y} for a, b in combinations(names, 2) for x in ends[a] for y in ends[b]]
    room = MAX_SETTINGS - len(out)
    out += pairs[:room // 2]
    rng = random.Random(",".join(names))
    while len(out) < MAX_SETTINGS:
        out.append({n: ends[n][rng.randrange(2)] for n in names})
    return out


def sweep(table, formula, reads, bounds=None, extra=()):
    """The `Span` of `formula` (recipe formula text) over `corners` and the `extra` settings."""
    low = high = None
    failed = False
    for setting in corners(table, reads, bounds) + list(extra):
        try:
            value = evaluate(formula, size_env(table, setting))
        except _FAILURES:
            failed = True
            continue
        low = value if low is None else min(low, value)
        high = value if high is None else max(high, value)
    return Span(low, high, failed)


def largest_share(holds):
    """The largest share t in [0, 1] for which `holds(t)` is true, when it holds up to some share and fails after.

    `holds(0.0)` is assumed true."""
    if holds(1.0):
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(STEPS):
        mid = (low + high) / 2.0
        if holds(mid):
            low = mid
        else:
            high = mid
    return low


def smallest_share(holds):
    """The smallest share t in [0, 1] for which `holds(t)` is true, when it fails up to some share and holds after.

    `holds(1.0)` is assumed true."""
    low, high = 0.0, 1.0
    for _ in range(STEPS):
        mid = (low + high) / 2.0
        if holds(mid):
            high = mid
        else:
            low = mid
    return high
