"""Fit a value that no straight formula follows over products of sizes and functions of angle sizes. Pure numbers.

A sketch point at the end of a leg that turns with an angle size moves by `leg * cos(angle)`; a corner set back by a
wall along the half angle moves by `wall * cot(angle / 2)`. Such a value is a sum of terms: each size (as in the
straight fit), the product of two length sizes, and for an angle size `sin`, `cos`, `tan` and `cot` of the angle and
of half the angle, alone and times a length size.

`fit_terms` looks for the smallest set of those terms that gives every measured state of the value within the fit
tolerance: the straight terms of the sizes that moved it, plus up to `MAX_EXTRA` other terms chosen one at a time
(each time the one that leaves the smallest miss), then every term the value can do without is dropped. A set is
accepted only when every measured state follows from the others (`_Problem.checked`): solved without that state,
the sum still gives it. A term only one state shows is then refused, since that state is needed to solve it. When another term in place of a chosen one also gives every state but a different value somewhere inside the
ranges tried (at a size half way to an end, or every size at an end), the states cannot tell them apart and the fit
is refused: more rows are needed.
"""
import math

from .fit import TOLERANCE, _least_squares, _residual, _tidy
from ..sketch_values.motion import FUNCTIONS, Terms, factor_value

MAX_EXTRA = 3
ANGLE = "angle"
_SCALES = (1.0, 0.5)
# A function value whose size passes this is too near a pole (tan near 90 degrees, cot near 0) to be trusted.
_POLE = 1e6


class Size:
    """A free size the value may follow: its Fusion name, whether it is an angle, and its value per state."""

    def __init__(self, name, angle, values):
        self.name = name
        self.angle = angle
        self.values = list(values)


def _linear(size):
    return (("", size.name, 1.0),)


def candidate_terms(sizes):
    """The terms beyond the straight ones: products of two length sizes (a square included), and per angle size each
    function of the angle and of half the angle, alone and times each length size."""
    lengths = [s for s in sizes if not s.angle]
    out = []
    for i, a in enumerate(lengths):
        for b in lengths[i:]:
            out.append((("", a.name, 1.0), ("", b.name, 1.0)))
    for angle in (s for s in sizes if s.angle):
        for function in FUNCTIONS:
            for scale in _SCALES:
                trig = (function, angle.name, scale)
                out.append((trig,))
                out.extend((("", length.name, 1.0), trig) for length in lengths)
    return out


def _column(term, envs):
    """The term's value per state, or None when it is undefined or too near a pole in one of them."""
    out = []
    for env in envs:
        try:
            value = 1.0
            for factor in term:
                value *= factor_value(factor, env)
        except (ZeroDivisionError, ValueError):
            return None
        if not math.isfinite(value) or abs(value) > _POLE:
            return None
        out.append(value)
    return out


class _Problem:
    def __init__(self, x, sizes):
        self.usable = [i for i, v in enumerate(x) if v is not None]
        self.envs = [{s.name: s.values[i] for s in sizes} for i in self.usable]
        xs = [x[i] for i in self.usable]
        self.x0 = xs[0]
        self.dx = [v - xs[0] for v in xs[1:]]
        self._columns = {}

    def column(self, term):
        if term not in self._columns:
            self._columns[term] = _column(term, self.envs)
        return self._columns[term]

    def solve(self, terms, skip=None):
        """`(coefficients, miss)` of the best sum of `terms`, or None when a term is undefined or adds nothing.
        `skip` leaves out one measured state (by number among the states other than the first)."""
        columns = [self.column(t) for t in terms]
        if any(c is None for c in columns):
            return None
        rows = [r for r in range(len(self.dx)) if r != skip]
        deltas = [[c[r + 1] - c[0] for r in rows] for c in columns]
        dx = [self.dx[r] for r in rows]
        if not terms:
            return [], max([abs(d) for d in dx] or [0.0])
        coefficients = _least_squares(deltas, dx)
        if coefficients is None:
            return None
        return coefficients, _residual(coefficients, deltas, dx)

    def checked(self, terms, tol):
        """True when every measured state follows from the others: the sum solved without it is still determined and
        gives it within `tol`. A state the fit needs to be solved at all checks nothing, so it fails here."""
        columns = [self.column(t) for t in terms]
        for skip in range(len(self.dx)):
            found = self.solve(terms, skip)
            if found is None or found[1] > tol:
                return False
            guess = sum(a * (c[skip + 1] - c[0]) for a, c in zip(found[0], columns))
            if abs(guess - self.dx[skip]) > tol:
                return False
        return True

    def changed_states(self, terms):
        """How many measured states other than the first change one of `terms`."""
        columns = [self.column(t) for t in terms]
        return sum(1 for s in range(1, len(self.usable))
                   if any(abs(c[s] - c[0]) > 1e-9 for c in columns))


