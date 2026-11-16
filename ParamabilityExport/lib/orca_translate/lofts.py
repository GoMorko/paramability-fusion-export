"""Loft steps as Orca Loft features: a solid between two outlines.

Orca's Loft (`CadDocument::apply_feature`, `SketchEngine::make_loft`) builds one closed wire per outline sketch and
skins them with OCCT's `BRepOffsetAPI_ThruSections`; with `loft_ruled` the faces between two outlines are straight,
which is what Fusion makes between two outlines with free ends. Orca has no end conditions, rails or centre line, and
takes one loop per outline (no holes). OCCT joins two loops point to point in its own way, so the copy takes only the
outlines whose joins cannot differ:

- two circles: Orca's circle starts at the same place for the same plane normal, so both sketches are written with
  one normal and the wall joins each point to the point at the same angle (a cone, also an oblique one);
- two outlines of straight lines with the same corner count whose corners pair up one way only: OCCT joins the
  corners that lie closest together about the outlines' centres (seen live up to a turn of 40 degrees), and no other
  pairing may come close. A new body's measured volume must be the volume of that loft
  (`design_model.steps.loft`), since that shows Fusion paired them the same way; without a measured volume each
  corner must lie within a degree of its partner about the centres (a square to a smaller square, a frustum).

The outlines must lie in parallel planes, each on its own side of the other. Left out: other shapes or pairs of
shapes, holes, more than two outlines (Orca's loft through more is smooth in its own way), points, faces and loops of
the part as sections, end conditions other than free, rails, a centre line and closed lofts.

The outlines follow their sizes as extrude outlines do (a rectangle's `width` and `height`, a circle's `radius`).
Their sketch planes keep their place. The shape for later cuts (`Lofted`) is the section at each height: the two
outlines' joined points moved in a straight line.
"""
import math

from ..capture_model import gap_hints
from ..design_model.reach import placement_sizes
from ..design_model.steps.loft import matches, ruled_volumes
from ..design_model.steps.sweep import loop_polygon, made_volume
from ..geometry import vec
from ..geometry.footprint import polyline
from ..orca_recipe.enums import BooleanMode, FeatureType
from . import causes, sketch_sizes, steps
from ..design_model.values import Quantity
from ..design_model import words as shared
from .sketches import circle_of, outline_sketch, outlines_of
from .skip import Skip
from .solid import ADD, CUT, INTERSECT, ahead, box_of, traced
from .tools import OPERATIONS, data_of, feature, label

_SOLID_MODES = {"newBody": ADD, "join": ADD, "cut": CUT, "intersect": INTERSECT}
# Normals closer than this (the sine of their angle) are parallel; points closer than this (mm) to a plane are on it.
_PARALLEL = 1e-6
_PLANE_TOL = 1e-6
# A corner's nearest partner must turn about the centres by less than this (degrees), and every other pairing cost
# more than this share again.
_PAIR_TURN_DEG = 1.0
_PAIR_MARGIN = 0.05
# A step along a line through a lofted shape is no shorter than the line's reach through the shape's box over
# `_STEPS`, and `_HALVINGS` halvings place each crossing. A step stops this far (mm) short of where a wall could be.
_STEPS = 4096
_HALVINGS = 30
_WALL_SLACK = 1e-9

_SHAPES = ("Orca joins the two outlines of this loft in its own way, which can differ from Fusion, so it is left out "
           "(only two circles, or two outlines of straight lines whose corners pair up clearly, are copied).")


