"""The rigid map of a recipe: a rotation plus a move, built from an occurrence frame, with its checks.

`Move` carries positions (rotated and moved) and directions (rotated only). A frame that is scaled, skewed or
mirrored is not a rigid map: `frame_problem` says why.
"""
import math

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


def axis_angle(rows):
    """`(unit axis, degrees)` of the turn `rows` (0 to 180 degrees, about an axis through the origin), or None when it
    turns nothing."""
    trace = rows[0][0] + rows[1][1] + rows[2][2]
    angle = math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0)))
    if angle < 1e-9:
        return None
    skew = [rows[2][1] - rows[1][2], rows[0][2] - rows[2][0], rows[1][0] - rows[0][1]]
    size = math.sqrt(sum(c * c for c in skew))
    if size > 1e-6:
        return [c / size for c in skew], math.degrees(angle)
    # A half turn: the axis is the longest column of (rows + I) / 2.
    columns = [[(rows[i][j] + (1.0 if i == j else 0.0)) / 2.0 for i in range(3)] for j in range(3)]
    longest = max(columns, key=lambda c: sum(v * v for v in c))
    size = math.sqrt(sum(v * v for v in longest))
    return [v / size for v in longest], 180.0
