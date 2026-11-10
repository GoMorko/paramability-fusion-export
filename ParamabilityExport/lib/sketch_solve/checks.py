"""What each dimension measures and whether each constraint holds, decided from the solved geometry alone.

A dimension is read as a `Shape`: the quantity it measures between which entities (a horizontal gap between two
points, the distance from a point to a line, the angle between two lines, a radius). The shape's quantity computed
from the solved positions must equal the dimension's value before the solver uses it; a dimension that fails is
read the wrong way or does not hold, and is not used. A constraint must hold on the solved positions too. Types the
solver has no rule for are "not covered" and keep their entities open.
"""
import math

# Constraint types the solver has rules for. Other types (smooth, polygon, patterns, surfaces, unknown) keep their
# entities open.
COVERED_CONSTRAINTS = ("coincident", "horizontal", "vertical", "horizontal_points", "vertical_points", "parallel",
                       "collinear", "perpendicular", "equal", "tangent", "concentric", "midpoint", "symmetry",
                       "offset")


class Shape:
    """What a dimension measures. `kind` is one of:

    - `dx`, `dy`: the horizontal or vertical gap between points `a` and `b`;
    - `dist`: the distance between points `a` and `b`;
    - `point_line`: the distance from point `a` to line `line`;
    - `line_line`: the distance between parallel lines `line` and `other`;
    - `angle`: the angle between lines `line` and `other`;
    - `radius`: the radius of `curve` times `factor` (2 for a diameter);
    - `ring`: the gap between the radii of `curve` and `other`."""

    def __init__(self, kind, a=None, b=None, line=None, other=None, curve=None, factor=1.0):
        self.kind, self.a, self.b = kind, a, b
        self.line, self.other, self.curve, self.factor = line, other, curve, factor


def _tol(tol, value):
    return tol * (1.0 + abs(value) * 1e-3)


def _point_of(g, ref, axis_line=None):
    """A point id for a ref: the point itself, or the start of a line that runs along `axis_line` ("vertical" for a
    horizontal gap, "horizontal" for a vertical one), or None."""
    if ref[0] == "point":
        return ref[1]
    if axis_line and g.is_line(ref):
        d = g.direction(ref[1])
        if d is None:
            return None
        if (axis_line == "vertical" and abs(d[0]) < 1e-9) or (axis_line == "horizontal" and abs(d[1]) < 1e-9):
            return g.curves[ref[1]].points[0]
    return None


def dimension_shape(g, dim):
    """(Shape, "") for a dimension the solver can use, or (None, why not)."""
    on = dim.on
    if dim.type == "linear":
        orientation = dim.raw.get("orientation")
        if len(on) == 1 and g.is_line(on[0]):
            a, b = g.curves[on[0][1]].points
            kind = {"horizontal": "dx", "vertical": "dy", "aligned": "dist"}.get(orientation)
            return (Shape(kind, a, b), "") if kind else (None, "its direction is not read")
        if len(on) != 2:
            return None, "it does not name two entities"
        if orientation in ("horizontal", "vertical"):
            along = "vertical" if orientation == "horizontal" else "horizontal"
            a, b = _point_of(g, on[0], along), _point_of(g, on[1], along)
            if a is None or b is None:
                return None, "it measures to a curve the solver does not read for this direction"
            return Shape("dx" if orientation == "horizontal" else "dy", a, b), ""
        if orientation == "aligned":
            return _aligned(g, on[0], on[1])
        return None, "its direction is not read"
    if dim.type == "offset":
        if len(on) != 2 or not g.is_line(on[0]):
            return None, "it does not name a line"
        return _aligned(g, on[0], on[1])
    if dim.type == "angular":
        if len(on) == 2 and g.is_line(on[0]) and g.is_line(on[1]):
            return Shape("angle", line=on[0][1], other=on[1][1]), ""
        return None, "it does not name two lines"
    if dim.type in ("diameter", "radial"):
        if len(on) == 1 and g.is_round(on[0]):
            return Shape("radius", curve=on[0][1], factor=2.0 if dim.type == "diameter" else 1.0), ""
        return None, "it does not name an arc or a circle"
    if dim.type == "concentric_circles":
        if len(on) == 2 and g.is_round(on[0]) and g.is_round(on[1]):
            return Shape("ring", curve=on[0][1], other=on[1][1]), ""
        return None, "it does not name two circles"
    return None, "the solver has no rule for this kind of dimension"


