"""Fit one written value as an exact affine formula over parameter columns. Pure numbers.

States are aligned lists, index 0 the state the export started from. A value `x` is `const + sum(a_j * c_j)` over at
most four columns `c_j`. The fit is exact only when every state agrees within the tolerance and the columns moved
in enough states to tell a line from a coincidence.
"""
import itertools
import math

from ..geometry import tolerances
from ..sketch_values.motion import CURVE, UNTRIED

# The name the export code reads the fit tolerance by.
TOLERANCE = tolerances.FIT_TOLERANCE
MAX_COLUMNS = 4
MAX_CANDIDATES = 12
SNAP_DENOMINATOR = 24
SNAP_TOLERANCE = 1e-6
_DEFICIENT = 1e-9


class Column:
    """A parameter's value per state. `rank` orders the candidates: lower is preferred. `kind` is the size kind
    (length, angle, count) of a free size, else empty."""

    def __init__(self, name, rank, values, kind=""):
        self.name = name
        self.rank = rank
        self.values = list(values)
        self.kind = kind


class Result:
    """`kind` is "const" (`const` only), "affine" (`const` and `terms`, name to coefficient) or "stuck" (`cause`)."""

    def __init__(self, kind, const=0.0, terms=None, cause=""):
        self.kind = kind
        self.const = const
        self.terms = terms or {}
        self.cause = cause


def _moves(values, tol):
    return any(abs(v - values[0]) > tol for v in values[1:])


def _same(a, b):
    return all(abs(x - y) <= _DEFICIENT * (1.0 + abs(x)) for x, y in zip(a, b))


def _candidates(columns, usable, moving=()):
    """Columns that change in some usable state, equal ones merged into the best ranked, at most `MAX_CANDIDATES`.

    `moving` are the states where the value moved. A column that changes in one of them goes before every column that
    does not, whatever its rank: with many sizes tried, the columns that cannot explain the move would otherwise take
    the places and leave a value that follows its sizes exactly without a fit."""

    def order(column):
        explains = any(abs(column.values[i] - column.values[0]) > _DEFICIENT for i in moving)
        return (not explains, column.rank)

    out = []
    for column in sorted(columns, key=order):
        values = [column.values[i] for i in usable]
        if not _moves(values, _DEFICIENT):
            continue
        if any(_same(values, other[1]) for other in out):
            continue
        out.append((column, values))
    return out[:MAX_CANDIDATES]


def least_squares(vectors, y):
    """Coefficients `a` with `sum(a_j * vectors[j])` nearest to `y` (modified Gram Schmidt), or None when a vector
    adds nothing the earlier ones have not."""
    q, r = [], []
    for j, v in enumerate(vectors):
        w = list(v)
        norm0 = math.sqrt(sum(t * t for t in w))
        row = [0.0] * len(vectors)
        for i, qi in enumerate(q):
            row[i] = sum(a * b for a, b in zip(qi, w))
            w = [a - row[i] * b for a, b in zip(w, qi)]
        norm = math.sqrt(sum(t * t for t in w))
        if norm0 == 0.0 or norm <= _DEFICIENT * norm0:
            return None
        row[j] = norm
        q.append([t / norm for t in w])
        r.append(row)
    rhs = [sum(a * b for a, b in zip(qi, y)) for qi in q]
    coefficients = [0.0] * len(vectors)
    for j in range(len(vectors) - 1, -1, -1):
        rest = sum(r[k][j] * coefficients[k] for k in range(j + 1, len(vectors)))
        coefficients[j] = (rhs[j] - rest) / r[j][j]
    return coefficients


def fit_residual(coefficients, deltas, dx):
    return max(abs(d - sum(a * col[s] for a, col in zip(coefficients, deltas))) for s, d in enumerate(dx))


def _snap(a):
    nearest = round(a * SNAP_DENOMINATOR) / SNAP_DENOMINATOR
    return nearest if abs(a - nearest) <= SNAP_TOLERANCE else round(a, 9)


def snap_coefficients(coefficients, deltas, dx, tol):
    """Coefficients on the nearest k / 24 when that keeps every state within tolerance, else rounded to 9 digits."""
    snapped = [_snap(a) for a in coefficients]
    if fit_residual(snapped, deltas, dx) <= tol:
        return snapped
    return [round(a, 9) for a in coefficients]


def fit_value(x, columns, tol=tolerances.FIT_TOLERANCE):
    """Fit `x` (a number per state, None for a state without it) over `columns`.

    Returns a `Result`: "const" when it moves less than `tol` everywhere, "affine" for the first exact subset of
    columns (fewest columns, then best ranks), else "stuck" with cause "untried" when a subset was exact but the
    columns moved in too few states, or "curve".
    """
    usable = [i for i, v in enumerate(x) if v is not None]
    if 0 not in usable:
        return Result("stuck", cause=CURVE)
    xs = [x[i] for i in usable]
    if not _moves(xs, tol):
        return Result("const", const=x[0])
    dx = [v - xs[0] for v in xs[1:]]
    candidates = _candidates(columns, usable, [i for i in usable[1:] if abs(x[i] - x[0]) > tol])
    too_few = False
    for size in range(1, MAX_COLUMNS + 1):
        for subset in itertools.combinations(candidates, size):
            deltas = [[v - vals[0] for v in vals[1:]] for _, vals in subset]
            a = least_squares(deltas, dx)
            if a is None or fit_residual(a, deltas, dx) > tol:
                continue
            changed = sum(1 for s in range(len(dx)) if any(abs(col[s]) > _DEFICIENT for col in deltas))
            if changed < size + 1:
                too_few = True
                continue
            a = snap_coefficients(a, deltas, dx, tol)
            const = x[0] - sum(c * vals[0] for c, (_, vals) in zip(a, subset))
            terms = {column.name: c for c, (column, _) in zip(a, subset)}
            return Result("affine", const=round(const, 6) if abs(const - round(const, 6)) <= 1e-6 else round(const, 9),
                          terms=terms)
    return Result("stuck", cause=UNTRIED if too_few else CURVE)
