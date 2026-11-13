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

`middles` gives settings inside the ranges (every size at its middle, alone or with the others at their ends) for a rule
that is not a formula and can fail between the ends. `size_env` gives the values of every size at a setting; `largest_share` finds where a rule stops holding while a range
is moved toward its value.

A formula that is more than sums and products (`abs`, a division by a size, `min`, `max`, `mod`, a choice, a
function such as `sin` or `sqrt`) can have its extreme or its failure inside a range. For such a formula `sweep`
also tests inner settings (`inner_settings`): each read size at INNER_FRACTIONS of its range, with the other sizes at
every combination of their ends and inner values when at most MAX_GRID_SIZES sizes are read (at most 125 settings), and
with the others at their current values, all low or all high when more are read (at most MAX_INNER settings). Then
it looks for the places where a term of the formula changes sign (a divisor, the argument of `abs`, `sqrt` or `ln`, the
two sides of a comparison, the difference of two `min` or `max` arguments): between two neighbouring inner values with
different signs, bisection finds the zero, and the settings on both sides of it are tested too (at most MAX_ZEROS).
A divisor that changes sign inside a range counts as a failed setting.
"""
import random
from itertools import combinations, product

from ..params.expressions.errors import ExpressionError
from ..params.expressions.evaluation import _eval, evaluate
from ..params.expressions.formula import parse_formula

MAX_CORNER_SIZES = 6
MAX_SETTINGS = 256
MAX_GRID_SIZES = 3
MAX_INNER = 256
MAX_ZEROS = 64
MAX_TERMS = 8
INNER_FRACTIONS = (0.25, 0.5, 0.75)
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


def middles(table, reads, bounds=None):
    """Settings with sizes inside their ranges, as [{recipe size name: value}]: every read size at the middle of its
    range together, and each one at its middle with the others all low, all high or at their current values. For a
    rule that can fail between the ends of the ranges and hold at both."""
    ends = _ends(table, reads, bounds)
    names = list(ends)
    middle = {n: (lo + hi) / 2.0 for n, (lo, hi) in ends.items()}
    if not names:
        return []
    out = [dict(middle)]
    for n in names:
        out.append({n: middle[n]})
        if len(names) > 1:
            out += [dict({m: ends[m][side] for m in names}, **{n: middle[n]}) for side in (0, 1)]
    return out


_CHECKED_ARGUMENTS = {"abs": (0,), "sign": (0,), "sqrt": (0,), "ln": (0,), "log": (0,)}
_DIVISORS = {"mod": 1}


def _terms(node, out):
    """Collect `(term node, is a divisor)` of the sub-expressions whose sign matters, and return whether the tree is
    more than sums and products of sizes."""
    kind = node[0]
    nonlinear = kind in ("cond", "cmp", "logic", "not", "call")
    children = []
    if kind == "bin":
        if node[1] == "/":
            nonlinear = nonlinear or _reads(node[3])
            out.append((node[3], True))
        children = node[2:]
    elif kind == "neg":
        children = node[1:]
    elif kind == "not":
        out.append((node[1], False))
        children = node[1:]
    elif kind == "cond":
        out.append((node[1], False))
        children = node[1:]
    elif kind == "logic":
        children = node[2:]
    elif kind == "cmp":
        out.append((("bin", "-", node[2], node[3]), False))
        children = node[2:]
    elif kind == "call":
        name, args = node[1], node[2]
        for at in _CHECKED_ARGUMENTS.get(name, ()):
            if at < len(args):
                out.append((args[at], False))
        if name in _DIVISORS and len(args) > _DIVISORS[name]:
            out.append((args[_DIVISORS[name]], True))
        if name in ("min", "max", "clamp"):
            out.extend((("bin", "-", a, b), False) for a, b in zip(args, args[1:]))
        children = args
    found = nonlinear
    for child in children:
        found = _terms(child, out) or found
    return found


def _reads(node):
    if node[0] == "name":
        return True
    return any(_reads(c) for c in node[1:] if isinstance(c, tuple)) or \
        any(_reads(x) for c in node[1:] if isinstance(c, list) for x in c)


def value_of(tree, env):
    """The number of a parsed formula (`parse_formula`) at `env`, for a rule worked out at many settings."""
    value = _eval(tree, env)
    if value != value or value in (float("inf"), float("-inf")):
        raise ExpressionError("The formula does not give a number.")
    return value


def _inner_values(ends):
    return {n: [lo + f * (hi - lo) for f in INNER_FRACTIONS] for n, (lo, hi) in ends.items()}


def inner_settings(table, reads, bounds=None):
    """The inner size settings of `sweep`, as [{recipe size name: value}] (see the module text for the bounds)."""
    ends = _ends(table, reads, bounds)
    names = list(ends)
    inner = _inner_values(ends)
    if not names:
        return []
    if len(names) <= MAX_GRID_SIZES:
        values = [list(ends[n]) + inner[n] for n in names]
        return [dict(zip(names, pick)) for pick in product(*values)]
    low, high = {n: ends[n][0] for n in names}, {n: ends[n][1] for n in names}
    out = []
    for n in names:
        for x in inner[n]:
            for rest in ({}, low, high):
                out.append(dict(rest, **{n: x}))
    return out[:MAX_INNER]


def _crossings(table, tree_terms, ends):
    """(settings next to a sign change of a term, whether a divisor changed sign)."""
    settings, divisor_flips = [], False
    sizes = list(ends)
    low, high = {n: ends[n][0] for n in sizes}, {n: ends[n][1] for n in sizes}
    for term, is_divisor in tree_terms[:MAX_TERMS]:
        for n in sizes:
            lo, hi = ends[n]
            xs = [lo] + [lo + f * (hi - lo) for f in INNER_FRACTIONS] + [hi]
            for rest in ({}, low, high):
                try:
                    signs = [_sign(value_of(term, size_env(table, dict(rest, **{n: x})))) for x in xs]
                except _FAILURES:
                    continue
                for (x0, s0), (x1, s1) in zip(zip(xs, signs), zip(xs[1:], signs[1:])):
                    if s0 * s1 >= 0:
                        continue
                    divisor_flips = divisor_flips or is_divisor
                    if len(settings) < 2 * MAX_ZEROS:
                        a, b = _bisect(table, term, dict(rest), n, x0, x1, s0)
                        settings += [dict(rest, **{n: a}), dict(rest, **{n: b})]
    return settings, divisor_flips


def _sign(x):
    return (x > 0) - (x < 0)


def _bisect(table, term, rest, name, x0, x1, s0):
    """The two ends of the last bracket around the zero of `term` along one size, between `x0` and `x1` where the
    signs differ (`s0` at `x0`)."""
    for _ in range(STEPS):
        mid = (x0 + x1) / 2.0
        try:
            s = _sign(value_of(term, size_env(table, dict(rest, **{name: mid}))))
        except _FAILURES:
            break
        if s == 0:
            return mid, mid
        if s == s0:
            x0 = mid
        else:
            x1 = mid
    return x0, x1


def sweep(table, formula, reads, bounds=None, extra=()):
    """The `Span` of `formula` (recipe formula text) over `corners`, `inner_settings` and `sign changes` for a
    formula that needs them, and the `extra` settings."""
    try:
        tree = parse_formula(formula)
    except ExpressionError:
        return Span(failed=True)
    terms = []
    nonlinear = _terms(tree, terms)
    settings = corners(table, reads, bounds)
    failed = False
    if nonlinear:
        settings += inner_settings(table, reads, bounds)
        ends = _ends(table, reads, bounds)
        if ends and terms:
            found, flipped = _crossings(table, terms, ends)
            settings += found
            failed = flipped
    low = high = None
    for setting in settings + list(extra):
        try:
            value = value_of(tree, size_env(table, setting))
        except _FAILURES:
            failed = True
            continue
        low = value if low is None else min(low, value)
        high = value if high is None else max(high, value)
    return Span(low, high, failed)


def largest_share(holds, steps=STEPS):
    """The largest share t in [0, 1] for which `holds(t)` is true, when it holds up to some share and fails after,
    found by `steps` halvings.

    `holds(0.0)` is assumed true."""
    if holds(1.0):
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(steps):
        mid = (low + high) / 2.0
        if holds(mid):
            low = mid
        else:
            high = mid
    return low
