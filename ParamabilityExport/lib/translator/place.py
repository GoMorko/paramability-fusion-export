"""Moves a finished recipe by a rigid map: every position and direction it holds.

The translator writes a recipe in the frame of the body's own component. The map carries it to the assembly place
where Fusion shows the body (`placement.frame` of the capture), and for a Y up design on to the recipe's Z up frame
(x, y, z) to (x, -z, y). Both are applied in one pass. A recipe is always written Z up (the package manifest's
`upAxis` applies to the STEP files only). 2D sketch values and revolve axes live in a sketch plane and stay.

A coordinate may be a formula: the map writes affine formulas through `Quantity`, and entries of the rotation that
are zero or plus or minus one are snapped, so a part that is only moved keeps plain formulas (`x + 100`).
"""
import copy
import math

from .step_kinds import RECIPE_KINDS
from .step_walk import all_steps
from .values import Quantity, Sized

# Step kind -> paths to positions, and to directions (turned, not moved), from the step kind table.
POSITIONS = {k.name: list(k.positions) for k in RECIPE_KINDS if k.positions}
DIRECTIONS = {k.name: list(k.directions) for k in RECIPE_KINDS if k.directions}

# Step kinds with positions or directions that the translator never writes. The schema walk in the tests
# fails when a kind appears in no table, so a new schema field cannot slip by.
NOT_WRITTEN = tuple(k.name for k in RECIPE_KINDS if not k.written)

FRAME_NOT_NUMBERS = "The frame of the part is not made of numbers."
_SNAP = 1e-12
# How far a frame's axes may be from unit length and right angles and still count as a rotation.
RIGID_TOLERANCE = 1e-6


class Move:
    """p -> rows * p + offset for a position, d -> rows * d for a direction. `rows` is a 3 by 3 rotation."""

    def __init__(self, rows, offset=(0.0, 0.0, 0.0)):
        self.rows = tuple(tuple(_snap(c) for c in row) for row in rows)
        self.offset = tuple(0.0 if abs(v) <= _SNAP else float(v) for v in offset)

    @property
    def is_identity(self):
        return self.rows == IDENTITY_ROWS and not any(self.offset)

    def then(self, other):
        """The move that applies `self` first, then `other`."""
        rows = [[sum(other.rows[i][k] * self.rows[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        offset = [sum(other.rows[i][k] * self.offset[k] for k in range(3)) + other.offset[i] for i in range(3)]
        return Move(rows, offset)

    def inverse(self):
        rows = [[self.rows[j][i] for j in range(3)] for i in range(3)]
        offset = [-sum(rows[i][k] * self.offset[k] for k in range(3)) for i in range(3)]
        return Move(rows, offset)


def _snap(value):
    for target in (0.0, 1.0, -1.0):
        if abs(value - target) <= _SNAP:
            return target
    return float(value)


IDENTITY_ROWS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
TURN_Z_UP = Move(((1, 0, 0), (0, 0, -1), (0, 1, 0)))


def move_from_frame(frame):
    """The move of an occurrence frame {origin, x, y, z}: its axes are the columns of the rotation."""
    axes = (frame["x"], frame["y"], frame["z"])
    return Move([[axes[j][i] for j in range(3)] for i in range(3)], frame["origin"])


def frame_problem(frame):
    """A plain reason when the frame is not a rotation plus a move (a scale, a mirror), else None."""
    try:
        axes = [[float(v) for v in frame[key]] for key in ("x", "y", "z")]
        origin = [float(v) for v in frame["origin"]]
    except (KeyError, TypeError, ValueError):
        return FRAME_NOT_NUMBERS
    if not all(len(a) == 3 for a in axes) or len(origin) != 3 or not all(math.isfinite(v) for a in axes for v in a + origin):
        return FRAME_NOT_NUMBERS
    for i in range(3):
        for j in range(i, 3):
            dot = sum(axes[i][k] * axes[j][k] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > RIGID_TOLERANCE:
                return "The frame of the part is scaled or skewed."
    x, y, z = axes
    cross = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]]
    if sum(c * v for c, v in zip(cross, z)) < 0:
        return "The frame of the part is mirrored."
    return None


def move_for(capture):
    """The component to assembly move of the capture's target, then the Y up turn when the design is Y up."""
    move = Move(IDENTITY_ROWS)
    placement = (capture.get("target") or {}).get("placement")
    if isinstance(placement, dict) and isinstance(placement.get("frame"), dict):
        move = move_from_frame(placement["frame"])
    if capture.get("up_axis") == "y":
        move = move.then(TURN_Z_UP)
    return move


def _quantity(value):
    if isinstance(value, Sized):
        return Quantity(value.n, value["expr"], value.reads)
    return Quantity(value)


def _is_triple(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(v, Sized) or isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


def _mapped(triple, move, offset, shift=None):
    coords = [_quantity(v) for v in triple]
    out = []
    for i in range(3):
        total = None
        for coef, coord in zip(move.rows[i], coords):
            if coef == 0:
                continue
            term = coord.scaled(coef)
            total = term if total is None else total.plus(term)
        total = Quantity(0.0) if total is None else total
        if offset and move.offset[i]:
            total = total.plus(move.offset[i])
        if offset and shift is not None and (shift[i].sized or shift[i].n):
            total = total.plus(shift[i])
        out.append(total.json())
    return out


def _apply(node, path, fn):
    if path[-1] == "[]":
        path = path[:-1]  # a trailing "[]" is the list of points that the last key holds
    key, rest = path[0], path[1:]
    if key == "[]":
        if isinstance(node, list):
            for entry in node:
                _apply(entry, rest, fn)
        return
    if not isinstance(node, dict) or key not in node:
        return
    if rest:
        _apply(node[key], rest, fn)
    elif _is_triple(node[key]):
        node[key] = fn(node[key])
    elif isinstance(node[key], list):
        node[key] = [fn(p) if _is_triple(p) else p for p in node[key]]


def place(recipe, move, shift=None):
    """A copy of the recipe with every position moved and every direction turned. The input is kept.

    `shift` is three Quantities added to every position after the move (not to directions): a move that follows
    sizes, zero at the sizes the recipe was measured at."""
    out = copy.deepcopy(recipe)
    if shift is not None and not any(q.sized or q.n for q in shift):
        shift = None
    if move.is_identity and shift is None:
        return out
    for step in all_steps(out.get("features", [])):
        kind = step.get("kind")
        for path in POSITIONS.get(kind, ()):
            _apply(step, path, lambda t: _mapped(t, move, True, shift))
        for path in DIRECTIONS.get(kind, ()):
            _apply(step, path, lambda t: _mapped(t, move, False))
    return out
