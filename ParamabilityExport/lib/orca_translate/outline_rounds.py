"""Rounds and chamfers of the side edges of a straight extrude, drawn into the extrude's outline.

A side edge of a straight extrude runs along the extrude at a corner of its outline. A round of that edge gives the
same solid as an arc at that corner of the outline, tangent to both lines; an even chamfer gives a line across the
corner. Orca names single edges only by its own numbering, which the copy cannot know, so such a step is copied by
redrawing the outline: the sketch feature the extrude wrote takes the corners as lines and arcs, and the shape the copy
keeps (`solid.Solid`) takes the redrawn prism in place of the old one.

That is the same part only when the round is the first change at that corner, so a step is copied only when:
- every picked edge is a side edge of one copied straight extrude (a `solid.Prism` with its sketch, drawn with lines,
  arcs and circles only) at a corner of two lines, found by its measured middle point. When no picked edge is one,
  `made` answers None and the step goes to the rounds of a face group (`finishes`); arcs at the corner are left out;
- the extrude's sketch feeds no other feature (a pattern copy of the extrude), no other shape of the copy holds the
  extrude's prism (a mirror of the body or a pattern copies the body as it was, and Orca would round those copies
  too), no step between the extrude and the round is left out (a left out round or chamfer of side edges that the copy
  measured counts only when it comes near: `note_left_out`), and no round of a face group or thread changed the body
  after the extrude;
- the corner fits: what the corners take from a line is at most its length (a line taken whole is gone, as when a
  rectangle's short sides are rounded with half their length), a line that stays is not shorter than `_SHORT`, and no
  other curve of the outline reaches into the corner. No margin as for the rounds of a face group: Orca rounds
  nothing here, it draws the outline, which no variable changes;
- the part the copy built shows, around the edge, one straight edge whose middle is Fusion's measured point, with the
  faces next to it flat and the faces at its ends flat and square to it (`_edge`); and the redrawn outline gives what
  Fusion's round gives along lines through the corner (`_same_result`): the corner's material taken away where the
  material makes the corner, filled where the corner points into the material.
Orca cannot tie sketch entities to variables, so the size of the round keeps its number and gets the reason. Redrawing
an outline must never cost a size that follows a variable: when the sketch feature of a picked corner has a bound size
(an expression, a bound entry or a followed variable), or the outline is built from plane cuts that follow sizes
(`outline_cuts`), its corners are cut by corner tools instead (`corner_hosts`, `corner_tools`), which follow the
outline's sizes and the round's own size. The checks above hold for them too, and the copy's shape takes the same
redrawn prism.
"""
import copy
import math

from ..geometry import vec
from ..geometry.footprint import is_full, polyline
from ..orca_recipe.feature import feature_refs
from . import causes, corner_hosts, finish_body, left_corners
from .skip import Skip
from ..design_model.steps import finish as sets_of
from ..design_model.values import Quantity
from .sketches import entities_of
from .solid import ADD, CUT, Moved, Prism, Solid, intersect, subtract, union

POINT_TOL = finish_body.POINT_TOL
# A side of the outline that the corners at its ends take whole (within this, mm) is gone, as on a rectangle whose
# short sides are rounded with half their length; one they leave shorter than `_SHORT` (mm) is too short to draw.
_GONE = 1e-6
_SHORT = 0.01
# How far (mm) to each side of a face the lines that read it run, and how far past the ends of an edge its faces are
# compared.
_SIDE = 2e-3
_PAST = 0.05
# Two runs of material along a line agree when their ends are this close (mm). An edge's measured middle may lie this
# far (mm) from the middle of the edge the copy finds.
_SPAN_TOL = 1e-5
_MIDDLE = 1e-3
# Lines tested near an arc of the copy keep this far (mm, plus the arc's polyline error) from it: the copy's shapes
# draw arcs as polylines.
_ARC_GAP = 0.01
_ARC_SEGMENTS = 64
# Fractions of the reach along each face, and of the corner's triangle, where lines are tested.
_ALONG = (0.02, 0.25, 0.5, 0.75, 1.0)
_GRID = 6


class Pick:
    """One set of a round or chamfer: its edge records, its size (`Quantity`), and whether it is a chamfer
    given by a distance and 45 degrees (even only at a square corner)."""

    def __init__(self, records, value, by_angle=False):
        self.records, self.value, self.by_angle = records, value, by_angle