def _refusal(data):
    """A Skip for a loft setting the copy does not follow, else None."""
    operation = data.get("operation")
    if operation == "newComponent":
        return Skip("This loft makes a new component, which is not copied.", gap_hints.NEW_COMPONENT)
    if operation not in _SOLID_MODES:
        return Skip("This kind of loft is not copied.")
    if data.get("solid") is False:
        return Skip(shared.LOFT_SURFACE, gap_hints.SURFACE)
    flags = (data.get("solid"), data.get("closed"), data.get("rails"), data.get("sections"), data.get("profiles"))
    if any(flag is None for flag in flags) or not isinstance(data["sections"], list):
        return Skip(shared.LOFT_UNREAD)
    if data["closed"]:
        return Skip(shared.LOFT_CLOSED, gap_hints.LOFT_KIND)
    if data.get("centerline") or data["rails"]:
        return Skip("Orca's loft has no rails or centre line, so this loft is left out.", gap_hints.LOFT_KIND)
    sections = data["sections"]
    for section in sections:
        if not isinstance(section, dict) or section.get("end") is None:
            return Skip(shared.LOFT_UNREAD)
        if section.get("kind") != "profile":
            return Skip("Orca's loft takes sketch outlines only, so a loft to a point, a face or edges of the part "
                        "is left out.", gap_hints.LOFT_KIND)
        if section["end"] != "free":
            return Skip("Orca's loft cannot shape its ends (tangent or direction), so this loft is left out.",
                        gap_hints.LOFT_KIND)
    if len(sections) != 2:
        return Skip("Orca's loft through more than two outlines is smooth in its own way, so this loft is left out."
                    if len(sections) > 2 else shared.LOFT_FEW_OUTLINES, gap_hints.LOFT_KIND)
    return None


def _profile_problem(profile):
    if not isinstance(profile, dict):
        return "An outline of this loft could not be read."
    if profile.get("face"):
        return "This loft uses a face of the part as an outline, which the Orca copy does not copy yet."
    if profile.get("text"):
        return "Sketch text is not copied to Orca yet."
    if profile.get("foreign"):
        return "This loft uses a sketch of another component, which is not copied."
    if profile.get("space") not in (None, "sketch", "model") or not isinstance(profile.get("frame"), dict) \
            or outlines_of(profile) is None:
        return "An outline of this loft could not be read."
    return None


def _frame(profile):
    f = profile["frame"]
    z = vec.unit(f["z"])
    x = vec.unit(f["x"])
    return {"origin": [float(c) for c in f["origin"]], "x": x, "y": vec.cross(z, x), "z": z}


def _side(frame, points):
    """1 or -1 when all `points` lie on one side of the plane of `frame`, else 0."""
    heights = [vec.dot(vec.sub(p, frame["origin"]), frame["z"]) for p in points]
    if all(h > _PLANE_TOL for h in heights):
        return 1
    if all(h < -_PLANE_TOL for h in heights):
        return -1
    return 0


def _ring(profile):
    """The corners of a loop of straight lines in the part's coordinates, or None."""
    curves = outlines_of(profile).outer
    if len(curves) < 3 or any(c.get("kind") != "line" for c in curves):
        return None
    points = loop_polygon(curves)
    if not points or len(points) < 3:
        return None
    return [vec.frame_apply(profile["frame"], [u, v, 0.0]) for u, v in points]


def _mean(points):
    return [sum(p[i] for p in points) / len(points) for i in range(3)]


def _wound(ring, normal):
    """The ring counter clockwise about `normal`, its first corner kept first."""
    centre = _mean(ring)
    turn = sum(vec.dot(vec.cross(vec.sub(a, centre), vec.sub(b, centre)), normal)
               for a, b in zip(ring, ring[1:] + ring[:1]))
    return ring if turn > 0 else [ring[0]] + ring[:0:-1]