def _aligned(g, first, second):
    if first[0] == "point" and second[0] == "point":
        return Shape("dist", first[1], second[1]), ""
    if g.is_line(first) and second[0] == "point":
        return Shape("point_line", second[1], line=first[1]), ""
    if first[0] == "point" and g.is_line(second):
        return Shape("point_line", first[1], line=second[1]), ""
    if g.is_line(first) and g.is_line(second):
        return Shape("line_line", line=first[1], other=second[1]), ""
    return None, "it measures to a curve the solver does not read"


def _gap_to_line(g, pid, cid):
    """Signed distance of a point from a line, along the line's left normal; None for a line with no length."""
    d = g.direction(cid)
    if d is None:
        return None
    (ax, ay), _ = g.ends(cid)
    px, py = g.xy(pid)
    return -d[1] * (px - ax) + d[0] * (py - ay)


def _cross(u, v):
    return u[0] * v[1] - u[1] * v[0]


def measure(g, shape):
    """The quantity a shape measures on the solved geometry, or None when it is not defined there (two lines that
    are not parallel, a line with no length)."""
    kind = shape.kind
    if kind in ("dx", "dy", "dist"):
        (ax, ay), (bx, by) = g.xy(shape.a), g.xy(shape.b)
        return abs(bx - ax) if kind == "dx" else abs(by - ay) if kind == "dy" else math.hypot(bx - ax, by - ay)
    if kind == "point_line":
        gap = _gap_to_line(g, shape.a, shape.line)
        return None if gap is None else abs(gap)
    if kind == "line_line":
        d1, d2 = g.direction(shape.line), g.direction(shape.other)
        if d1 is None or d2 is None or abs(_cross(d1, d2)) > 1e-9:
            return None
        gap = _gap_to_line(g, g.curves[shape.other].points[0], shape.line)
        return abs(gap)
    if kind == "angle":
        d1, d2 = g.direction(shape.line), g.direction(shape.other)
        if d1 is None or d2 is None:
            return None
        return math.degrees(math.atan2(_cross(d1, d2), d1[0] * d2[0] + d1[1] * d2[1])) % 180.0
    if kind == "radius":
        return g.curves[shape.curve].radius * shape.factor
    if kind == "ring":
        return abs(g.curves[shape.curve].radius - g.curves[shape.other].radius)
    return None


def dimension_holds(g, shape, value, tol):
    """True when the solved geometry gives the dimension's value."""
    found = measure(g, shape)
    if found is None:
        return False
    if shape.kind == "angle":
        # A line has no sense of direction: the dimension is one of the angles the two lines make.
        rest = value % 180.0
        return any(abs(((found - c) + 90.0) % 180.0 - 90.0) <= tol for c in (rest, -rest))
    return abs(found - value) <= _tol(tol, value)


# --- constraints -----------------------------------------------------------------------------------------------------


def _on_line(g, pid, cid, tol):
    gap = _gap_to_line(g, pid, cid)
    return gap is not None and abs(gap) <= tol


def _on_circle(g, pid, cid, tol):
    curve = g.curves[cid]
    (px, py), (cx, cy) = g.xy(pid), g.xy(curve.center)
    return abs(math.hypot(px - cx, py - cy) - curve.radius) <= tol


def _same(g, p, q, tol):
    (px, py), (qx, qy) = g.xy(p), g.xy(q)
    return abs(px - qx) <= tol and abs(py - qy) <= tol


def _parallel(g, l1, l2, tol):
    d1, d2 = g.direction(l1), g.direction(l2)
    if d1 is None or d2 is None:
        return False
    length = math.hypot(*(b - a for a, b in zip(*g.ends(l2))))
    return abs(_cross(d1, d2)) * max(length, 1.0) <= tol