class _Corner:
    """A side edge of a copied prism: piece `n` of the body, the loop and the two lines at corner `point` (2D, in
    the prism's frame), Fusion's measured point `w` along the extrude, and the size of its round or chamfer."""

    def __init__(self, n, prism, mode, loop, a, b, point, w, pick):
        self.n, self.prism, self.mode = n, prism, mode
        self.loop, self.a, self.b, self.point, self.w = loop, a, b, point, w
        self.pick = pick
        # The ends of the edge along the extrude, and whether the round takes material (else it fills).
        self.low = self.high = None
        self.takes = True

    def lines(self):
        loop = self.prism.loops[self.loop]
        return loop[self.a], loop[self.b]


# ---- the plane geometry of a corner ------------------------------------------------------------------------------

def _same(a, b, tol=POINT_TOL):
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol


def _ends(curve):
    return [] if is_full(curve) else [curve["start"], curve["end"]]


def _corners(loop):
    """(point, curve index, curve index) of each place two curves of a loop meet."""
    out = []
    for n, curve in enumerate(loop):
        for p in _ends(curve):
            if any(_same(p, q) for q, _, _ in out):
                continue
            at = [m for m, other in enumerate(loop) if any(_same(p, q) for q in _ends(other))]
            if len(at) == 2:
                out.append((list(p), at[0], at[1]))
    return out


def _away(line, p):
    """The unit direction a line leaves its end `p` in, and its length."""
    other = line["end"] if _same(line["start"], p) else line["start"]
    dx, dy = other[0] - p[0], other[1] - p[1]
    length = math.hypot(dx, dy)
    return [dx / length, dy / length], length


def _plus(p, d, s):
    return [p[0] + d[0] * s, p[1] + d[1] * s]


class _Shape:
    """What a round or chamfer of `size` does at a corner `p` of two lines leaving it in `d1` and `d2`: `reach` along
    each line, the new curve, and the region `inside` it takes or fills."""

    def __init__(self, p, d1, d2, size, chamfer):
        self.p, self.d1, self.d2 = p, d1, d2
        self.angle = math.acos(max(-1.0, min(1.0, d1[0] * d2[0] + d1[1] * d2[1])))
        self.bisector = vec.unit([d1[0] + d2[0], d1[1] + d2[1], 0.0])[:2]
        self.chamfer, self.size = chamfer, size
        self.reach = size if chamfer else size / math.tan(self.angle / 2.0)
        self.ta, self.tb = _plus(p, d1, self.reach), _plus(p, d2, self.reach)
        self.center = None if chamfer else _plus(p, self.bisector, size / math.sin(self.angle / 2.0))

    def curve(self):
        if self.chamfer:
            return {"kind": "line", "start": list(self.ta), "end": list(self.tb)}
        mid = _plus(self.center, self.bisector, -self.size)
        return {"kind": "arc", "center": list(self.center), "radius": self.size, "start": list(self.ta),
                "end": list(self.tb), "mid": mid}

    def in_triangle(self, q):
        """True when `q` lies inside the triangle of the corner and the two reach points."""
        def side(a, b, c):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        s = [side(self.p, self.ta, q), side(self.ta, self.tb, q), side(self.tb, self.p, q)]
        return all(v > 0 for v in s) or all(v < 0 for v in s)

    def inside(self, q):
        """True when the round or chamfer takes or fills the material along the line through `q`."""
        if not self.in_triangle(q):
            return False
        return self.chamfer or math.hypot(q[0] - self.center[0], q[1] - self.center[1]) > self.size

    def near_curve(self, q):
        """True when `q` lies too near the new arc to tell on which side the copy's polyline puts it."""
        if self.chamfer:
            return False
        sweep = math.pi - self.angle
        gap = _ARC_GAP + 2.0 * self.size * (1.0 - math.cos(sweep / (2.0 * _ARC_SEGMENTS)))
        return abs(math.hypot(q[0] - self.center[0], q[1] - self.center[1]) - self.size) < gap

    def triangle_points(self):
        out = []
        for i in range(1, _GRID):
            for j in range(1, _GRID - i):
                f, g = i / float(_GRID), j / float(_GRID)
                out.append([self.p[0] + f * (self.ta[0] - self.p[0]) + g * (self.tb[0] - self.p[0]),
                            self.p[1] + f * (self.ta[1] - self.p[1]) + g * (self.tb[1] - self.p[1])])
        return out