def _paired(first, second, normal):
    """`(second, clear)`: `second` turned so that its corner `i` joins corner `i` of `first` as Orca joins them (the
    pairing that puts the corners closest together about the centres, seen live up to a turn of 40 degrees), and
    whether that pairing is clear without a measured volume (each corner turned by under `_PAIR_TURN_DEG` from its
    partner). None when another pairing comes close, since Orca might pick either."""
    a = [vec.sub(p, _mean(first)) for p in first]
    b = [vec.sub(p, _mean(second)) for p in second]
    n = len(a)
    costs = [sum(vec.length(vec.sub(b[(i + s) % n], a[i])) ** 2 for i in range(n)) for s in range(n)]
    best = min(range(n), key=lambda s: costs[s])
    if any(s != best and costs[s] <= costs[best] * (1.0 + _PAIR_MARGIN) for s in range(n)):
        return None
    turns = [math.degrees(math.atan2(vec.dot(vec.cross(a[i], b[(i + best) % n]), normal),
                                     vec.dot(a[i], b[(i + best) % n]))) for i in range(n)]
    return [second[(i + best) % n] for i in range(n)], all(abs(t) <= _PAIR_TURN_DEG for t in turns)


class Lofted:
    """A ruled loft between two sections in parallel planes: `rings` are the two lists of joined points (3D), or
    `circles` the two `(centre, radius)` of round sections. The section at a height is the joined points moved in a
    straight line between the planes; `frame` is the first section's plane, its normal toward the second.

    A line is read in steps no longer than the distance to the nearest wall allows (`solid.traced`), so a thin part of
    the shape is not stepped over: `drift` is how far (mm) any point of a section's wall moves in the plane from one
    end to the other, which bounds how fast that distance changes with the height."""

    def __init__(self, frame, height, rings=None, circles=None):
        self.frame, self.height = frame, float(height)
        self.rings, self.circles = rings, circles
        if circles is not None:
            (c0, r0), (c1, r1) = circles
            a, b = self._flat(c0), self._flat(c1)
            self._centre, self._centre_move = (a[0], a[1]), (b[0] - a[0], b[1] - a[1])
            self._radius, self._radius_change = float(r0), float(r1) - float(r0)
            self.drift = math.hypot(*self._centre_move) + abs(self._radius_change)
        else:
            flat = [(self._flat(a), self._flat(b)) for a, b in zip(*rings)]
            self._corners = [((a[0], a[1]), (b[0] - a[0], b[1] - a[1])) for a, b in flat]
            self.drift = max(math.hypot(*move) for _, move in self._corners)

    def _flat(self, p):
        d = vec.sub(p, self.frame["origin"])
        return vec.dot(d, self.frame["x"]), vec.dot(d, self.frame["y"]), vec.dot(d, self.frame["z"])

    def _probe(self, p):
        """Whether `p` is inside, with two levels that are 0 on the walls and below 0 inside them: `side`, the signed
        distance in the plane to the section at that height (the nearer end's section past the ends), and `end`, the
        distance past the nearer end plane (negative between them)."""
        u, v, w = self._flat(p)
        end = max(-w, w - self.height)
        t = min(1.0, max(0.0, w / self.height))
        if self.circles is not None:
            cu, cv = self._centre[0] + self._centre_move[0] * t, self._centre[1] + self._centre_move[1] * t
            side = math.hypot(u - cu, v - cv) - (self._radius + self._radius_change * t)
        else:
            ring = [(a[0] + move[0] * t, a[1] + move[1] * t) for a, move in self._corners]
            edges = list(zip(ring, ring[1:] + ring[:1]))
            gap = min(_segment_distance((u, v), a, b) for a, b in edges)
            side = -gap if _encloses(edges, u, v) else gap
        return side <= 0.0 and end <= 0.0, side, end

    def bounds(self):
        if self.circles is None:
            return box_of(p for ring in self.rings for p in ring)
        z = self.frame["z"]
        reach = [math.sqrt(max(0.0, 1.0 - z[i] ** 2)) for i in range(3)]
        return {"min": [min(c[i] - r * reach[i] for c, r in self.circles) for i in range(3)],
                "max": [max(c[i] + r * reach[i] for c, r in self.circles) for i in range(3)]}

    def span(self, start, direction):
        box = self.bounds()
        lo, hi = -math.inf, math.inf
        for i in range(3):
            if abs(direction[i]) < 1e-12:
                if not box["min"][i] - 1e-9 <= start[i] <= box["max"][i] + 1e-9:
                    return []
                continue
            t0, t1 = (box["min"][i] - start[i]) / direction[i], (box["max"][i] - start[i]) / direction[i]
            lo, hi = max(lo, min(t0, t1)), min(hi, max(t0, t1))
        if not hi > lo:
            return []
        # Per unit of t, `side` changes at most by the move in the plane plus the drift of the walls with the height,
        # and `end` by the move along the normal. Inside, the answer holds until either level can reach 0; outside,
        # until every level above 0 can.
        du, dv, dw = (vec.dot(direction, self.frame[k]) for k in ("x", "y", "z"))
        side_rate, end_rate = math.hypot(du, dv) + abs(dw) * self.drift / self.height, abs(dw)

        def probe(t):
            inside, side, end = self._probe(vec.add(start, vec.scale(direction, t)))
            clear = (ahead(abs(side) - _WALL_SLACK, side_rate), ahead(abs(end) - _WALL_SLACK, end_rate))
            if inside:
                return True, min(clear)
            return False, max((a for a, level in zip(clear, (side, end)) if level > 0), default=0.0)

        return traced(probe, lo, hi, _HALVINGS, _STEPS)


