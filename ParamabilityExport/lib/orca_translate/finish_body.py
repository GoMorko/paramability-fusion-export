"""The faces and edges of the body the Orca copy has built, for rounds and bevels.

Orca rounds or bevels every edge of one face group of the body it rebuilt (`GeometryEngine::collect_edges`): Top takes
each edge of a flat face whose outward normal points up (its z above 0.7), Bottom each edge of a flat face that points
down (below -0.7), Lateral each edge of any other face (curved faces count as Lateral), All every edge. Orca's Z is
the design's up direction. A Fusion step is copied only when its picked edges are exactly one group of the copy.

The copy knows its edges only for a simple body (`body_of`): one straight extrusion (`solid.Prism`) with straight
cuts through all of it, along the same direction, whose outlines lie inside the extrusion's outline and touch nothing
else. Its faces are the two ends and one side face per outline curve. Its edges are the end outlines (one per curve
and end), one edge along the direction at each corner of an outline, and the seam of a full circle. A seam, and the
edge where two side faces meet smoothly, are neither edges Fusion shows nor edges Orca rounds, so they may be picked
or not.

`room` is the rule that keeps a round Orca may fail to make out of the copy: a failed round stops the whole rebuild.
Every face must keep a margin after the round takes its share of it.

A round or chamfer changes the edges, and so does a thread, while the shape the copy keeps (`solid.Solid`) does not
show them. Each is recorded on the body (`context.Body.finishes`: `finished`, `changed`), so a later round can tell
what came before. The material near rounded edges may be gone in Orca, so it goes into the shape's `unsure` list
(`Rounded`, `unsure`): a later cut, hole or thread must meet material away from it, since Orca stops the whole
rebuild on one that removes nothing.
"""
import math

from ..geometry import vec
from ..geometry.footprint import Footprint, curve_distance, is_full, polyline
from ..orca_recipe.enums import FaceGroup
from .solid import ADD, CUT, Moved, Prism, Solid, union

# A Fusion edge point lies on an edge of the copy when it is this close (mm).
POINT_TOL = 1e-3
# Outlines closer than this (mm) touch.
TOUCH_TOL = 1e-2
# Orca's split between flat faces that point up or down and the rest, and how near to it a face is too close to call.
UP_SPLIT = 0.7
SPLIT_MARGIN = 0.02
# Each face must stay this much larger than what the rounds take from it, and a round must be larger than Orca's
# smallest one (mm).
ROOM = 1.1
SMALLEST = 0.001
# A round's reach (`reach`) is kept this much larger, and lines through it are sampled this often, each change
# placed by this many halvings.
REACH_MARGIN = 1.05
_SAMPLES = 96
_HALVINGS = 30
_EPS = 1e-9

# The curve kinds of an outline whose edges the copy can tell (a spline is not one of them).
PLAIN_KINDS = ("line", "arc", "circle")
TOP, BOTTOM, LATERAL, ALL = FaceGroup.TOP, FaceGroup.BOTTOM, FaceGroup.LATERAL, FaceGroup.ALL
GROUP_WORDS = {TOP: "top", BOTTOM: "bottom", LATERAL: "side", ALL: "all"}


class Edge:
    """One edge of the copy: `kind` "end" (an outline curve at an end), "side" (along the direction at a corner) or
    "seam"; `faces` the two face keys it joins; `required` false for a seam or a smooth side edge."""

    def __init__(self, kind, faces, required, curve=None, height=None, corner=None):
        self.kind, self.faces, self.required = kind, faces, required
        self.curve, self.height, self.corner = curve, height, corner