# ---- finding the side edges ----------------------------------------------------------------------------------------

def _local(prism, point):
    d = vec.sub([float(c) for c in point], prism.origin)
    return (vec.dot(d, prism.x), vec.dot(d, prism.y)), vec.dot(d, prism.z)


def _side_edges(pieces, point, known):
    """(piece index, loop index, corner) of every copied prism whose side edge holds `point`, with the height.
    `known` keeps the corners of each prism's loops between calls."""
    out = []
    for n, (mode, shape) in enumerate(pieces):
        if type(shape) is not Prism or (shape.sketch is None and shape.built is None) \
                or not finish_body.drawn_plainly(shape.loops):
            continue
        uv, w = _local(shape, point)
        if not shape.low + POINT_TOL < w < shape.high - POINT_TOL:
            continue
        if n not in known:
            known[n] = [_corners(loop) for loop in shape.loops]
        for k, corners in enumerate(known[n]):
            for p, a, b in corners:
                if _same(uv, p):
                    out.append((n, mode, shape, k, a, b, p, w))
    return out


def _find(ctx, picks):
    """The corners the picks name, None when an edge is not a side edge of a copied prism, or a Skip."""
    pieces = ctx.solid.pieces
    found, sides, others, known = [], 0, 0, {}
    for pick in picks:
        for record in pick.records:
            points = record.get("points") or []
            hits = _side_edges(pieces, points[0], known) if len(points) == 1 and not record.get("closed") else []
            if not hits:
                others += 1
                continue
            sides += 1
            if len(hits) > 1:
                return Skip("An edge of this step runs along more than one extrude of the Orca copy, so the copy "
                            "cannot tell which outline to draw it into.", causes.CORNER_CHANGED)
            n, mode, shape, k, a, b, p, w = hits[0]
            found.append(_Corner(n, shape, mode, k, a, b, p, w, pick))
    if others or not sides:
        return None
    seen = set()
    for corner in found:
        key = (corner.n, corner.loop, tuple(round(c, 6) for c in corner.point))
        if key in seen:
            return Skip("This step names one edge twice.", causes.CORNER_CHANGED)
        seen.add(key)
    return found


# ---- the steps around the extrude ----------------------------------------------------------------------------------

def _maker(ctx, prism):
    """The timeline index of the step whose shapes hold `prism`, or None."""
    for index, shapes in ctx.shapes.items():
        if any(shape is prism for _, shape in shapes):
            return index
    return None


def _at(features, feature):
    return next((n for n, f in enumerate(features) if f is feature), None)


def _holds(shape, prism):
    """True when `shape` is `prism` or holds it inside a moved copy or a body."""
    if shape is prism:
        return True
    if isinstance(shape, Moved):
        return _holds(shape.shape, prism)
    if isinstance(shape, Solid):
        return any(_holds(inner, prism) for _, inner in shape.pieces)
    return False


def _held_elsewhere(ctx, prism, n):
    """True when a shape of any body of the copy other than piece `n` of the body being built holds `prism`: a
    mirror of the body, a pattern or a Combine that took the body as it was. Orca builds those copies from the
    extrude's sketch, so a redrawn outline would change them too."""
    bodies = {id(b): b for b in list(ctx.bodies) + list(ctx.scopes) + [ctx.part]}
    for body in bodies.values():
        for m, (_, shape) in enumerate(body.solid.pieces):
            if body is ctx.scope and m == n:
                continue
            if _holds(shape, prism):
                return True
    return False


