"""Sketch text in an extrude as Orca's imported regions: each letter a region of polygon loops (its outer loop, then
its holes) in the sketch plane, extruded by a feature of its own.

Orca builds a sketch whose `imported_regions` is not empty from those regions alone (its entities are not drawn), so
the letters get a sketch of their own. Orca's region extrude (`SketchEngine::make_extrude_regions`) reads the
distance and the flip of a Blind extrude; Symmetric and Two sides are both built symmetric, Through all as symmetric
1e5 mm, and a taper is not read. So the copy keeps to one side (Blind, a long Blind for a one way through all, or Orca's
through all when nothing of the part lies behind the sketch) and Symmetric without taper.

Orca skips a region whose loop it cannot build and gives no error, so each loop is checked first: at least three
points more than `JOIN_TOL` apart once points that close are merged (Orca merges them too), no loop that crosses or
touches itself or another loop, every hole inside its letter's outer loop and outside the other holes, and no letter
inside the material of another. A step whose letters fail any check is left out.

Curves are written as polygons: lines by their ends, arcs and circles with points close enough that no chord leaves
the arc by more than `CHORD_TOL`, free curves from their samples (within 0.0005 mm of the curve) thinned to the rest of
that tolerance. Only the depth follows variables: the size and place of the text keep their numbers, and the sizes
that move them are marked.
"""
import math

from ..design_model import reach
from ..geometry import vec
from ..geometry.footprint import arc_span, closed_chain
from ..orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType
from ..orca_recipe.feature import CadFeature
from . import causes, extents
from .sketch_sizes import profile_sizes
from .sketches import graph_for
from .skip import Skip
from .solid import ADD, CUT, INTERSECT, Prism

# How far a written polygon may leave the curve it stands for (mm).
CHORD_TOL = 0.005
# What the capture's samples of a free curve may be off the curve (mm, `fusion_reader.read_sketch._CHORD_TOL_MM`).
SAMPLE_TOL = 0.0005
# Orca's sketch joint tolerance (`kSketchJoinTol`): points closer than this are merged into one.
JOIN_TOL = 1e-3
# Two loops nearer than this (mm) count as touching.
TOUCH_TOL = 1e-6
# Frames of the letters farther apart than this are not one sketch plane.
FRAME_TOL = 1e-6
# Length of a one way extrude that stands for through all (mm), as `steps.LONG`.
LONG = 1000.0
MIN_AREA = 1e-6

_MODES = {"join": BooleanMode.ADD, "cut": BooleanMode.CUT, "intersect": BooleanMode.INTERSECT}
_SOLID_MODES = {"newBody": ADD, "join": ADD, "cut": CUT, "intersect": INTERSECT}

_EXTENT = ("Orca builds text only to one side or symmetric, without taper, so this extrude of text is left out.")
_MIXED = ("This extrude uses sketch text together with other outlines, and the Orca copy writes text only in a "
          "sketch of its own.")


def _label(item):
    return item.get("name") or "the step"


# ---- curves to polygons -------------------------------------------------------------------------------------------

def _arc_points(curve):
    """Points of an arc or circle link (start to end), with no chord further than CHORD_TOL from the arc."""
    c, r = curve["center"], float(curve["radius"])
    if curve["kind"] == "circle":
        a0, sweep = 0.0, 2 * math.pi
    else:
        a0, sweep = arc_span(curve)
    step = 2.0 * math.acos(max(-1.0, 1.0 - CHORD_TOL / r)) if r > CHORD_TOL else math.pi
    count = max(1, int(math.ceil(abs(sweep) / step)))
    if curve["kind"] == "circle":
        count = max(count, 3)
    points = [[c[0] + r * math.cos(a0 + sweep * k / count), c[1] + r * math.sin(a0 + sweep * k / count)]
              for k in range(count + 1)]
    if curve["kind"] == "arc":
        points[0], points[-1] = list(curve["start"]), list(curve["end"])
    return points