class Body:
    """A simple body as the copy builds it, in the frame of its extrusion: `section` the 2D curves (outline and the
    holes through it), `low` and `high` the heights of its ends along the frame's z."""

    def __init__(self, frame, loops, low, high):
        self.origin, self.x, self.y, self.z = frame
        self.loops = loops
        self.low, self.high = low, high
        self.curves = [c for loop in loops for c in loop]
        self.region = Footprint({"loops": [{"curves": loop} for loop in loops]})
        self.corners = []  # (point, curve index, curve index)
        self.edges = []
        self.normals = {"low": vec.scale(self.z, -1.0), "high": list(self.z)}  # flat faces only

    def local(self, p):
        d = vec.sub([float(c) for c in p], self.origin)
        return (vec.dot(d, self.x), vec.dot(d, self.y)), vec.dot(d, self.z)

    def lift(self, uv):
        return vec.add(vec.scale(self.x, uv[0]), vec.scale(self.y, uv[1]))


def _frame(prism):
    return list(prism.origin), list(prism.x), list(prism.y), list(prism.z)


def _to_frame(curve, source, target):
    """A curve of `source`'s plane in `target`'s 2D coordinates (the planes are parallel)."""
    out = dict(curve)
    for key in ("start", "end", "mid", "center"):
        if isinstance(curve.get(key), (list, tuple)):
            world = vec.add(source.origin, vec.add(vec.scale(source.x, float(curve[key][0])),
                                                   vec.scale(source.y, float(curve[key][1]))))
            out[key] = list(target.local(world)[0])
    return out