def _extrude_check(ctx, item, on, its, n, noun):
    """(maker index, sketch feature, extrude feature) of the prism of the corners `on` (their shapes `its`), or a
    Skip. An outline built from plane cuts has neither feature (None, None)."""
    prism = on[0].prism
    maker = _maker(ctx, prism)
    sketch = extrude = None
    if prism.built is None:
        made, extrude = prism.sketch
        sketch = made.feature
        at = _at(ctx.features, sketch)
        if at is None or _at(ctx.features, extrude) is None:
            maker = None
        elif any(f is not extrude and at in feature_refs(f) for f in ctx.features):
            return Skip("The outline this %s is on is also used for a copy of the extrude, which must keep its "
                        "sharp corners, so it is left out." % noun, causes.SKETCH_SHARED)
    if maker is None:
        return Skip("The extrude this %s is on is no longer in the Orca copy." % noun, causes.CORNER_CHANGED)
    if _held_elsewhere(ctx, prism, n):
        return Skip("A later step copies the part with this edge (a mirror or a pattern), and Orca would %s the "
                    "edges of the copies too, which Fusion leaves sharp, so it is left out." % noun,
                    causes.BODY_COPIED)
    regions = [left_corners.region(c, s, prism.low, prism.high) for c, s in zip(on, its)]
    if not left_corners.clear_of_gaps(ctx, item.get("index", -1), maker, regions):
        return Skip("A step between the extrude and this %s is left out of the Orca copy, so the copy cannot tell "
                    "whether it changed the edge." % noun, causes.CORNER_CHANGED)
    if any(record["pieces"] > n for record in finish_body.earlier(ctx.scope, ctx.features)):
        return Skip("An earlier round, chamfer or thread changed the part after the extrude this %s is on, so it is "
                    "left out." % noun, causes.EDGES_CHANGED)
    return maker, sketch, extrude


# ---- the shape of the redrawn outline ------------------------------------------------------------------------------

def _shapes(corners, chamfer, noun):
    """The `_Shape` of each corner, or a Skip."""
    out = []
    for corner in corners:
        line_a, line_b = corner.lines()
        if line_a.get("kind") != "line" or line_b.get("kind") != "line":
            return Skip("This %s is on an edge where a curved side of the outline meets another side, which the Orca "
                        "copy does not draw yet, so it is left out." % noun, causes.CORNER_CURVE)
        d1, _ = _away(line_a, corner.point)
        d2, _ = _away(line_b, corner.point)
        if d1[0] * d2[0] + d1[1] * d2[1] < -1 + 1e-9:
            return Skip("This %s is on an edge between two sides that run straight on." % noun, causes.CORNER_CHANGED)
        size = corner.pick.value.n
        shape = _Shape(corner.point, d1, d2, size, chamfer)
        if corner.pick.by_angle and abs(math.degrees(shape.angle) - 90.0) > 1e-6:
            return Skip("This chamfer is set by a distance and an angle on a corner that is not square, so its two "
                        "sides differ, and Orca makes only even chamfers.", causes.CORNER_CHANGED)
        out.append(shape)
    return out


def _fits(prism, corners, shapes, noun):
    """None when every corner fits its outline, else a Skip."""
    taken = {}
    for corner, shape in zip(corners, shapes):
        for line in (corner.a, corner.b):
            taken[(corner.loop, line)] = taken.get((corner.loop, line), 0.0) + shape.reach
    for (k, line), reach in taken.items():
        curve = prism.loops[k][line]
        rest = math.hypot(curve["end"][0] - curve["start"][0], curve["end"][1] - curve["start"][1]) - reach
        if rest < -_GONE or _GONE < rest < _SHORT:
            return Skip("This %s is too big for a side of the outline it is drawn into, so it is left out." % noun,
                        causes.NO_ROOM)
    for corner, shape in zip(corners, shapes):
        across = {"kind": "line", "start": shape.ta, "end": shape.tb}
        for k, loop in enumerate(prism.loops):
            for m, curve in enumerate(loop):
                if k == corner.loop and m in (corner.a, corner.b):
                    continue
                if finish_body.closer_than(curve, across, POINT_TOL) or any(
                        shape.in_triangle(q) for q in polyline(curve)):
                    return Skip("Another side of the outline reaches into the corner of this %s, so it is left out."
                                % noun, causes.NO_ROOM)
    return None


def _redrawn(prism, corners, shapes):
    """The loops of the prism with its corners drawn."""
    loops = [[dict(c) for c in loop] for loop in prism.loops]
    for corner, shape in zip(corners, shapes):
        loop = loops[corner.loop]
        for line, reach_point in ((corner.a, shape.ta), (corner.b, shape.tb)):
            curve = loop[line]
            key = "start" if _same(curve["start"], corner.point) else "end"
            curve[key] = list(reach_point)
        loop.append(shape.curve())
    return [[c for c in loop if c["kind"] != "line" or not _same(c["start"], c["end"], _GONE)] for loop in loops]


def _prism_like(prism, loops):
    frame = {"origin": prism.origin, "x": prism.x, "y": prism.y, "z": prism.z}
    made = Prism(frame, loops, prism.low, prism.high)
    made.ends, made.plane_sizes, made.sketch, made.built = prism.ends, prism.plane_sizes, prism.sketch, prism.built
    made.slot = prism.slot
    return made