def _gap(p, a, b):
    """Distance from `p` to the segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    size = dx * dx + dy * dy
    t = 0.0 if size <= 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / size))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def thinned(points, tol):
    """The points a polyline keeps when each left out point lies within `tol` of the chord that replaces it
    (Douglas and Peucker), first and last kept."""
    if len(points) <= 2:
        return [list(p) for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    spans = [(0, len(points) - 1)]
    while spans:
        lo, hi = spans.pop()
        far, at = -1.0, None
        for k in range(lo + 1, hi):
            gap = _gap(points[k], points[lo], points[hi])
            if gap > far:
                far, at = gap, k
        if at is not None and far > tol:
            keep[at] = True
            spans += [(lo, at), (at, hi)]
    return [list(p) for p, kept in zip(points, keep) if kept]


def _link_points(link):
    """Points of one chain link from its start to its end, or None for a curve the copy cannot write as a polygon."""
    kind = link.get("kind")
    if kind == "line":
        return [list(link["start"]), list(link["end"])]
    if kind in ("arc", "circle"):
        return _arc_points(link)
    if kind == "other" and isinstance(link.get("samples"), list) and len(link["samples"]) >= 2 \
            and not link.get("truncated"):
        return thinned(link["samples"], CHORD_TOL - SAMPLE_TOL)
    return None


def _merged(points):
    """The points with each one within JOIN_TOL of the one kept before it dropped, and the closing points that
    repeat the first: what Orca keeps of a contour."""
    out = []
    for p in points:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > JOIN_TOL:
            out.append((float(p[0]), float(p[1])))
    while len(out) >= 2 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= JOIN_TOL:
        out.pop()
    return out


def _area(ring):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))


def loop_polygon(curves):
    """The polygon of one loop of capture curves (a list of (x, y), no closing point), or None when the curves do not
    close, a curve cannot be written, or fewer than three points or no area are left."""
    if not curves:
        return None
    if len(curves) == 1 and curves[0].get("kind") == "circle":
        chain = [curves[0]]
    elif any(c.get("kind") not in ("line", "arc", "other") for c in curves):
        return None
    else:
        chain = closed_chain(curves)
        if chain is None:
            return None
    points = []
    for link in chain:
        found = _link_points(link)
        if found is None:
            return None
        points += found if not points else found[1:]
    ring = _merged(points)
    if len(ring) < 3 or abs(_area(ring)) <= MIN_AREA:
        return None
    return ring


# ---- checks Orca does not report ----------------------------------------------------------------------------------

def _segments(ring):
    return list(zip(ring, ring[1:] + ring[:1]))


def _box(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _turn(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segment_gap(s, t):
    """Distance between two segments: zero when they cross."""
    (a, b), (c, d) = s, t
    d1, d2, d3, d4 = _turn(c, d, a), _turn(c, d, b), _turn(a, b, c), _turn(a, b, d)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return 0.0
    return min(_gap(a, c, d), _gap(b, c, d), _gap(c, a, b), _gap(d, a, b))


def _inside(ring, p):
    crossings = 0
    for a, b in _segments(ring):
        if (a[1] > p[1]) != (b[1] > p[1]):
            if a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]) > p[0]:
                crossings += 1
    return crossings % 2 == 1


def _crossing(rings):
    """True when two segments of the rings that are not neighbours in one ring come nearer than TOUCH_TOL, or two
    neighbours fold back onto each other."""
    segments = []
    for n, ring in enumerate(rings):
        count = len(ring)
        for k, (a, b) in enumerate(_segments(ring)):
            box = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
            segments.append((box, n, k, count, (a, b)))
    segments.sort(key=lambda s: s[0][0])
    for i, (box, n, k, count, seg) in enumerate(segments):
        for at in range(i + 1, len(segments)):
            other_box, m, j, _, other = segments[at]
            if other_box[0] > box[2] + TOUCH_TOL:
                break
            if other_box[1] > box[3] + TOUCH_TOL or other_box[3] < box[1] - TOUCH_TOL:
                continue
            if n == m and (abs(k - j) == 1 or abs(k - j) == count - 1):
                # Neighbours share an end; they may not run back along each other.
                (a, b), (c, d) = (seg, other) if (k + 1) % count == j else (other, seg)
                if abs(_turn(a, b, d)) <= TOUCH_TOL * math.hypot(b[0] - a[0], b[1] - a[1]) and \
                        (b[0] - a[0]) * (d[0] - c[0]) + (b[1] - a[1]) * (d[1] - c[1]) < 0:
                    return True
                continue
            if _segment_gap(seg, other) <= TOUCH_TOL:
                return True
    return False


def _in_material(region, p):
    return _inside(region[0], p) and not any(_inside(hole, p) for hole in region[1:])


def region_problem(regions):
    """Why Orca would build the regions otherwise than they are drawn (a plain reason), or None."""
    if _crossing([ring for region in regions for ring in region]):
        return "the outlines of its letters cross or touch"
    for region in regions:
        for n, hole in enumerate(region[1:]):
            if not _inside(region[0], hole[0]):
                return "a hole of a letter lies outside the letter"
            if any(_inside(other, hole[0]) for other in region[1 + n + 1:]) or \
                    any(_inside(hole, other[0]) for other in region[1 + n + 1:]):
                return "a hole of a letter lies inside another hole"
    boxes = [_box(region[0]) for region in regions]
    for i, a in enumerate(regions):
        for j, b in enumerate(regions):
            if i == j:
                continue
            ba, bb = boxes[i], boxes[j]
            if bb[0] > ba[2] or bb[2] < ba[0] or bb[1] > ba[3] or bb[3] < ba[1]:
                continue
            if _in_material(a, b[0][0]):
                return "a letter lies inside another letter"
    return None


def regions_of(profiles):
    """The regions of text profile records (each a list of loops, the outer loop first, in the sketch's 2D frame), or
    a plain reason why they cannot be written."""
    regions = []
    for profile in profiles:
        loops = profile.get("loops") or []
        outer = [loop for loop in loops if loop.get("outer")]
        if len(outer) != 1:
            return "a letter does not have exactly one outer outline"
        region = []
        for loop in outer + [loop for loop in loops if not loop.get("outer")]:
            ring = loop_polygon(loop.get("curves") or [])
            if ring is None:
                return "a curve of a letter cannot be written, or a letter outline is too small"
            # Outer loops counter clockwise, holes clockwise (Orca sorts the way out by itself as well).
            if (_area(ring) > 0) != (not region):
                ring.reverse()
            region.append(ring)
        regions.append(region)
    if not regions:
        return "no letter could be read"
    return region_problem(regions) or regions


# ---- the extrude --------------------------------------------------------------------------------------------------

def _same_frame(a, b):
    return all(abs(float(x) - float(y)) <= FRAME_TOL for key in ("origin", "x", "y", "z")
               for x, y in zip(a[key], b[key]))


def _heights(side):
    if side.end == ExtrudeEnd.THROUGH_ALL:
        return -math.inf, math.inf
    if side.through:
        return (-LONG, 0.0) if side.flip else (0.0, LONG)
    low, high = side.ends()
    return low.n, high.n


def _lines(ring):
    return [{"kind": "line", "start": list(a), "end": list(b)} for a, b in _segments(ring)]


def _holds_projection(record):
    """True when the sketch graph holds geometry projected from the part (not only origin geometry), or may: no
    graph."""
    if record is None:
        return True
    for entry in list(record.get("points") or []) + list(record.get("curves") or []):
        reference = entry.get("reference") if isinstance(entry, dict) else None
        if isinstance(reference, dict) and not reference.get("origin"):
            return True
    return False


def _mark_kept(ctx, item, profiles):
    """Mark the sizes that move the text in Fusion: the sketch's dimensions, its plane, and geometry projected into
    it. Orca keeps the letters where and as large as they are now."""
    items = ctx.capture.get("items") or []
    why = "%s: its text keeps its place and size in Orca, which cannot move or resize text with a variable" % (
        _label(item))
    for profile in profiles:
        ctx.doubt(profile_sizes(ctx, profile), why)
        ctx.doubt(reach.sketch_plane_sizes(ctx.table, items, item, profile),
                  "%s: its sketch sits on a plane or face that moves with it, and Orca cannot move a sketch plane "
                  "with a variable" % _label(item))
        if ctx.table is not None and _holds_projection(graph_for(ctx.capture, profile)):
            ctx.doubt(reach.projection_sizes(ctx.table, items, item, profile.get("sketch") or ""), why)


def extrude(ctx, item, profiles, sides, shift, operation):
    """The Orca features of an extrude of sketch text (`profiles`, its text records), or a Skip. `sides` are the
    extrude's `steps._Side`s, `shift` how far it starts from its sketch plane (mm)."""
    from .steps import misses_reason  # steps hands its text extrudes to this module

    if not all(p.get("text") for p in profiles):
        return Skip(_MIXED, causes.TEXT_OUTLINE)
    if len(sides) != 1 or sides[0].taper or sides[0].end not in (
            ExtrudeEnd.BLIND, ExtrudeEnd.SYMMETRIC, ExtrudeEnd.THROUGH_ALL):
        return Skip(_EXTENT, causes.TEXT_EXTENT)
    side = sides[0]
    frame = profiles[0]["frame"]
    if any(not _same_frame(frame, p["frame"]) for p in profiles[1:]):
        return Skip("The letters of this text lie in more than one sketch plane, which is not copied to Orca yet.",
                    causes.TEXT_OUTLINE)
    regions = regions_of(profiles)
    if isinstance(regions, str):
        return Skip("This text is not copied to Orca: %s, and Orca would build such letters otherwise or leave one out "
                    "without an error."
                    % regions, causes.TEXT_OUTLINE)
    if not ctx.has_body and len(regions) > 1:
        return Skip("Text of several letters that starts the part is not copied to Orca yet.", causes.TEXT_OUTLINE)
    if shift:
        frame = dict(frame, origin=vec.add(frame["origin"], vec.scale(vec.unit(frame["z"]), shift)))
    low, high = _heights(side)
    shapes = [Prism(frame, [_lines(ring) for ring in region], low, high) for region in regions]
    if operation in ("cut", "intersect"):
        kept = [n for n, shape in enumerate(shapes) if ctx.solid.meets(shape)]
        if not kept:
            return Skip(*misses_reason(ctx, "cut" if operation == "cut" else "intersect"))
        if len(kept) < len(shapes):
            ctx.notes.append("%s: %d of its letters do not meet the part as the Orca copy builds it and are left "
                             "out." % (_label(item), len(shapes) - len(kept)))
        regions, shapes = [regions[n] for n in kept], [shapes[n] for n in kept]
    _mark_kept(ctx, item, profiles)

    name = _label(item)
    plane = ctx.place.plane(frame["origin"], frame["x"], frame["y"], frame["z"])
    sketch = CadFeature(type=FeatureType.SKETCH, name=name + " text", plane=plane,
                        imported_regions=[[list(ring) for ring in region] for region in regions],
                        thread_major_nominal=True, pattern_inclusive=True)
    feature = CadFeature(type=FeatureType.EXTRUDE, name=name, sketch_ref=ctx.add(sketch), extrude_end=side.end,
                         flip=side.flip, symmetric=side.end == ExtrudeEnd.SYMMETRIC, thread_major_nominal=True,
                         pattern_inclusive=True)
    feature.mode = BooleanMode.NEW if not ctx.has_body else _MODES.get(operation, BooleanMode.ADD)
    if side.distance is not None:
        ctx.bind(feature, "distance", side.distance, "%s distance" % name)
    ctx.add(feature)
    ctx.has_body = True
    for shape in shapes:
        ctx.solid.add(_SOLID_MODES.get(operation, ADD), shape)
        if side.end != ExtrudeEnd.THROUGH_ALL and not side.through:
            shape.ends = side.ends(feature)
    extents.guard(ctx, sketch, feature, side, shapes[0].loops[0])
    return [sketch, feature]
