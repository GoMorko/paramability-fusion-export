"""The relations each curve, constraint and dimension of a sketch adds, for the propagation in `solve`.

A rule turns one item into relations between slots (`slots`): linear relations (`Rel`), distances (`Dist`), a fixed
line direction (`DirFixed`) or a turn between two line directions (`DirLink`). A relation whose factors need a line
direction or other values that are not known yet is `Deferred`: it is built once they are.

Where an item allows two solutions (a gap to the left or the right, a turn one way or the other) the rule picks the
one the solved drawing shows, with `sign`, and gives up when the drawing cannot tell them apart.
"""
from ..sketch_values.expr import num
from . import checks
from .slots import Dist, Lin, Rel, length, offset, radius, x, y


class Deferred:
    """Relations that can be built once `ready(solver)` is true; `build(solver)` returns them."""

    def __init__(self, ready, build, source):
        self.ready, self.build, self.source = ready, build, source


class DirFixed:
    """A line's direction is one of `angles` (degrees); the solved line picks which."""

    def __init__(self, line, angles, source):
        self.line, self.angles, self.source = line, tuple(angles), source


class DirLink:
    """Line `b`'s direction is line `a`'s turned by one of `turns` (`Expr` angles, half turns added as needed),
    and the other way round; the solved lines pick which."""

    def __init__(self, a, b, turns, source):
        self.a, self.b, self.turns, self.source = a, b, tuple(turns), source


class Ambiguous(Exception):
    """The solved drawing cannot tell the two solutions of a rule apart."""


def sign(value, tol):
    if abs(value) <= tol:
        raise Ambiguous()
    return 1.0 if value > 0 else -1.0


def _dirs_known(*lines):
    return lambda s: all(s.dirs.known(line) is not None for line in lines)


def _normal_lin(d, p):
    """`n . p` for a direction `d` and point `p` as a `Lin`."""
    nx, ny = d.normal()
    return Lin({x(p): nx, y(p): ny})


def _along_lin(d, p):
    """`d . p` as a `Lin`."""
    return Lin({x(p): d.c, y(p): d.s})


def curve_rules(s, cid):
    """A line's ends lie on it and its length runs along it; an arc's ends lie on its circle."""
    curve = s.g.curves[cid]
    source = "curve %d (%s)" % (cid, curve.kind)
    if curve.kind == "line" and cid in s.dirs.vector:
        a, b = curve.points

        def build(s):
            d = s.dirs.known(cid)
            return [Rel(_normal_lin(d, a).add(offset(cid), -1.0), source),
                    Rel(_normal_lin(d, b).add(offset(cid), -1.0), source),
                    Rel(_along_lin(d, b).plus(_along_lin(d, a), -1.0).add(length(cid), -1.0), source)]
        return [Deferred(_dirs_known(cid), build, source)]
    if curve.kind == "arc":
        return [Dist(p, curve.center, Lin({radius(cid): 1.0}), source) for p in curve.points]
    return []


def _base_normal_gap(s, pid, line):
    """`n . p - o` on the solved drawing for a line's class normal."""
    bx, by = s.dirs.base(line)
    px, py = s.g.xy(pid)
    return -by * px + bx * py - s.slots.base[offset(line)]


def _gap_rel(s, pid, line, extra, source):
    """`n . p - o(line) + extra == 0` once the line's direction is known."""
    def build(s):
        lin = _normal_lin(s.dirs.known(line), pid).add(offset(line), -1.0)
        return [Rel(lin.plus(extra), source)]
    return Deferred(_dirs_known(line), build, source)