def _length(g, cid):
    (ax, ay), (bx, by) = g.ends(cid)
    return math.hypot(bx - ax, by - ay)


def mirror(g, pid, cid):
    """The solved position of a point mirrored about a line."""
    d = g.direction(cid)
    (ax, ay), _ = g.ends(cid)
    px, py = g.xy(pid)
    gap = -d[1] * (px - ax) + d[0] * (py - ay)
    return px + 2.0 * gap * d[1], py - 2.0 * gap * d[0]


def symmetric_pairs(g, first, second, axis, tol):
    """The point pairs a symmetry ties, in solved order: ((p, q), ...) for two points, the matching ends of two lines
    or the centres of two arcs or circles; None when the entities are not mirror images about `axis`."""
    if g.direction(axis) is None:
        return None

    def near(p, q):
        mx, my = mirror(g, p, axis)
        qx, qy = g.xy(q)
        return abs(mx - qx) <= tol and abs(my - qy) <= tol

    if first[0] == "point" and second[0] == "point":
        return ((first[1], second[1]),) if near(first[1], second[1]) else None
    if g.is_line(first) and g.is_line(second):
        (a1, b1), (a2, b2) = g.curves[first[1]].points, g.curves[second[1]].points
        for pairs in (((a1, a2), (b1, b2)), ((a1, b2), (b1, a2))):
            if all(near(p, q) for p, q in pairs):
                return pairs
        return None
    if g.is_round(first) and g.is_round(second):
        c1, c2 = g.curves[first[1]], g.curves[second[1]]
        if abs(c1.radius - c2.radius) <= tol and near(c1.center, c2.center):
            return ((c1.center, c2.center),)
    return None


def offset_pairs(g, con, tol):
    """The (parent, child, side) of each child curve of an offset constraint, side +1 or -1 by where the child lies:
    a child line on the parent's left normal (+1) or right; a child arc with a larger (+1) or smaller radius. None
    when a child has no parent at the offset distance."""
    raw = con.raw
    distance = raw.get("distance")
    if not isinstance(distance, (int, float)) or not raw.get("topology_matched"):
        return None
    parents = [g._ref(r) for r in raw.get("parents") or []]
    children = [g._ref(r) for r in raw.get("children") or []]
    if not children or any(r is None for r in parents + children):
        return None
    out = []
    for child in children:
        found = None
        for parent in parents:
            if g.is_line(child) and g.is_line(parent) and _parallel(g, parent[1], child[1], tol):
                gap = _gap_to_line(g, g.curves[child[1]].points[0], parent[1])
                if abs(abs(gap) - distance) <= tol:
                    found = (parent[1], child[1], 1.0 if gap > 0 else -1.0)
            elif g.is_round(child) and g.is_round(parent):
                cp, cc = g.curves[parent[1]], g.curves[child[1]]
                if _same(g, cp.center, cc.center, tol) and abs(abs(cc.radius - cp.radius) - distance) <= tol:
                    found = (parent[1], child[1], 1.0 if cc.radius > cp.radius else -1.0)
            if found:
                break
        if found is None:
            return None
        out.append(found)
    return out


