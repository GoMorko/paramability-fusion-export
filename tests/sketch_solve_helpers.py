"""Hand built sketch graph records (docs/capture-format.md, "Sketch graphs") for the sketch solver tests."""
import math

from tests import context  # noqa: F401


def cos(a):
    return math.cos(math.radians(a))


def sin(a):
    return math.sin(math.radians(a))


class Sketch:
    """Builds one sketch graph record. Point 0 is the sketch origin at (0, 0). Every point and curve is given at its
    solved position; dimensions take their current value."""

    def __init__(self):
        self.points, self.curves, self.dimensions, self.constraints = [], [], [], []
        self.point(0.0, 0.0, origin=True)

    def point(self, px, py, **fields):
        record = {"id": len(self.points), "xy": [px, py], "origin": False, "fixed": False, "free": False,
                  "linked": False, "reference": None, "token": "p%d" % len(self.points)}
        record.update(fields)
        self.points.append(record)
        return record["id"]

    def _curve(self, kind, **fields):
        record = {"id": len(self.curves), "kind": kind, "construction": False, "fixed": False, "free": False,
                  "linked": False, "reference": None, "token": "c%d" % len(self.curves)}
        record.update(fields)
        self.curves.append(record)
        return record["id"]

    def line(self, a, b, **fields):
        return self._curve("line", points=[a, b], center_line=False, **fields)

    def arc(self, center, start, end):
        (cx, cy), (sx, sy) = self.points[center]["xy"], self.points[start]["xy"]
        return self._curve("arc", center=center, points=[start, end], radius=math.hypot(sx - cx, sy - cy))

    def circle(self, center, r, **fields):
        return self._curve("circle", center=center, radius=r, **fields)

    def dim(self, kind, on, value, param=None, orientation=None, driving=True):
        record = {"id": len(self.dimensions), "type": kind, "on": [list(r) for r in on], "param": param,
                  "expression": param, "reads": [param] if param else [], "value": value, "driving": driving,
                  "text": [0.0, 0.0], "token": ""}
        if orientation:
            record["orientation"] = orientation
        self.dimensions.append(record)
        return record["id"]

    def con(self, kind, *on, **extra):
        record = {"id": len(self.constraints), "type": kind, "on": [list(r) for r in on], "token": ""}
        record.update(extra)
        self.constraints.append(record)
        return record["id"]

    def record(self):
        return {"sketch": "Sketch1", "token": "s1", "fully_constrained": True, "origin": 0, "cut": "",
                "points": self.points, "curves": self.curves, "dimensions": self.dimensions,
                "constraints": self.constraints}


def P(i):
    return ("point", i)


def L(i):
    return ("line", i)


def A(i):
    return ("arc", i)


def C(i):
    return ("circle", i)


def rectangle(sketch, corners):
    """Four lines through four point ids, horizontal and vertical by turns, starting with a horizontal one."""
    lines = [sketch.line(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    for i, line in enumerate(lines):
        sketch.con("horizontal" if i % 2 == 0 else "vertical", L(line))
    return lines


class SolvedCase:
    """Assertions over a `Solution`: a point's formulas, evaluated at size settings, equal a hand computation."""

    def assert_point(self, solution, pid, expect, settings):
        """`expect(env)` gives the hand computed (x, y) for a setting `env` (leaf name to value)."""
        vx, vy = solution.points[pid]
        self.assertTrue(vx.derived and vy.derived, "point %d: %s / %s" % (pid, vx.reason, vy.reason))
        for env in settings:
            ex, ey = expect(env)
            self.assertAlmostEqual(vx.expr.value(env), ex, places=9, msg="x of point %d at %r" % (pid, env))
            self.assertAlmostEqual(vy.expr.value(env), ey, places=9, msg="y of point %d at %r" % (pid, env))
