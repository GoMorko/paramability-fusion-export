"""Fit the readings of one probe record (a sketch value or a measured reference) over the tried states. Pure.

A series is one number per state, index 0 the state the export started from, None where a state gave none. `problems`
lists why states gave none: `(cause, sizes)` for each state, `sizes` the Fusion names that state changes.
"""
from . import fit
from ..sketch_values.motion import CURVE, SHAPE, TURNS, UNREAD, Affine, Stuck

_PRIORITY = (TURNS, SHAPE, UNREAD)


def moved(a, b):
    return abs(a - b) > fit.TOLERANCE


def movers(varied, series):
    """Sizes whose own state moved the value; when only a state of several sizes moved it, all of those. `varied(at)`
    gives the Fusion names state `at` changes."""
    single, several = [], []
    for at in range(1, len(series)):
        if series[at] is None or not moved(series[at], series[0]):
            continue
        names = varied(at)
        (single if len(names) == 1 else several).extend(sorted(names))
    return list(dict.fromkeys(single or several))


def blocked(problems):
    """The sizes behind the states that could not be read. A state of several sizes adds nothing when a size of it
    already fails alone, since that size stays fixed and the state cannot happen."""
    alone = set().union(*[p[1] for p in problems if len(p[1]) == 1])
    several = [p[1] for p in problems if len(p[1]) != 1 and not p[1] & alone]
    return sorted(alone.union(*several))


def fit_series(values, series, problems, candidates, varied, owner=""):
    """Write into `values` (key to `Affine` or `Stuck`) the fit of each series (key to numbers) over the parameter
    `candidates` (`fit.Column`). A series that does not move writes nothing. With `problems`, the states that failed
    are left out: the value may still follow the other sizes. `owner` names the sketch of an `Affine` or `Stuck`."""
    causes = [c for c in _PRIORITY if any(p[0] == c for p in problems)]
    unreadable = blocked(problems)
    for key, x in series.items():
        found = movers(varied, x)
        if problems:
            rest = fit.fit_value(x, candidates)
            if rest.kind == "affine":
                values[key] = Stuck(unreadable, causes[0], owner, Affine(rest.const, rest.terms, owner))
            elif rest.kind == "const":
                values[key] = Stuck(unreadable, causes[0], owner)
            else:
                values[key] = Stuck(dict.fromkeys(unreadable + found), causes[0], owner)
            continue
        result = fit.fit_value(x, candidates)
        if result.kind == "affine":
            values[key] = Affine(result.const, result.terms, owner)
        elif result.kind == "stuck":
            values[key] = Stuck(found, result.cause or CURVE, owner)