def constraint_problem(g, con, tol):
    """"" when the constraint holds on the solved geometry and the solver has a rule for it, else why it is not
    used."""
    if con.type not in COVERED_CONSTRAINTS:
        return "the solver has no rule for it"
    on = con.on
    t = con.type
    if t == "coincident":
        if len(on) != 2 or on[0][0] != "point":
            return "it does not name a point"
        p, e = on[0][1], on[1]
        ok = (_same(g, p, e[1], tol) if e[0] == "point" else _on_line(g, p, e[1], tol) if g.is_line(e)
              else _on_circle(g, p, e[1], tol) if g.is_round(e) else None)
        return "" if ok else "the solver has no rule for it" if ok is None else "it does not hold on the drawing"
    if t in ("horizontal", "vertical"):
        if len(on) != 1 or not g.is_line(on[0]):
            return "it does not name a line"
        (ax, ay), (bx, by) = g.ends(on[0][1])
        return "" if abs((by - ay) if t == "horizontal" else (bx - ax)) <= tol else "it does not hold on the drawing"
    if t in ("horizontal_points", "vertical_points"):
        if len(on) != 2 or on[0][0] != "point" or on[1][0] != "point":
            return "it does not name two points"
        (ax, ay), (bx, by) = g.xy(on[0][1]), g.xy(on[1][1])
        gap = (by - ay) if t == "horizontal_points" else (bx - ax)
        return "" if abs(gap) <= tol else "it does not hold on the drawing"
    if t in ("parallel", "collinear", "perpendicular"):
        if len(on) != 2 or not g.is_line(on[0]) or not g.is_line(on[1]):
            return "it does not name two lines"
        l1, l2 = on[0][1], on[1][1]
        if t == "perpendicular":
            d1, d2 = g.direction(l1), g.direction(l2)
            ok = d1 is not None and d2 is not None and abs(d1[0] * d2[0] + d1[1] * d2[1]) * max(
                _length(g, l2), 1.0) <= tol
        else:
            ok = _parallel(g, l1, l2, tol)
            if ok and t == "collinear":
                ok = all(_on_line(g, p, l1, tol) for p in g.curves[l2].points)
        return "" if ok else "it does not hold on the drawing"
    if t == "equal":
        if len(on) == 2 and g.is_line(on[0]) and g.is_line(on[1]):
            ok = abs(_length(g, on[0][1]) - _length(g, on[1][1])) <= tol
        elif len(on) == 2 and g.is_round(on[0]) and g.is_round(on[1]):
            ok = abs(g.curves[on[0][1]].radius - g.curves[on[1][1]].radius) <= tol
        else:
            return "it does not name two lines or two arcs"
        return "" if ok else "it does not hold on the drawing"
    if t == "tangent":
        if len(on) != 2:
            return "it does not name two curves"
        first, second = on
        if g.is_round(first) and g.is_line(second):
            first, second = second, first
        if g.is_line(first) and g.is_round(second):
            gap = _gap_to_line(g, g.curves[second[1]].center, first[1])
            ok = gap is not None and abs(abs(gap) - g.curves[second[1]].radius) <= tol
        elif g.is_round(first) and g.is_round(second):
            c1, c2 = g.curves[first[1]], g.curves[second[1]]
            (x1, y1), (x2, y2) = g.xy(c1.center), g.xy(c2.center)
            gap = math.hypot(x2 - x1, y2 - y1)
            ok = gap > tol and min(abs(gap - c1.radius - c2.radius), abs(gap - abs(c1.radius - c2.radius))) <= tol
        else:
            return "the solver has no rule for a tangent between these curves"
        return "" if ok else "it does not hold on the drawing"
    if t == "concentric":
        if len(on) != 2 or not g.is_round(on[0]) or not g.is_round(on[1]):
            return "it does not name two arcs or circles"
        ok = _same(g, g.curves[on[0][1]].center, g.curves[on[1][1]].center, tol)
        return "" if ok else "it does not hold on the drawing"
    if t == "midpoint":
        if len(on) != 2 or on[0][0] != "point" or not g.is_line(on[1]):
            return "the solver reads a midpoint on a line only"
        (ax, ay), (bx, by) = g.ends(on[1][1])
        px, py = g.xy(on[0][1])
        ok = abs(px - (ax + bx) / 2.0) <= tol and abs(py - (ay + by) / 2.0) <= tol
        return "" if ok else "it does not hold on the drawing"
    if t == "symmetry":
        if len(on) != 3 or not g.is_line(on[2]):
            return "it does not name a symmetry line"
        return "" if symmetric_pairs(g, on[0], on[1], on[2][1], tol) else "it does not hold on the drawing"
    if t == "offset":
        return "" if offset_pairs(g, con, tol) else "the solver reads an offset of matching lines and arcs only"
    return "the solver has no rule for it"