def _value_at(terms, coefficients, const, env):
    total = const
    for coef, term in zip(coefficients, terms):
        value = coef
        for factor in term:
            value *= factor_value(factor, env)
        total += value
    return total


def _settings(sizes):
    """Size settings inside the ranges tried where two exact fits must agree: each size half way to each end it was
    tried at and at that end, the others at their first value, and every size at its lowest and at its highest."""
    now = {s.name: s.values[0] for s in sizes}
    out = []
    for s in sizes:
        for end in (min(s.values), max(s.values)):
            if abs(end - now[s.name]) > 1e-9:
                out.append(dict(now, **{s.name: (now[s.name] + end) / 2.0}))
                out.append(dict(now, **{s.name: end}))
    out.append({s.name: min(s.values) for s in sizes})
    out.append({s.name: max(s.values) for s in sizes})
    return out


class TermsFit:
    """`kind` is "terms" (with `value`, a `Terms`), "ambiguous" (exact fits that disagree between the states) or
    "none"."""

    def __init__(self, kind, value=None):
        self.kind = kind
        self.value = value


def _const(problem, terms, coefficients):
    return problem.x0 - sum(c * problem.column(t)[0] for c, t in zip(coefficients, terms))


def fit_terms(x, sizes, tol=TOLERANCE, owner=""):
    """The `TermsFit` of `x` (a number per state, None where a state gave none, index 0 the first read) over `sizes`
    (the free sizes that moved it, `Size`)."""
    problem = _Problem(x, sizes)
    if 0 not in problem.usable or len(problem.usable) < 3:
        return TermsFit("none")
    straight = [_linear(s) for s in sizes]
    extra = [t for t in candidate_terms(sizes) if problem.column(t) is not None]
    terms, found = _grow(problem, straight, extra, tol)
    if found is None:
        return TermsFit("none")
    terms, found = _prune(problem, terms, found, tol)
    if problem.changed_states(terms) < len(terms) + 1 or not problem.checked(terms, tol):
        return TermsFit("none")
    coefficients = _tidy(found[0], [[v - c[0] for v in c[1:]] for c in map(problem.column, terms)], problem.dx, tol)
    const = _const(problem, terms, coefficients)
    if _ambiguous(problem, terms, coefficients, const, extra, sizes, tol):
        return TermsFit("ambiguous")
    parts = [(c, t) for c, t in zip(coefficients, terms)]
    return TermsFit("terms", Terms(round(const, 9), parts, owner))


def _grow(problem, straight, extra, tol):
    """The straight terms plus up to `MAX_EXTRA` others, each the one that leaves the smallest miss, until the sum gives
    every state. `(terms, (coefficients, miss))`, or `(terms, None)` when no such sum was found."""
    terms = list(straight)
    found = problem.solve(terms)
    for _ in range(MAX_EXTRA + 1):
        if found is not None and found[1] <= tol:
            return terms, found
        best = None
        for term in extra:
            if term in terms:
                continue
            trial = problem.solve(terms + [term])
            if trial is not None and (best is None or trial[1] < best[1][1]):
                best = (term, trial)
        if best is None:
            break
        terms.append(best[0])
        found = best[1]
    if found is not None and found[1] <= tol:
        return terms, found
    return terms, None


def _prune(problem, terms, found, tol):
    """`terms` without every term the sum gives every state without."""
    changed = True
    while changed:
        changed = False
        for term in list(terms):
            rest = [t for t in terms if t != term]
            trial = problem.solve(rest) if rest else None
            if trial is not None and trial[1] <= tol:
                terms, found, changed = rest, trial, True
                break
    return terms, found


def _ambiguous(problem, terms, coefficients, const, extra, sizes, tol):
    """True when swapping one chosen term for another also gives every state, but a different value at a setting
    inside the ranges tried."""
    settings = _settings(sizes)
    mine = [_value_at(terms, coefficients, const, env) for env in settings]
    for at, term in enumerate(terms):
        for other in extra:
            if other in terms:
                continue
            swapped = terms[:at] + [other] + terms[at + 1:]
            trial = problem.solve(swapped)
            if trial is None or trial[1] > tol:
                continue
            theirs_const = _const(problem, swapped, trial[0])
            try:
                theirs = [_value_at(swapped, trial[0], theirs_const, env) for env in settings]
            except (ZeroDivisionError, ValueError):
                return True
            if any(abs(a - b) > tol for a, b in zip(mine, theirs)):
                return True
    return False