def constraint_rules(s, con, label):
    """The relations of one constraint that holds on the drawing."""
    g, on, t = s.g, con.on, con.type
    tol = s.tol
    if t == "coincident":
        p, e = on[0][1], on[1]
        if e[0] == "point":
            return [Rel(Lin({x(p): 1.0, x(e[1]): -1.0}), label), Rel(Lin({y(p): 1.0, y(e[1]): -1.0}), label)]
        if g.is_line(e):
            return [_gap_rel(s, p, e[1], num(0.0), label)] if e[1] in s.dirs.vector else []
        return [Dist(p, g.curves[e[1]].center, Lin({radius(e[1]): 1.0}), label)]
    if t in ("horizontal", "vertical"):
        if on[0][1] not in s.dirs.vector:
            return []
        return [DirFixed(on[0][1], (0.0, 180.0) if t == "horizontal" else (90.0, -90.0), label)]
    if t in ("horizontal_points", "vertical_points"):
        axis = y if t == "horizontal_points" else x
        return [Rel(Lin({axis(on[0][1]): 1.0, axis(on[1][1]): -1.0}), label)]
    if t == "parallel":
        return []  # joined into one direction class before the rules run
    if t == "collinear":
        return [Rel(Lin({offset(on[0][1]): 1.0, offset(on[1][1]): -1.0}), label)]
    if t == "perpendicular":
        return [DirLink(on[0][1], on[1][1], (num(90.0),), label)]
    if t == "equal":
        a, b = on[0][1], on[1][1]
        if g.is_line(on[0]):
            same = sign(s.slots.base[length(a)] * s.slots.base[length(b)], tol)
            return [Rel(Lin({length(a): 1.0, length(b): -same}), label)]
        return [Rel(Lin({radius(a): 1.0, radius(b): -1.0}), label)]
    if t == "tangent":
        first, second = on
        if g.is_line(first) and g.is_round(second) or g.is_line(second) and g.is_round(first):
            line, curve = (first[1], second[1]) if g.is_line(first) else (second[1], first[1])
            return _tangent_line(s, line, curve, label)
        return _tangent_rounds(s, first[1], second[1], label)
    if t == "concentric":
        c1, c2 = g.curves[on[0][1]].center, g.curves[on[1][1]].center
        return [Rel(Lin({x(c1): 1.0, x(c2): -1.0}), label), Rel(Lin({y(c1): 1.0, y(c2): -1.0}), label)]
    if t == "midpoint":
        p = on[0][1]
        a, b = g.curves[on[1][1]].points
        return [Rel(Lin({x(p): 2.0, x(a): -1.0, x(b): -1.0}), label),
                Rel(Lin({y(p): 2.0, y(a): -1.0, y(b): -1.0}), label)]
    if t == "symmetry":
        return _symmetry(s, con, label)
    if t == "offset":
        return _offset(s, con, label)
    return []


def _tangent_line(s, line, curve, label):
    """The circle's centre lies its radius from the line; an arc end on the line is the foot of the centre."""
    g = s.g
    if line not in s.dirs.vector:
        return []
    center = g.curves[curve].center
    side = sign(_base_normal_gap(s, center, line), s.tol)
    out = [_gap_rel(s, center, line, Lin({radius(curve): -side}), label)]
    if g.curves[curve].kind != "arc":
        return out
    for p in g.curves[curve].points:
        if p not in s.on_line(line):
            continue

        def build(s, p=p):
            nx, ny = s.dirs.known(line).normal()
            return [Rel(Lin({x(p): 1.0, x(center): -1.0, radius(curve): nx * side}), label),
                    Rel(Lin({y(p): 1.0, y(center): -1.0, radius(curve): ny * side}), label)]
        out.append(Deferred(_dirs_known(line), build, label))
    return out


def _tangent_rounds(s, first, second, label):
    """The centres lie the sum or the difference of the radii apart; a shared arc end is on the line through them."""
    g = s.g
    c1, c2 = g.curves[first], g.curves[second]
    (x1, y1), (x2, y2) = g.xy(c1.center), g.xy(c2.center)
    gap = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    if abs(gap - c1.radius - c2.radius) <= s.tol:
        rho = Lin({radius(first): 1.0, radius(second): 1.0})
    else:
        side = sign(c1.radius - c2.radius, s.tol)
        rho = Lin({radius(first): side, radius(second): -side})
    out = [Dist(c1.center, c2.center, rho, label)]
    shared = [p for p in c1.points if any(s.twin(p) == s.twin(q) for q in c2.points)]
    for p in shared:
        px, py = g.xy(p)
        towards = sign((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1), s.tol)
        needed = (x(c1.center), y(c1.center), x(c2.center), y(c2.center), radius(first), radius(second))

        def build(s, p=p, towards=towards):
            k = [s.slots.known(slot) for slot in needed]
            share = k[4] * towards / (k[4] * rho.terms[radius(first)] + k[5] * rho.terms[radius(second)])
            return [Rel(Lin({x(p): 1.0}, -(k[0] + (k[2] - k[0]) * share)), label),
                    Rel(Lin({y(p): 1.0}, -(k[1] + (k[3] - k[1]) * share)), label)]
        out.append(Deferred(lambda s: all(s.slots.known(slot) is not None for slot in needed), build, label))
    return out