def _box(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _segment_gap(a, b, c, d):
    """Distance between two 2D segments."""
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    if side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0:
        return 0.0

    def to_seg(p, s, e):
        dx, dy = e[0] - s[0], e[1] - s[1]
        size = dx * dx + dy * dy
        t = 0.0 if size <= 0 else max(0.0, min(1.0, ((p[0] - s[0]) * dx + (p[1] - s[1]) * dy) / size))
        return math.hypot(p[0] - s[0] - t * dx, p[1] - s[1] - t * dy)
    return min(to_seg(a, c, d), to_seg(b, c, d), to_seg(c, a, b), to_seg(d, a, b))


def closer_than(one, two, limit):
    """True when two capture curves come closer than `limit` (mm)."""
    p, q = polyline(one), polyline(two)
    b1, b2 = _box(p), _box(q)
    if max(b1[0] - b2[2], b2[0] - b1[2], b1[1] - b2[3], b2[1] - b1[3]) >= limit:
        return False
    for a, b in zip(p, p[1:]):
        for c, d in zip(q, q[1:]):
            if _segment_gap(a, b, c, d) < limit:
                return True
    return False


def _ends(curve):
    return [] if is_full(curve) else [curve["start"], curve["end"]]


def _same(a, b, tol=POINT_TOL):
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol


def _leaving(curve, p):
    """The unit direction a curve leaves its end `p` in."""
    if curve["kind"] == "line":
        other = curve["end"] if _same(curve["start"], p) else curve["start"]
        return vec.unit([other[0] - p[0], other[1] - p[1], 0.0])[:2]
    c = curve["center"]
    t = [-(p[1] - c[1]), p[0] - c[0]]
    mid = curve.get("mid") or polyline(curve)[len(polyline(curve)) // 2]
    if t[0] * (mid[0] - p[0]) + t[1] * (mid[1] - p[1]) < 0:
        t = [-t[0], -t[1]]
    return vec.unit([t[0], t[1], 0.0])[:2]


def _chains(loop):
    """The corners of a loop as (point, curve index in loop, curve index in loop), or None when the curves do not
    meet two at a corner."""
    ends = [(p, n) for n, c in enumerate(loop) for p in _ends(c)]
    corners = []
    for p, n in ends:
        if any(_same(p, q) for q, _, _ in corners):
            continue
        at = [m for q, m in ends if _same(p, q)]
        if len(at) != 2 or at[0] == at[1]:
            return None
        corners.append((p, at[0], at[1]))
    return corners


def body_of(solid):
    """The `Body` of the part the copy built (`solid.Solid`), or a plain reason why its edges cannot be told."""
    pieces = list(getattr(solid, "pieces", None) or [])
    unknown = "it is not one straight extrude with only holes straight through it"
    if not pieces or any(not isinstance(p, Prism) for _, p in pieces):
        return unknown
    mode, base = pieces[0]
    if mode != ADD or not (math.isfinite(base.low) and math.isfinite(base.high)) or base.high - base.low <= _EPS:
        return unknown
    if not all(drawn_plainly(p.loops) for _, p in pieces):
        return "its outline has a curve other than lines, arcs and circles"
    if any(mode != CUT for mode, _ in pieces[1:]):
        return unknown
    body = Body(_frame(base), [list(loop) for loop in base.loops], base.low, base.high)
    for _, cut in pieces[1:]:
        if abs(abs(vec.dot(cut.z, body.z)) - 1.0) > 1e-9 or len(cut.loops) != 1:
            return unknown
        shift = vec.dot(vec.sub(cut.origin, body.origin), body.z)
        turn = vec.dot(cut.z, body.z)
        reach = sorted([shift + cut.low * turn, shift + cut.high * turn])
        if reach[0] > body.low + 1e-6 or reach[1] < body.high - 1e-6:
            return unknown
        loop = [_to_frame(c, cut, body) for c in cut.loops[0]]
        if any(closer_than(c, other, TOUCH_TOL) for c in loop for other in body.curves):
            return unknown
        inside = [_to_frame({"start": list(uv)}, cut, body)["start"] for uv in cut.samples()[:1]]
        if not inside or not body.region.covers(inside[0]):
            return unknown
        body.loops.append(loop)
        body.curves = [c for lp in body.loops for c in lp]
        body.region = Footprint({"loops": [{"curves": lp} for lp in body.loops]})
    return _edges(body) or unknown


def drawn_plainly(loops):
    """True when every curve of the loops is a line, an arc or a circle (the curves whose edges the copy can tell)."""
    return all(c.get("kind") in PLAIN_KINDS for loop in loops for c in loop)


def _edges(body):
    """Fill the corners and edges of a body; None when an outline does not close."""
    start = 0
    for loop in body.loops:
        found = _chains(loop)
        if found is None:
            return None
        body.corners += [(p, start + a, start + b) for p, a, b in found]
        start += len(loop)
    for n, curve in enumerate(body.curves):
        for end in ("low", "high"):
            body.edges.append(Edge("end", (end, n), True, curve=n, height=getattr(body, end)))
        if is_full(curve):
            body.edges.append(Edge("seam", (n, n), False, curve=n))
    for p, a, b in body.corners:
        smooth = vec.dot(_leaving(body.curves[a], p) + [0.0], _leaving(body.curves[b], p) + [0.0]) < -1 + 1e-6
        body.edges.append(Edge("side", (a, b), not smooth, corner=p))
    for n, curve in enumerate(body.curves):
        if curve["kind"] == "line":
            mid = [(curve["start"][0] + curve["end"][0]) / 2.0, (curve["start"][1] + curve["end"][1]) / 2.0]
            out = body.region.outward(n, mid)
            if out is None:
                return None
            body.normals[n] = body.lift(out)
    return body


def face_groups(body, turn):
    """`{face key: FaceGroup}` in Orca's terms; `turn` maps a capture direction to Orca's. None for a flat face too
    near Orca's split to call."""
    out = {}
    for key in ["low", "high"] + list(range(len(body.curves))):
        normal = body.normals.get(key)
        if normal is None:
            out[key] = LATERAL
            continue
        up = vec.unit(list(turn(normal)))[2]
        if abs(abs(up) - UP_SPLIT) < SPLIT_MARGIN:
            out[key] = None
        else:
            out[key] = TOP if up > UP_SPLIT else (BOTTOM if up < -UP_SPLIT else LATERAL)
    return out


def group_edges(body, groups, group):
    """Indices of the edges Orca takes for `group`, or None when a face of them is too near the split to call."""
    if group == ALL:
        return set(range(len(body.edges)))
    out = set()
    for n, edge in enumerate(body.edges):
        found = [groups[f] for f in edge.faces]
        if None in found:
            return None
        if group in found:
            out.add(n)
    return out


def _on(body, edge, uv, w):
    if edge.kind == "end":
        return abs(w - edge.height) <= POINT_TOL and curve_distance(body.curves[edge.curve], uv) <= POINT_TOL
    inside = body.low + POINT_TOL < w < body.high - POINT_TOL
    if edge.kind == "seam":
        return inside and curve_distance(body.curves[edge.curve], uv) <= POINT_TOL
    return inside and _same(uv, edge.corner)


def picked(body, records):
    """The edges of the copy that Fusion edge records name (each record's points all on one edge), or None when a
    record names no edge, or several, of the copy."""
    out = set()
    for record in records:
        found = None
        for n, edge in enumerate(body.edges):
            if all(_on(body, edge, *body.local(p)) for p in record.get("points") or []):
                if found is not None:
                    return None
                found = n
        if found is None or not record.get("points"):
            return None
        out.add(found)
    return out


def matching_group(body, turn, chosen):
    """The face group whose edges are exactly the chosen ones (a seam or smooth edge may be in or out), or None.
    All comes first, so a body whose side faces touch every edge reads as all edges."""
    groups = face_groups(body, turn)
    for group in (ALL, TOP, BOTTOM, LATERAL):
        taken = group_edges(body, groups, group)
        if taken is None:
            continue
        needed = {n for n in taken if body.edges[n].required}
        if needed <= chosen <= taken:
            return group, taken
    return None


def _corner_angle(body, p, a, b):
    """The angle (radians) of material at a corner between curves `a` and `b`."""
    d1, d2 = _leaving(body.curves[a], p), _leaving(body.curves[b], p)
    cos = max(-1.0, min(1.0, d1[0] * d2[0] + d1[1] * d2[1]))
    angle = math.acos(cos)
    if angle > math.pi - 1e-6:
        return math.pi
    bis = vec.unit([d1[0] + d2[0], d1[1] + d2[1], 0.0])
    probe = [p[0] + bis[0] * 1e-4, p[1] + bis[1] * 1e-4]
    return angle if body.region.covers(probe) else 2 * math.pi - angle


def _convex_arc(body, curve):
    point = polyline(curve)[len(polyline(curve)) // 2]
    c = curve["center"]
    toward = vec.unit([c[0] - point[0], c[1] - point[1], 0.0])
    return body.region.covers([point[0] + toward[0] * 1e-4, point[1] + toward[1] * 1e-4])


def room(body, size, ends):
    """None when every face keeps a margin after rounds of `size` in all (mm), else the reason. `ends` is how many
    ends of the extrusion lose `size` from their sides (0 to 2). The rule is kept on every curve: a round of an end's
    edges shrinks that end like a round of the side edges shrinks the sides."""
    if size <= SMALLEST:
        return "it is too small for Orca"
    need = ROOM * size
    if body.high - body.low <= need * max(ends, 1):
        return "the part is not tall enough for it"
    shrink = {n: 0.0 for n in range(len(body.curves))}
    for p, a, b in body.corners:
        angle = _corner_angle(body, p, a, b)
        cut = 1.0 / math.tan(angle / 2.0) if angle < math.pi - 1e-9 else 0.0
        shrink[a] += max(cut, 0.0)
        shrink[b] += max(cut, 0.0)
    for n, curve in enumerate(body.curves):
        if curve["kind"] == "line":
            length = math.hypot(curve["end"][0] - curve["start"][0], curve["end"][1] - curve["start"][1])
            if length <= need * shrink[n]:
                return "a side of the outline is too short for it"
        elif curve["kind"] in ("arc", "circle") and _convex_arc(body, curve) and curve["radius"] <= need:
            return "a rounded side of the outline is too tight for it"
    ends_of = {}
    for p, a, b in body.corners:
        ends_of.setdefault(a, []).append(p)
        ends_of.setdefault(b, []).append(p)
    for n in range(len(body.curves)):
        for m in range(n + 1, len(body.curves)):
            if any(_same(p, q) for p in ends_of.get(n, []) for q in ends_of.get(m, [])):
                continue
            if closer_than(body.curves[n], body.curves[m], 2.0 * need):
                return "two sides of the outline are too close together for it"
    return None


# ---- what changed the edges of a body ----------------------------------------------------------------------------

def finished(scope, feature, group, size, ends):
    """Record on a body (`context.Body`) a round or chamfer of `group` and `size` (mm) on the ends `ends` ("low",
    "high")."""
    scope.finishes.append({"feature": feature, "pieces": len(scope.solid.pieces), "group": group, "size": size,
                           "ends": set(ends)})


def changed(scope, feature):
    """Record on a body a step that changes its edges in a way the copy does not follow (a thread)."""
    scope.finishes.append({"feature": feature, "pieces": len(scope.solid.pieces), "group": None, "size": 0.0,
                           "ends": set()})


def earlier(scope, features):
    """The records of a body whose feature is still in the recipe `features` (a step that was taken back is not)."""
    held = {id(f) for f in features}
    return [r for r in scope.finishes if id(r["feature"]) in held]


# ---- the material a round or chamfer may have taken ----------------------------------------------------------------

def reach(body, size):
    """How far (mm) from a rounded edge a round or chamfer of `size` can take material: `size` from each face at an
    end edge (the ends meet the sides square), and up to `size / sin(a / 2)` from the corner at a side edge whose
    corner holds an angle `a` of material. The sharpest corner of the outline sets it for every edge."""
    widest = 1.0
    for p, a, b in body.corners:
        angle = _corner_angle(body, p, a, b)
        if 1e-6 < angle < math.pi - 1e-9:
            widest = max(widest, 1.0 / math.sin(angle / 2.0))
    return size * widest * REACH_MARGIN


class Rounded:
    """The material near the edges a round or chamfer took, as a shape (`span` along a line): within `distance` of
    an end plane and of an outline curve at that end (an end edge), or within `distance` of an outline corner at any
    height (a side edge). It stands in `solid.Solid.unsure`, so a later cut, hole or thread counts only material
    away from rounded edges (Orca may have rounded it away).

    `body` is the `Body` the edges belong to, made when its first shape was `base`; while a whole-body move
    (`Solid.moved`) carries the body, the lines are carried back through it. `alive` is false once the step that
    made the round is taken back."""

    def __init__(self, body, edges, distance, solid, base, alive):
        self.body, self.distance = body, distance
        self.ends = [(body.curves[e.curve], e.height) for e in edges if e.kind == "end"]
        self.corners = [e.corner for e in edges if e.kind == "side"]
        self.solid, self.base, self.alive = solid, base, alive

    def _carried(self, start, direction):
        """The line in the body's own place, or None when the body was changed in a way that cannot be followed."""
        piece = self.solid.pieces[0][1] if self.solid.pieces else None
        while piece is not self.base:
            if not (isinstance(piece, Moved) and isinstance(piece.shape, Solid) and piece.shape.pieces):
                return None
            rows = piece.rows
            start = [sum(rows[k][i] * (start[k] - piece.offset[k]) for k in range(3)) for i in range(3)]
            direction = [sum(rows[k][i] * direction[k] for k in range(3)) for i in range(3)]
            piece = piece.shape.pieces[0][1]
        return start, direction

    def _inside(self, uv, w):
        d, body = self.distance, self.body
        if any(math.hypot(uv[0] - c[0], uv[1] - c[1]) < d for c in self.corners) \
                and body.low - d < w < body.high + d:
            return True
        return any(abs(w - height) < d and curve_distance(curve, uv) < d for curve, height in self.ends)

    def span(self, start, direction):
        if not self.alive():
            return []
        carried = self._carried(list(start), list(direction))
        if carried is None:
            return [(-math.inf, math.inf)]
        start, direction = carried
        uv0, w0 = self.body.local(start)
        du, dv, dw = (vec.dot(direction, axis) for axis in (self.body.x, self.body.y, self.body.z))
        d = self.distance
        lo, hi = self.body.low - d, self.body.high + d
        if abs(dw) > 1e-12:
            t0, t1 = sorted(((lo - w0) / dw, (hi - w0) / dw))
        elif lo < w0 < hi:
            t0, t1 = _flat_reach(self.body, uv0, (du, dv), d)
        else:
            return []
        if abs(du) < 1e-12 and abs(dv) < 1e-12:
            return self._along_normal(uv0, w0, dw)
        return _sampled(lambda t: self._inside((uv0[0] + t * du, uv0[1] + t * dv), w0 + t * dw), t0, t1)

    def _along_normal(self, uv, w0, dw):
        """The spans of a line along the body's normal through `uv`, worked out exactly."""
        d, body = self.distance, self.body
        heights = []
        if any(math.hypot(uv[0] - c[0], uv[1] - c[1]) < d for c in self.corners):
            heights.append((body.low - d, body.high + d))
        heights += [(h - d, h + d) for curve, h in self.ends if curve_distance(curve, uv) < d]
        spans = [tuple(sorted(((a - w0) / dw, (b - w0) / dw))) for a, b in heights]
        return union(spans, [])


def _flat_reach(body, uv, d2, margin):
    """The part of a line in the end plane's direction that passes within `margin` of the outline's box."""
    points = [p for c in body.curves for p in polyline(c)]
    lo = [min(p[k] for p in points) - margin for k in range(2)]
    hi = [max(p[k] for p in points) + margin for k in range(2)]
    t0, t1 = -math.inf, math.inf
    for k in range(2):
        if abs(d2[k]) < 1e-12:
            if not lo[k] <= uv[k] <= hi[k]:
                return 0.0, 0.0
            continue
        a, b = sorted(((lo[k] - uv[k]) / d2[k], (hi[k] - uv[k]) / d2[k]))
        t0, t1 = max(t0, a), min(t1, b)
    return (t0, t1) if t1 > t0 else (0.0, 0.0)


def _sampled(inside, t0, t1):
    """The spans of [t0, t1] where `inside(t)` holds: samples, each change placed by halving."""
    if t1 <= t0:
        return []
    ts = [t0 + (t1 - t0) * k / _SAMPLES for k in range(_SAMPLES + 1)]
    states = [inside(t) for t in ts]
    out, begin = [], (t0 if states[0] else None)
    for k in range(1, len(ts)):
        if states[k] == states[k - 1]:
            continue
        a, b = ts[k - 1], ts[k]
        for _ in range(_HALVINGS):
            mid = (a + b) / 2.0
            if inside(mid) == states[k - 1]:
                a = mid
            else:
                b = mid
        # Widen each span to the outer side of its edge, so the doubt never falls short.
        if states[k]:
            begin = a
        else:
            out.append((begin, b))
            begin = None
    if begin is not None:
        out.append((begin, t1))
    return out


def only_rounded(solid, tool):
    """True when a tool meets the part's material only where a round or chamfer may have taken it."""
    return bool(solid.unsure) and not solid.meets(tool) and Solid(solid.pieces).meets(tool)


def unsure(scope, body, taken, size, alive):
    """Add to a body's shape the material the rounded edges `taken` (indices into `body.edges`) of `size` may have
    taken."""
    solid = scope.solid
    shape = Rounded(body, [body.edges[n] for n in taken], reach(body, size), solid, solid.pieces[0][1], alive)
    solid.unsure.append(shape)
    return shape