def _segment_distance(p, a, b):
    """The distance in the plane from `p` to the segment from `a` to `b`."""
    ex, ey = b[0] - a[0], b[1] - a[1]
    length2 = ex * ex + ey * ey
    s = 0.0 if length2 <= 0.0 else min(1.0, max(0.0, ((p[0] - a[0]) * ex + (p[1] - a[1]) * ey) / length2))
    return math.hypot(p[0] - a[0] - s * ex, p[1] - a[1] - s * ey)


def _encloses(edges, u, v):
    """True when `(u, v)` lies inside the polygon of `edges` (even-odd rule)."""
    inside = False
    for (x0, y0), (x1, y1) in edges:
        if (y0 > v) != (y1 > v) and u < x0 + (v - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _shape(item, data, profiles, frames):
    """`(Lofted, circles)`: the shape of the loft, and whether its outlines are two circles; or a Skip."""
    outlines = [outlines_of(p) for p in profiles]
    if any(o.holes for o in outlines):
        return Skip("Orca's loft takes outlines without holes, so a loft of outlines with holes is left out.",
                    causes.OUTLINE_HOLES)
    normal = frames[0]["z"]
    if vec.length(vec.cross(normal, frames[1]["z"])) > _PARALLEL:
        return Skip("The outlines of this loft are not in parallel planes, which the Orca copy does not copy yet.",
                    causes.LOFT_SHAPE)
    points = [[vec.frame_apply(p["frame"], [u, v, 0.0]) for c in o.outer for u, v in polyline(c)]
              for p, o in zip(profiles, outlines)]
    if not (_side(frames[0], points[1]) and _side(frames[1], points[0])):
        return Skip(shared.LOFT_CROSSING)
    height = vec.dot(vec.sub(frames[1]["origin"], frames[0]["origin"]), normal)
    base = frames[0] if height > 0 else dict(frames[0], y=vec.scale(frames[0]["y"], -1.0),
                                             z=vec.scale(normal, -1.0))
    circles = [circle_of(o.outer) for o in outlines]
    if all(c is not None for c in circles):
        placed = [(vec.frame_apply(p["frame"], [c[0][0], c[0][1], 0.0]), c[1]) for p, c in zip(profiles, circles)]
        return Lofted(base, abs(height), circles=placed), True
    rings = [_ring(p) for p in profiles]
    if any(r is None for r in rings) or len(rings[0]) != len(rings[1]):
        return Skip(_SHAPES, causes.LOFT_SHAPE)
    first, second = (_wound(r, base["z"]) for r in rings)
    found = _paired(first, second, base["z"])
    if found is None:
        return Skip(_SHAPES, causes.LOFT_SHAPE)
    second, clear = found
    # A new body's measured volume tells how Fusion paired the corners; without it only a clear pairing is copied.
    made = made_volume(item, data) if data.get("operation") == "newBody" else None
    if made is not None:
        volumes = ruled_volumes(profiles)
        if volumes is None or not matches(volumes, made):
            return Skip("Fusion joins the corners of the two outlines of this loft another way than Orca does, so "
                        "it is not copied.", causes.LOFT_SHAPE)
    elif not clear:
        return Skip(_SHAPES, causes.LOFT_SHAPE)
    return Lofted(base, abs(height), rings=[first, second]), False


def _same_normal(made, normal, place):
    """Turn a circle's sketch plane over when its normal points against `normal` (capture coordinates): Orca starts
    a circle at a place set by its plane normal, so both circles of a loft need the same one."""
    plane = made.feature.plane
    if vec.dot(list(plane.normal), list(place.direction(normal))) > 0:
        return
    plane.normal = tuple(-c for c in plane.normal)
    plane.y_axis = tuple(-c for c in plane.y_axis)


def loft(ctx, item):
    """The Orca features of a loft, or a Skip."""
    data = data_of(item)
    refused = _refusal(data)
    if refused is not None:
        return refused
    operation = data["operation"]
    if not ctx.has_body and operation in ("cut", "intersect"):
        return Skip("The part this %s works on is not in the copy." % ("cut" if operation == "cut" else "intersect"),
                    gap_hints.AFTER_GAP)
    try:
        profiles = [data["profiles"][s["profile"]] for s in data["sections"]]
    except (IndexError, KeyError, TypeError):
        return Skip(shared.LOFT_UNREAD)
    for profile in profiles:
        problem = _profile_problem(profile)
        if problem:
            return Skip(problem)
    frames = [_frame(p) for p in profiles]
    found = _shape(item, data, profiles, frames)
    if isinstance(found, Skip):
        return found
    shape, round_ends = found
    mode = _SOLID_MODES[operation]
    if mode != ADD and not ctx.solid.meets(shape):
        return Skip(*steps.misses_reason(ctx, "cut" if mode == CUT else "intersect"))

    name = label(item)
    written = []
    for n, profile in enumerate(profiles):
        made = outline_sketch(outlines_of(profile), profile["frame"], ctx.place, sketch_sizes.sketch_formulas(ctx, profile),
                              "%s outline %d" % (name, n + 1))
        if made is None:
            return Skip("An outline of this loft has a curve the Orca copy cannot draw yet.")
        if round_ends:
            _same_normal(made, shape.frame["z"], ctx.place)
        written.append((profile, made))
    sketch_sizes.sketch_doubts(ctx, item, [(p, outlines_of(p)) for p in profiles],
                        [(m, outlines_of(p), p) for p, m in written])
    items = ctx.capture.get("items") or []
    for profile in profiles:
        moving = placement_sizes(ctx.table, items, profile, item.get("index")) if ctx.table is not None else []
        ctx.doubt(moving, "%s: an outline sits on a plane or face that moves with it, and Orca cannot move a sketch "
                  "plane with a variable" % name)

    out, refs = [], []
    for profile, made in written:
        refs.append(ctx.add(made.feature))
        out.append(made.feature)
        for field, (formula, reads) in made.bound.items():
            ctx.bind(made.feature, field, Quantity(getattr(made.feature, field), formula, reads),
                     "%s %s" % (made.feature.name, field))
        made.feature.thread_major_nominal = made.feature.pattern_inclusive = True
    step = feature(FeatureType.LOFT, name, loft_profile_refs=refs, loft_ruled=True)
    step.mode = BooleanMode.NEW if not ctx.has_body else OPERATIONS.get(operation, BooleanMode.ADD)
    ctx.add(step)
    ctx.has_body = True
    ctx.solid.add(mode, shape)
    out.append(step)
    return out


HANDLERS = {"LoftFeature": loft}
