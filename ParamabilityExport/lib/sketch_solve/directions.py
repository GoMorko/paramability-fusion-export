"""Line directions of a sketch.

Lines tied parallel or collinear share a direction class. Each class has a base vector: the solved direction of its
first line. A class's direction, once known, is a `Dir` that equals the base vector on the solved drawing (not its
opposite), so every line of the class measures its offset (`("o", line)`) along the same normal.
"""
import math

from ..sketch_values.expr import cos, num, sin, sqrt


class Dir:
    """A unit direction `(c, s)` as two `Expr` values, with its angle in degrees when that is known as an `Expr`."""

    def __init__(self, c, s, angle=None):
        self.c, self.s, self.angle = c, s, angle

    @classmethod
    def at(cls, angle):
        return cls(cos(angle), sin(angle), angle)

    def normal(self):
        """The left normal `(-s, c)`."""
        return -self.s, self.c

    def turned(self, by):
        """This direction turned by the angle `by` (an `Expr`, degrees, counter clockwise)."""
        if self.angle is not None:
            return Dir.at(self.angle + by)
        cb, sb = cos(by), sin(by)
        return Dir(self.c * cb - self.s * sb, self.s * cb + self.c * sb)

    def reversed(self):
        return Dir(-self.c, -self.s, None if self.angle is None else self.angle + 180.0)


class Directions:
    """Direction classes over the lines that have a length on the solved drawing."""

    def __init__(self, base_vectors):
        self.vector = dict(base_vectors)  # line -> its own solved unit vector
        self.parent = {}
        self.value = {}  # class root -> Dir
        self.source = {}

    def root(self, line):
        while line in self.parent:
            line = self.parent[line]
        return line

    def join(self, a, b):
        ra, rb = self.root(a), self.root(b)
        if ra != rb:
            self.parent[rb] = ra

    def base(self, line):
        """The class's base vector on the solved drawing."""
        return self.vector[self.root(line)]

    def known(self, line):
        return self.value.get(self.root(line))

    def same_class(self, a, b):
        return self.root(a) == self.root(b)

    def angle_of(self, line):
        """The angle (an `Expr`, degrees) of a line from its first point to its second, or None when its class has
        no known angle. The class's direction points along its base vector, so a line drawn the other way is turned
        half round."""
        known = self.known(line)
        if known is None or known.angle is None:
            return None
        own, base = self.vector[line], self.base(line)
        return known.angle + 180.0 if own[0] * base[0] + own[1] * base[1] < 0 else known.angle


def matches(d, vector, value_at, tol=1e-6):
    """True when a `Dir` equals a unit vector on the solved drawing; `value_at` gives an `Expr`'s number there."""
    try:
        return abs(value_at(d.c) - vector[0]) <= tol and abs(value_at(d.s) - vector[1]) <= tol
    except (ValueError, ZeroDivisionError):
        return False


def from_points(ax, ay, bx, by):
    """The unit direction from point a to point b (all `Expr` coordinates), or along an axis when one gap is zero
    in every setting. The caller turns it around when it points the other way on the solved drawing."""
    dx, dy = bx - ax, by - ay
    if dy.is_constant and dy.const == 0.0:
        return Dir(num(1.0), num(0.0), num(0.0))
    if dx.is_constant and dx.const == 0.0:
        return Dir(num(0.0), num(1.0), num(90.0))
    if dx.is_constant and dy.is_constant:
        size = math.hypot(dx.const, dy.const)
        return Dir(num(dx.const / size), num(dy.const / size), num(math.degrees(math.atan2(dy.const, dx.const))))
    size = sqrt(dx * dx + dy * dy)
    return Dir(dx / size, dy / size)