# ---- the check along lines -----------------------------------------------------------------------------------------

def _line(prism, uv):
    return vec.add(prism.origin, vec.add(vec.scale(prism.x, uv[0]), vec.scale(prism.y, uv[1]))), list(prism.z)


def _clip(spans, lo, hi):
    return intersect(spans, [(lo, hi)])


def _agree(a, b):
    return len(a) == len(b) and all(abs(x0 - y0) <= _SPAN_TOL and abs(x1 - y1) <= _SPAN_TOL
                                    for (x0, x1), (y0, y1) in zip(a, b))


def _normal_toward(d, bisector):
    """The unit normal of a face along `d` on the side of the bisector."""
    n = [-d[1], d[0]]
    return n if n[0] * bisector[0] + n[1] * bisector[1] > 0 else [-n[0], -n[1]]


def _face_points(corner, shape, toward):
    """Points just off each face next to the edge, on the bisector's side (`toward` 1) or the other (-1)."""
    out = []
    for d, line in ((shape.d1, corner.a), (shape.d2, corner.b)):
        _, length = _away(corner.prism.loops[corner.loop][line], corner.point)
        n = _normal_toward(d, shape.bisector)
        far = min(1.25 * shape.reach + _PAST, length - 10 * _SIDE)
        for f in _ALONG:
            out.append(_plus(_plus(corner.point, d, f * far), n, toward * _SIDE))
    return out


def _edge(solid, corner, shape):
    """(low, high) of the side edge the copy has at the corner, or None when it is not one straight edge with flat
    faces beside it and flat ends square to it, whose middle is Fusion's measured point."""
    prism = corner.prism
    inner, outer = _plus(corner.point, shape.bisector, _SIDE), _plus(corner.point, shape.bisector, -_SIDE)
    convex = prism.footprint.covers(inner)
    material_side = convex if corner.mode == ADD else not convex
    spans_in, spans_out = solid.material(*_line(prism, inner)), solid.material(*_line(prism, outer))
    edge = subtract(spans_in, spans_out) if material_side else subtract(spans_out, spans_in)
    found = next(((lo, hi) for lo, hi in edge if lo <= corner.w <= hi), None)
    if found is None or not all(math.isfinite(v) for v in found):
        return None
    low, high = found
    if abs(corner.w - (low + high) / 2.0) > _MIDDLE or low < prism.low - POINT_TOL or high > prism.high + POINT_TOL:
        return None
    lo, hi = low - _PAST, high + _PAST
    for points, spans in ((_face_points(corner, shape, 1) + [inner], spans_in),
                          (_face_points(corner, shape, -1) + [outer], spans_out)):
        want = _clip(spans, lo, hi)
        for q in points:
            line = _line(prism, q)
            held = _clip(solid.material(*line), lo, hi)
            # Material an earlier round may have taken (`Solid.unsure`) is not known well enough to round next to.
            if not _agree(held, want) or not _agree(_clip(solid.firm(*line), lo, hi), held):
                return None
    return low, high, material_side


def _expected(corners, shapes, solid, start, direction):
    """What Fusion's round leaves along a line: the part's material with each corner's region taken or filled
    between the ends of its edge. None when two corners claim the line or the line runs too near a new arc."""
    held = solid.material(start, direction)
    claimed = False
    for corner, shape in zip(corners, shapes):
        uv, w0 = _local(corner.prism, start)
        if shape.near_curve(uv):
            return None
        if not shape.inside(uv):
            continue
        if claimed:
            return None
        claimed = True
        turn = vec.dot(direction, corner.prism.z)
        ends = sorted(((corner.low - w0) / turn, (corner.high - w0) / turn))
        held = subtract(held, [tuple(ends)]) if corner.takes else union(held, [tuple(ends)])
    return held


def _same_result(solid, redrawn, corners, shapes):
    """True when the part with the outlines redrawn gives what Fusion's round gives, along lines through every corner
    and beside its faces."""
    tested = 0
    for corner, shape in zip(corners, shapes):
        points = shape.triangle_points() + _face_points(corner, shape, 1) + _face_points(corner, shape, -1)
        for uv in points:
            start, direction = _line(corner.prism, uv)
            want = _expected(corners, shapes, solid, start, direction)
            if want is None:
                continue
            tested += 1
            if not _agree(redrawn.material(start, direction), want):
                return False
    return tested > 0


