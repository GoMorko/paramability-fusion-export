"""Fit the readings of one probe record (a sketch value or a measured reference) over the tried states. Pure.

A series is one number per state, index 0 the state the export started from, None where a state gave none. `problems`
lists why states gave none: `(cause, sizes)` for each state, `sizes` the Fusion names that state changes.
"""
from . import fit, terms
from ..sketch_values.motion import CURVE, SHAPE, TURNS, UNREAD, Affine, Stuck, Terms

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
    are left out: the value may still follow the other sizes. Its `rest` is fitted over the states that keep the
    blamed sizes at their value now, as it holds once they are fixed. `owner` names the sketch of an `Affine` or
    `Stuck`."""
    causes = [c for c in _PRIORITY if any(p[0] == c for p in problems)]
    unreadable = blocked(problems)
    held = set(unreadable)
    for key, x in series.items():
        found = movers(varied, x)
        if problems:
            rest = fit.fit_value([x[0]] + [None if varied(at) & held else x[at] for at in range(1, len(x))],
                                 candidates)
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
            values[key] = (_curved_fit(x, candidates, found, owner, varied)
                           or _narrowed(x, candidates, varied, found, owner)
                           or Stuck(found, result.cause or CURVE, owner))


def _curved_fit(x, candidates, found, owner, varied):
    """The `Terms` fit of a value over the free sizes that moved it and their partners (`probe.terms`), or None when
    it has none that the states check."""
    by_name = {c.name: c for c in candidates if c.kind}
    if not found or any(name not in by_name for name in found):
        return None

    def size(name):
        return terms.Size(name, by_name[name].kind == terms.ANGLE, by_name[name].values)

    result = terms.fit_terms(x, [size(n) for n in found], owner=owner,
                             partners=[size(n) for n in partners(x, by_name, varied, found)])
    return result.value if result.kind == "terms" else None


def partners(x, by_name, varied, found):
    """The free sizes that move the value only together with an angle that moved it: in a state that changes the
    angle and that size alone, the value differs from a state that changes only the angle, to the same value. At its
    value now the turn may hide such a size (a leg lying along the line it moves), so its own states did not move
    the value."""
    angles = [n for n in found if by_name[n].kind == terms.ANGLE]
    out = []
    for at in range(1, len(x)):
        names = varied(at)
        pair = [n for n in names if n in angles]
        if x[at] is None or len(names) != 2 or len(pair) != 1:
            continue
        angle = by_name[pair[0]]
        other = next(n for n in names if n != pair[0])
        if other in found or other in out or other not in by_name:
            continue
        alone = [x[b] for b in range(1, len(x)) if x[b] is not None and varied(b) == {angle.name}
                 and abs(angle.values[b] - angle.values[at]) <= 1e-9]
        if alone and moved(x[at], alone[0]):
            out.append(other)
    return out


def _alone(x, varied, column):
    """`[(size value, reading)]` of the value now and of every state that changes only `column`'s size."""
    out = [(column.values[0], x[0])]
    for at in range(1, len(x)):
        if x[at] is not None and varied(at) == {column.name}:
            out.append((column.values[at], x[at]))
    return out


def _on_a_line(points):
    """False when three or more readings of one size alone do not lie on one straight line; True for fewer."""
    if len(points) < 3:
        return True
    (s0, v0), rest = points[0], points[1:]
    slopes = [(v - v0) / (s - s0) for s, v in rest if abs(s - s0) > 1e-12]
    reach = max(abs(s - s0) for s, _ in rest)
    return max(slopes) - min(slopes) <= fit.TOLERANCE / max(reach, 1e-12) * 2


def curved_sizes(x, candidates, varied, found):
    """The sizes in `found` (they moved the value) whose own readings, with every other size at its value now, do not
    lie on a straight line: a move along a curve that only they make."""
    by_name = {c.name: c for c in candidates}
    return [name for name in found if name in by_name and not _on_a_line(_alone(x, varied, by_name[name]))]


def _narrowed(x, candidates, varied, found, owner):
    """A `Stuck` that blames only the sizes that move the value along a curve on their own, with the formula the
    value follows over the other sizes once those are fixed (`rest`): fitted over the states that keep the curved
    sizes at their value now, and accepted only as exact as any other fit (with a state to check it). None when no
    size is curved on its own, or the rest does not fit: then every size that moved the value is blamed."""
    curved = curved_sizes(x, candidates, varied, found)
    if not curved:
        return None
    kept = [x[0]] + [None if varied(at) & set(curved) else x[at] for at in range(1, len(x))]
    rest = fit.fit_value(kept, candidates)
    if rest.kind == "affine":
        return Stuck(curved, CURVE, owner, Affine(rest.const, rest.terms, owner))
    if rest.kind == "const":
        return Stuck(curved, CURVE, owner)
    return None


def _reads(value):
    if isinstance(value, Stuck):
        return list(value.movers) + list(value.rest.terms if value.rest is not None else ())
    if isinstance(value, Terms):
        return list(value.names())
    return list(getattr(value, "terms", None) or ())


def curve_sizes(values):
    """`(curved, partners)` of the fitted `values` (key to `Affine`, `Terms` or `Stuck`): the Fusion names of the sizes
    that move a value along a curve on their own (a `Stuck` with `rest` blames them, or a `Terms` value reads them
    through an angle function), and the other sizes of those values, then of every value of the same sketches. A
    partner of a turn may move no value of its own at the sizes now (a leg lying along the line it moves), but it moves
    some other value of the sketch: a corner at its end."""
    curved, partners, sketches = [], [], set()
    for value in values.values():
        if isinstance(value, Stuck) and value.cause == CURVE and value.rest is not None:
            curved.extend(value.movers)
        elif isinstance(value, Terms):
            curved.extend(f[1] for _, factors in value.parts for f in factors if f[0])
        else:
            continue
        partners.extend(_reads(value))
        sketches.add(value.sketch)
    for value in values.values():
        if getattr(value, "sketch", "") in sketches:
            partners.extend(_reads(value))
    curved = list(dict.fromkeys(curved))
    return curved, [n for n in dict.fromkeys(partners) if n not in curved]