def _symmetry(s, con, label):
    g = s.g
    axis = con.on[2][1]
    if axis not in s.dirs.vector:
        return []
    pairs = checks.symmetric_pairs(g, con.on[0], con.on[1], axis, s.tol)
    out = []
    for p, q in pairs:
        def build(s, p=p, q=q):
            d = s.dirs.known(axis)
            middle = _normal_lin(d, p).plus(_normal_lin(d, q)).add(offset(axis), -2.0)
            across = _along_lin(d, p).plus(_along_lin(d, q), -1.0)
            return [Rel(middle, label), Rel(across, label)]
        out.append(Deferred(_dirs_known(axis), build, label))
    if g.is_round(con.on[0]):
        out.append(Rel(Lin({radius(con.on[0][1]): 1.0, radius(con.on[1][1]): -1.0}), label))
    return out


def _offset(s, con, label):
    g = s.g
    distance = s.offset_distance(con)
    out = []
    for parent, child, _ in checks.offset_pairs(g, con, s.tol):
        if g.curves[child].kind == "line":
            if child not in s.dirs.vector:
                return []
            side = sign(s.slots.base[offset(child)] - s.slots.base[offset(parent)], s.tol)
            out.append(Rel(Lin({offset(child): 1.0, offset(parent): -1.0}, distance * -side), label))
        else:
            cp, cc = g.curves[parent].center, g.curves[child].center
            side = sign(g.curves[child].radius - g.curves[parent].radius, s.tol)
            out += [Rel(Lin({x(cc): 1.0, x(cp): -1.0}), label), Rel(Lin({y(cc): 1.0, y(cp): -1.0}), label),
                    Rel(Lin({radius(child): 1.0, radius(parent): -1.0}, distance * -side), label)]
    return out


def dimension_rules(s, shape, value, label):
    """The relations of one driving dimension that matches the drawing; `value` is its `Expr`."""
    g, tol, base = s.g, s.tol, s.slots.base
    kind = shape.kind
    if kind in ("dx", "dy"):
        axis = x if kind == "dx" else y
        a, b = shape.a, shape.b
        side = sign(base[axis(b)] - base[axis(a)], tol)
        return [Rel(Lin({axis(b): 1.0, axis(a): -1.0}, value * -side), label)]
    if kind == "dist":
        a, b = shape.a, shape.b
        out = [Dist(a, b, Lin({}, value), label)]
        for line in s.lines_through(a, b):
            ends = g.curves[line].points
            if set(ends) == {a, b}:
                side = sign(base[length(line)], tol)
                out.append(Rel(Lin({length(line): 1.0}, value * -side), label))
                continue
            bx, by = s.dirs.base(line)
            (ax_, ay_), (bx_, by_) = g.xy(a), g.xy(b)
            side = sign(bx * (bx_ - ax_) + by * (by_ - ay_), tol)

            def build(s, line=line, side=side):
                d = s.dirs.known(line)
                return [Rel(_along_lin(d, b).plus(_along_lin(d, a), -1.0).plus(value, -side), label)]
            out.append(Deferred(_dirs_known(line), build, label))
        return out
    if kind == "point_line":
        if shape.line not in s.dirs.vector:
            return None
        side = sign(_base_normal_gap(s, shape.a, shape.line), tol)
        return [_gap_rel(s, shape.a, shape.line, value * -side, label)]
    if kind == "line_line":
        first, second = shape.line, shape.other
        if first not in s.dirs.vector or second not in s.dirs.vector:
            return None
        start = g.curves[second].points[0]
        side = sign(_base_normal_gap(s, start, first), tol)

        def build(s):
            if not s.stays_parallel(first, second):
                s.refuse(label, "the two lines are not tied parallel")
                return []
            lin = _normal_lin(s.dirs.known(first), start).add(offset(first), -1.0)
            return [Rel(lin.plus(value, -side), label)]
        return [Deferred(_dirs_known(first, second), build, label)]
    if kind == "angle":
        return [DirLink(shape.line, shape.other, (value, -value), label)]
    if kind == "radius":
        return [Rel(Lin({radius(shape.curve): shape.factor}, -value), label)]
    if kind == "ring":
        side = sign(g.curves[shape.other].radius - g.curves[shape.curve].radius, tol)
        return [Rel(Lin({radius(shape.other): 1.0, radius(shape.curve): -1.0}, value * -side), label)]
    return None