# ---- the step ----------------------------------------------------------------------------------------------------

def _by_piece(corners, shapes):
    """{piece index: (corners, their shapes)}."""
    out = {}
    for corner, shape in zip(corners, shapes):
        out.setdefault(corner.n, ([], []))
        out[corner.n][0].append(corner)
        out[corner.n][1].append(shape)
    return out


def made(ctx, item, picks, chamfer):
    """The features a round (`chamfer` False) or chamfer of side edges wrote or changed: the sketch features it
    redrew, and the corner tools it cut from outlines that follow sizes (`corner_hosts`). None when not every picked
    edge is a side edge of a copied extrude (the step is then one for a face group), or a Skip. `picks` are the
    step's sets (`Pick`)."""
    if not ctx.has_body:
        return None
    noun = "chamfer" if chamfer else "round"
    corners = _find(ctx, picks)
    if corners is None or isinstance(corners, Skip):
        return corners
    if any(c.mode not in (ADD, CUT) for c in corners):
        return Skip("This %s is on an edge of an intersect, which the Orca copy does not redraw." % noun,
                    causes.CORNER_CHANGED)
    if any(abs(abs(vec.dot(c.prism.z, corners[0].prism.z)) - 1.0) > 1e-9 for c in corners):
        return Skip("This %s is on extrudes that run different ways, which the Orca copy does not redraw together."
                    % noun, causes.CORNER_CHANGED)
    shapes = _shapes(corners, chamfer, noun)
    if isinstance(shapes, Skip):
        return shapes
    by_piece = _by_piece(corners, shapes)
    solid = ctx.solid
    pieces = list(solid.pieces)
    extrudes, tools = {}, []
    for n, (on, its) in by_piece.items():
        prism = on[0].prism
        found = _extrude_check(ctx, item, on, its, n, noun)
        if isinstance(found, Skip):
            return found
        problem = _fits(prism, on, its, noun)
        if problem:
            return problem
        for corner, shape in zip(on, its):
            edge = _edge(solid, corner, shape)
            if edge is None:
                return Skip("The edge of this %s is not a whole straight edge of the extrude as the Orca copy builds "
                            "it (a later step changed it, or its ends are not square to it), so it is left out."
                            % noun, causes.CORNER_CHANGED)
            corner.low, corner.high, corner.takes = edge
        loops = _redrawn(prism, on, its)
        # An outline whose sizes follow variables keeps them: its corners are cut by corner tools, not drawn.
        if prism.built is not None or _follows(ctx, found[1]):
            tools.append(n)
        elif entities_of(loops) is None:
            return Skip("The outline of the extrude this %s is on cannot be drawn again." % noun,
                        causes.CORNER_CHANGED)
        extrudes[n] = (found, loops)
        pieces[n] = (pieces[n][0], _prism_like(prism, loops))
    if not _same_result(solid, Solid(pieces), corners, shapes):
        return Skip("Drawing this %s into the outline of the extrude would not give the part Fusion makes (a later "
                    "step changed the part near the edge), so it is left out." % noun, causes.CORNER_CHANGED)
    out, hosts = [], []
    if tools:
        written = corner_hosts.copy(ctx, item, [(extrudes[n][0][0], by_piece[n][0], by_piece[n][1]) for n in tools],
                                    chamfer, noun)
        if isinstance(written, Skip):
            return written
        out += written[0]
        hosts = written[1]
        for n, host in zip(tools, hosts):
            maker = extrudes[n][0][0]
            _reshape(ctx, n, pieces[n], maker)
            if host.rectangle:
                _mark(ctx, maker, "a round or chamfer made after it is cut from its outline in Orca, and the copies "
                                  "must not have it")
    drawn = [n for n in extrudes if n not in tools]
    for n in drawn:
        (maker, sketch, extrude), loops = extrudes[n]
        _redraw(ctx, n, pieces[n], maker, sketch, loops)
        out.append(sketch)
    names = sorted({extrudes[n][0][2].name for n in drawn})
    if drawn:
        reads = {name: None for corner in corners if corner.n in drawn for name in corner.pick.value.reads}
        ctx.doubt(tuple(reads), "%s: Orca draws the %s into the outline of %s, and cannot tie an outline to a variable"
                  % (item.get("name") or "the step", noun, ", ".join(names)))
        ctx.notes.append("%s: copied as %s corners of the outline of %s." % (
            item.get("name") or "The step", "cut" if chamfer else "rounded", ", ".join(names)))
    if tools:
        ctx.notes.append("%s: copied as corners cut from the outline of %s, so the corners follow its sizes." % (
            item.get("name") or "The step", ", ".join(sorted({host.name for host in hosts}))))
    if drawn or any(host.rectangle for host in hosts):
        _mark(ctx, item.get("index"), "a step that rounds or chamfers edges cannot be repeated in Orca yet")
    return out


def _mark(ctx, index, why):
    """Mark step `index` as one a pattern cannot repeat, for `why`; `Context.rollback` takes the mark back."""
    had = ctx.reshaped.get(index)
    ctx.reshaped[index] = why

    def put_back():
        if had is None:
            ctx.reshaped.pop(index, None)
        else:
            ctx.reshaped[index] = had
    ctx.undo.append(put_back)


def _reshape(ctx, n, piece, maker):
    """Put the rounded prism into piece `n` of the copy's shape and into the shapes of step `maker`, so that
    `Context.rollback` can put both back."""
    solid = ctx.solid
    old_piece = solid.pieces[n]
    old_shapes = list(ctx.shapes.get(maker) or [])

    def put_back():
        solid.pieces[n] = old_piece
        ctx.shapes[maker] = old_shapes

    ctx.undo.append(put_back)
    solid.pieces[n] = piece
    ctx.shapes[maker] = [piece if shape is old_piece[1] else (mode, shape) for mode, shape in old_shapes]


def _redraw(ctx, n, piece, maker, sketch, loops):
    """Write the redrawn outline into the sketch feature and the shape, so that `Context.rollback` can put both
    back."""
    kept = {key: copy.deepcopy(getattr(sketch, key)) for key in ("shape", "plane", "entities", "expr")}
    bound = list(ctx.bound)

    def put_back():
        for key, value in kept.items():
            setattr(sketch, key, value)
        ctx.bound[:] = bound

    ctx.undo.append(put_back)
    _reshape(ctx, n, piece, maker)
    prism = piece[1]
    sketch.plane = ctx.place.plane(prism.origin, prism.x, prism.y, prism.z)
    sketch.entities = entities_of(loops)
    _mark(ctx, maker, "a round or chamfer made after it is drawn into its outline in Orca, and the copies must not "
                      "have it")


def _follows(ctx, sketch):
    """True when a size of the sketch feature follows a variable: an expression on the feature, a bound entry or a
    followed variable that names it."""
    held = any(e["feature"] == sketch.name for e in ctx.bound)
    where = any(w.startswith(sketch.name + " ") for ws in ctx.follows.values() for w in ws)
    return bool(sketch.expr or held or where)


# ---- rounds and chamfers left out between the extrude and a round --------------------------------------------------

def note_left_out(ctx, item, sets, chamfer):
    """Measure a round (`chamfer` False) or chamfer step that is left out, on the part the copy has built before it,
    and keep its regions in `ctx.left_corners` when every edge is a whole straight side edge of a copied extrude at a
    corner that fits it. `sets` are the step's round or chamfer sets (`design_model.steps.finish`). A step that cannot
    be measured so is not kept, and every later round counts it."""
    if not ctx.has_body or not sets:
        return
    picks = []
    for one in sets:
        size = one.reach if one.edges else None
        if size is None or one.follows_step or one.foreign:
            return
        picks.append(Pick(one.edges, Quantity(size)))
    corners = _find(ctx, picks)
    if not isinstance(corners, list) or any(c.mode not in (ADD, CUT) for c in corners):
        return
    shapes = _shapes(corners, chamfer, "")
    if isinstance(shapes, Skip):
        return
    by_piece = _by_piece(corners, shapes)
    changed = [record["pieces"] for record in finish_body.earlier(ctx.scope, ctx.features)]
    regions = []
    for n, (on, its) in by_piece.items():
        maker = _maker(ctx, on[0].prism)
        if maker is None or any(pieces > n for pieces in changed) or _fits(on[0].prism, on, its, "") is not None:
            return
        for corner, shape in zip(on, its):
            edge = _edge(ctx.solid, corner, shape)
            if edge is None:
                return
            regions.append(left_corners.region(corner, shape, edge[0], edge[1]))
        if not left_corners.clear_of_gaps(ctx, item.get("index", -1), maker, regions[-len(on):]):
            return
    ctx.left_corners[item.get("index")] = regions
