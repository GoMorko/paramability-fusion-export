"""Sketch values that follow sizes, read from the probe's motion file (`probe.motion`).

The probe measures each value the translator writes for a sketch (loop numbers, the sketch plane, hole points, revolve
axis points) at other size settings and fits it as `Affine` (a sum over Fusion parameters) or marks it `Stuck`. Here
the values of one outline are looked up by key (`<item>/p<profile>/l<loop>/<field path>`), combined where the
translator writes a value the probe did not key (outlines merged from several profiles, rect corners, points picked on
an outline) and written as formulas. A stuck value that is written fixes its sizes, with the probe's cause. A value of
a sketch the probe did not measure (`Motion.unmeasured`) is stuck the same way for the sizes behind that sketch.

Without a motion file, or with `OPTIMISTIC`, nothing here runs and the sketch is written as numbers.
"""
import math

from ..probe import keys
from ..probe.motion import CURVE, UNREAD, UNTRIED, Affine, Stuck
from . import notes
from .curved import Curved, combine, names_of
from .footprint import nearest_point
from .loops import profile_loops
from .result import Refusal
from .sizes import unmeasured_sizes
from .sketch_crossings import Sources, keeps_order
from .values import Quantity, stays_positive

POSITIVE_FIELDS = ("width", "height", "radius", "radiusX", "radiusY")
_SKIP = ("angleDeg",)
# How far the rendered formula may be from the captured number before the value is treated as unread.
VALUE_TOL = 1e-3
# Points of merged outlines come from the same sketch curves, so they match closely; picks are measured.
MATCH_TOL = 1e-6
PICK_TOL = 1e-3
SAME_TOL = 1e-4
# The cause of a pick on a curved outline that changes shape (its reason names the step).
BENDS = "bends"


def active(ctx):
    """True when sketch values follow sizes in this walk."""
    motion = getattr(ctx, "motion", None)
    return ctx.table is not None and motion is not None and not motion.optimistic


def _free_sizes(table, names):
    out = []
    for name in names:
        out.extend(table.depends(name))
    return tuple(dict.fromkeys(out))


def movers(table, value):
    """The free sizes that move a raw value (Affine, Curved or Stuck)."""
    return _free_sizes(table, names_of(value))


def raw(ctx, key, number, sketch=""):
    """The raw value of `key` in the sketch named `sketch`: the probe's Affine or Stuck, or the captured number as a
    constant when the sketch was measured and the value did not move. A value of a sketch the probe did not measure
    is stuck for the sizes behind that sketch. A stuck value whose sizes are all fixed by now follows what the other
    sizes do (`rest`), else stands still."""
    found = ctx.motion.get(key)
    if found is None:
        names = unmeasured_sizes(ctx.table, ctx.motion, sketch)
        found = Stuck(names, UNTRIED, sketch) if names else None
    if found is None:
        return Affine(number)
    if isinstance(found, Stuck) and not movers(ctx.table, found):
        return found.rest if found.rest is not None else Affine(number)
    return found


def same(a, b):
    """True when two raw values move alike (both constant, or the same terms) and agree within SAME_TOL."""
    if not isinstance(a, Affine) or not isinstance(b, Affine):
        return False
    if set(a.terms) != set(b.terms) or any(abs(a.terms[k] - b.terms[k]) > 1e-9 for k in a.terms):
        return False
    return abs(a.const - b.const) <= SAME_TOL


def fix_stuck(ctx, stuck):
    ctx.doubt(movers(ctx.table, stuck), notes.stuck_reason(stuck.cause, stuck.sketch))


def rendered(table, value, number):
    """A raw value as a Quantity whose number is the captured `number`, or a Stuck when it cannot be written: stuck
    already, a parameter that does not translate, or a formula that misses the captured number."""
    if isinstance(value, Stuck):
        return value
    if value.is_constant:
        return Quantity(number)
    q = value.render(table)
    if isinstance(q, Stuck) or not q.sized:
        return q if isinstance(q, Stuck) else Quantity(number)
    if abs(q.n - number) > VALUE_TOL:
        return Stuck(q.reads, UNREAD, value.sketch)
    return Quantity(number, q.text, q.reads)


def quantity(ctx, value, number, positive=False):
    """The Quantity a raw value is written as. Its number stays the captured `number`. A stuck value, a formula that
    misses the captured number, or a length that would reach zero fixes its sizes and writes the number."""
    q = rendered(ctx.table, value, number)
    if isinstance(q, Stuck):
        fix_stuck(ctx, q)
        return Quantity(number)
    if positive and q.sized and not stays_positive(ctx.table, q):
        ctx.doubt(q.reads, notes.shrinks_reason(value.sketch))
        return Quantity(number)
    return q


# ---- loops as raw values ----------------------------------------------------------------------------------------

def _map(node, path, fn):
    """`node` with each number replaced by `fn(path, number)` (path as "center.0"); `angleDeg` is kept."""
    if isinstance(node, dict):
        return {k: (v if k in _SKIP else _map(v, path + [k], fn)) for k, v in node.items()}
    if isinstance(node, list):
        return [_map(v, path + [str(at)], fn) for at, v in enumerate(node)]
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return fn(".".join(path), float(node))
    return node


def _pair(node, other, fn, path=()):
    """`node` with each number replaced by `fn(field, number, raw)`, `raw` the value at the same place in `other`."""
    if isinstance(node, dict):
        return {k: (v if k in _SKIP else _pair(v, other[k], fn, path + (k,))) for k, v in node.items()}
    if isinstance(node, list):
        return [_pair(v, other[at], fn, path) for at, v in enumerate(node)]
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return fn(path[-1] if path else "", float(node), other)
    return node


def _keyed_loops(ctx, prefix, loops, sketch=""):
    return [_map(loop, [], lambda path, n, k=k: raw(ctx, keys.loop_field(prefix, k, path), n, sketch))
            for k, loop in enumerate(loops)]


def _rect_axes(loop):
    angle = math.radians(loop.get("angleDeg", 0.0))
    c, s = math.cos(angle), math.sin(angle)
    if abs(s) < 1e-15:
        c, s = math.copysign(1.0, c), 0.0
    return (c, s), (-s, c)


def _rect_corners(loop, raw_loop, sketch=""):
    """[(uv, (x, y))] of a rect's corners, numbers and raw values."""
    u, v = _rect_axes(loop)
    out = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        uv = [loop["center"][i] + sx * loop["width"] / 2 * u[i] + sy * loop["height"] / 2 * v[i] for i in range(2)]
        xy = tuple(combine([(1.0, raw_loop["center"][i]), (sx * u[i] / 2, raw_loop["width"]),
                            (sy * v[i] / 2, raw_loop["height"])], sketch) for i in range(2))
        out.append((uv, xy))
    return out


class Anchors:
    """The points of written loops with their raw values: corners and arc points, and circles and ellipses."""

    def __init__(self, sketch=""):
        self.sketch = sketch
        self.points = []   # (uv, (x, y))
        self.rounds = []   # (loop numbers, raw loop) of circles and ellipses

    def add(self, loop, raw_loop):
        kind = loop["kind"]
        if kind == "polygon":
            self.points += [(p, tuple(r)) for p, r in zip(loop["points"], raw_loop["points"])]
        elif kind == "profile":
            self.points.append((loop["start"], tuple(raw_loop["start"])))
            for seg, rseg in zip(loop["segments"], raw_loop["segments"]):
                self.points.append((seg["to"], tuple(rseg["to"])))
                if "through" in seg:
                    self.points.append((seg["through"], tuple(rseg["through"])))
        elif kind == "rect":
            self.points += _rect_corners(loop, raw_loop, self.sketch)
        else:
            self.rounds.append((loop, raw_loop))

    def point(self, uv, tol=MATCH_TOL):
        """The raw (x, y) of the anchor at `uv`, or None."""
        best = None
        for p, xy in self.points:
            gap = math.hypot(p[0] - uv[0], p[1] - uv[1])
            if gap <= tol and (best is None or gap < best[0]):
                best = (gap, xy)
        return None if best is None else best[1]

    def round_at(self, center, size, tol=MATCH_TOL):
        """The (numbers, raw) of the circle or ellipse at `center` whose radius (or larger radius) is `size`."""
        for loop, raw_loop in self.rounds:
            big = loop.get("radius", max(loop.get("radiusX", 0.0), loop.get("radiusY", 0.0)))
            if math.hypot(loop["center"][0] - center[0], loop["center"][1] - center[1]) <= tol and abs(
                    big - size) <= tol:
                return loop, raw_loop
        return None

    def all_values(self):
        out = [c for _, xy in self.points for c in xy]
        for _, raw_loop in self.rounds:
            out += _raw_values(raw_loop)
        return out


def _raw_values(node):
    if isinstance(node, dict):
        return [v for k, value in node.items() if k not in _SKIP for v in _raw_values(value)]
    if isinstance(node, list):
        return [v for value in node for v in _raw_values(value)]
    return [node] if isinstance(node, (Affine, Curved, Stuck)) else []


def _names(values):
    """The Fusion names that move any of the raw values."""
    return tuple(dict.fromkeys(n for value in values for n in names_of(value)))


def _unread(anchors, sketch):
    return Stuck(_names(anchors.all_values()), UNREAD, sketch)


def _from_anchors(loop, anchors, sketch, sources=None):
    """The raw loop of a loop drawn through anchor points (an outline merged from several profiles). A circle that
    stands for arcs of one sketch circle takes that circle's centre and radius."""
    kind = loop["kind"]
    missing = _unread(anchors, sketch)

    def at(uv):
        found = anchors.point(uv)
        if found is None and sources is not None:
            found = sources.point(uv)
        if isinstance(found, Stuck):
            return [found, found]
        return list(found) if isinstance(found, tuple) else [missing, missing]

    if kind == "polygon":
        return dict(loop, points=[at(p) for p in loop["points"]])
    if kind == "profile":
        segments = []
        for seg in loop["segments"]:
            out = dict(seg, to=at(seg["to"]))
            if "through" in seg:
                out["through"] = at(seg["through"])
            segments.append(out)
        return dict(loop, start=at(loop["start"]), segments=segments)
    if kind == "rect":
        u, v = _rect_axes(loop)
        corners = [at(uv) for uv, _ in _rect_corners(loop, _map(loop, [], lambda path, n: Affine(n)))]
        center = [combine([(0.25, c[i]) for c in corners], sketch) for i in range(2)]
        # corners run (-,-), (+,-), (+,+), (-,+): width along u, height along v
        width = combine([(0.5 * u[i], corners[1][i]) for i in range(2)] + [(-0.5 * u[i], corners[0][i]) for i in range(2)]
                        + [(0.5 * u[i], corners[2][i]) for i in range(2)] + [(-0.5 * u[i], corners[3][i]) for i in range(2)],
                        sketch)
        height = combine([(0.5 * v[i], corners[3][i]) for i in range(2)] + [(-0.5 * v[i], corners[0][i]) for i in range(2)]
                         + [(0.5 * v[i], corners[2][i]) for i in range(2)] + [(-0.5 * v[i], corners[1][i]) for i in range(2)],
                         sketch)
        return dict(loop, center=center, width=width, height=height)
    big = loop.get("radius", max(loop.get("radiusX", 0.0), loop.get("radiusY", 0.0)))
    found = anchors.round_at(loop["center"], big)
    if found is not None and found[0]["kind"] == kind:
        return dict(found[1])
    circle = sources.circle(loop["center"], big) if sources is not None and kind == "circle" else None
    if isinstance(circle, Stuck):
        return _map(loop, [], lambda path, n: circle)
    if circle is not None:
        return dict(loop, center=circle[0], radius=circle[1])
    return _map(loop, [], lambda path, n: missing)


# ---- one written outline ----------------------------------------------------------------------------------------

def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


class Outline:
    """The written loops of one profile (outer first) as numbers and raw values, and the raw sketch plane: its
    position along the frame normal, measured from the component origin (`plane0` at the captured sizes)."""

    def __init__(self, ctx, frame, loops, raw_loops, plane, sketch=""):
        self.table = ctx.table
        self.frame = frame
        self.loops, self.raw_loops = loops, raw_loops
        self.plane, self.plane0 = plane, _dot(frame["origin"], frame["z"])
        self.sketch = sketch
        self.anchors = Anchors(sketch)
        for loop, raw_loop in zip(loops, raw_loops):
            self.anchors.add(loop, raw_loop)
        self.moves = any(isinstance(v, Stuck) or not v.is_constant for v in _raw_values(raw_loops))

    def written(self, ctx):
        """(outer, inners) as the recipe writes them: numbers, or formulas where they follow sizes."""
        def write(field, number, value):
            return quantity(ctx, value, number, positive=field in POSITIVE_FIELDS).json()

        out = [_pair(loop, raw_loop, write) for loop, raw_loop in zip(self.loops, self.raw_loops)]
        return out[0], out[1:]

    def plane_shift(self, ctx):
        """How far the sketch plane moves along its normal from where it was captured, as a Quantity (zero number)."""
        return quantity(ctx, combine([(1.0, self.plane), (-1.0, self.plane0)], self.sketch), 0.0)

    def origin(self, ctx, shift):
        """The sketch origin moved along the frame normal by the plane's move and the start `shift` (a Quantity)."""
        z = self.frame["z"]
        out = []
        for o, d in zip(self.frame["origin"], z):
            if abs(d) <= 1e-12:
                out.append(round(float(o), 9) + 0.0)
                continue
            base = float(o) + (0.0 if shift.sized else d * shift.n)
            q = quantity(ctx, combine([(1.0, base - d * self.plane0), (d, self.plane)], self.sketch), base)
            if shift.sized:
                q = q.plus(shift.scaled(d)) if q.sized else shift.scaled(d).plus(q.n)
            out.append(q.json() if q.sized else round(q.n, 9) + 0.0)
        return out

    # ---- points picked on the outline

    def _centre(self):
        loop, raw_loop = self.loops[0], self.raw_loops[0]
        if loop["kind"] in ("circle", "ellipse", "rect"):
            return loop["center"], raw_loop["center"]
        if loop["kind"] == "polygon":
            pairs = list(zip(loop["points"], raw_loop["points"]))
        else:
            pairs = [(loop["start"], raw_loop["start"])] + [(s["to"], r["to"]) for s, r in
                                                             zip(loop["segments"], raw_loop["segments"])][:-1]
        k = 1.0 / len(pairs)
        uv = [sum(p[i] for p, _ in pairs) * k for i in range(2)]
        return uv, [combine([(k, r[i]) for _, r in pairs], self.sketch) for i in range(2)]

    def _shifted(self, uv, base_uv, base):
        """`uv` moved like the point `base_uv` whose raw values are `base`."""
        return tuple(combine([(1.0, base[i]), (1.0, uv[i] - base_uv[i])], self.sketch) for i in range(2))

    def _on_curve(self, curve, near):
        """The raw (x, y) of the point `near` on an outline curve, a Stuck, or None when its ends are not known."""
        kind = curve["kind"]
        if kind == "line":
            a, b = self.anchors.point(curve["start"], PICK_TOL), self.anchors.point(curve["end"], PICK_TOL)
            if a is None or b is None:
                return None
            d = [curve["end"][i] - curve["start"][i] for i in range(2)]
            size = _dot(d, d)
            t = 0.0 if size <= 0 else max(0.0, min(1.0, _dot([near[i] - curve["start"][i] for i in range(2)], d) / size))
            return tuple(combine([(1.0 - t, a[i]), (t, b[i])], self.sketch) for i in range(2))
        if kind == "arc":
            keys = ("start", "mid", "end")
            found = [self.anchors.point(curve[k], PICK_TOL) for k in keys]
            if any(f is None for f in found):
                return None
            if math.hypot(near[0] - curve["mid"][0], near[1] - curve["mid"][1]) <= PICK_TOL:
                return self._shifted(near, curve["mid"], found[1])
            moves = [[combine([(1.0, f[i]), (-1.0, curve[k][i])]) for i in range(2)] for k, f in zip(keys, found)]
            if all(same(m[i], moves[0][i]) for m in moves[1:] for i in range(2)):
                return self._shifted(near, curve["start"], found[0])
            return Stuck(_names([v for m in moves for v in m]), BENDS, self.sketch)
        if kind in ("circle", "ellipse"):
            size = curve.get("radius", curve.get("major_radius", 0.0))
            found = self.anchors.round_at(curve["center"], size, PICK_TOL)
            if found is None:
                return None
            loop, raw_loop = found
            if kind == "circle":
                d = [near[i] - loop["center"][i] for i in range(2)]
                length = math.hypot(*d) or 1.0
                return tuple(combine([(1.0, raw_loop["center"][i]), (d[i] / length, raw_loop["radius"])], self.sketch)
                             for i in range(2))
            if all(isinstance(raw_loop[k], Affine) and raw_loop[k].is_constant for k in ("radiusX", "radiusY")):
                return self._shifted(near, loop["center"], raw_loop["center"])
            return Stuck(_names([raw_loop["center"][0], raw_loop["center"][1], raw_loop["radiusX"],
                                 raw_loop["radiusY"]]), BENDS, self.sketch)
        return None

    def follow(self, footprint, which, curve, corner, uv):
        """The raw (x, y) a point at `uv` moves to: a corner, a point on an outline curve, or a point inside an end
        face (it moves with the outline's centre). None when nothing moves it; a Stuck when it cannot follow."""
        if not self.moves:
            return None
        if corner is not None:
            found = self.anchors.point(footprint.corners[corner], PICK_TOL)
            if found is not None:
                return self._shifted(uv, footprint.corners[corner], found)
            return _unread(self.anchors, self.sketch)
        if curve is None and which == "side":
            curve = footprint.nearest_curve(uv)[0]
        if curve is not None:
            near = nearest_point(footprint.curves[curve], uv)[0]
            found = self._on_curve(footprint.curves[curve], near)
            if found is None:
                return _unread(self.anchors, self.sketch)
            return found if isinstance(found, Stuck) else self._shifted(uv, near, found)
        centre_uv, centre = self._centre()
        return self._shifted(uv, centre_uv, centre)


def _sources(ctx, item, parts, sketch):
    """The sketch curves of `parts` with their raw values, or None when the probe did not measure them."""
    prefixes = [keys.profile(item.get("index"), n) for n, _ in parts]
    if not all(p in getattr(ctx.motion, "curves", ()) for p in prefixes):
        return None
    return Sources(lambda key, number: raw(ctx, key, number, sketch), list(zip(prefixes, [s for _, s in parts])),
                   sketch)


def _mend(loop, raw_loop, sources):
    """`raw_loop` with each stuck corner and arc middle rebuilt from the sketch curves through it, where it can be."""
    if sources is None or loop["kind"] not in ("polygon", "profile"):
        return raw_loop

    def fix(uv, xy, middle=False):
        if not any(isinstance(c, Stuck) for c in xy):
            return xy
        found = sources.through(uv) if middle else sources.point(uv)
        return list(found) if isinstance(found, tuple) else xy

    if loop["kind"] == "polygon":
        return dict(raw_loop, points=[fix(p, r) for p, r in zip(loop["points"], raw_loop["points"])])
    segments = []
    for seg, rseg in zip(loop["segments"], raw_loop["segments"]):
        out = dict(rseg, to=fix(seg["to"], rseg["to"]))
        if "through" in seg:
            out["through"] = fix(seg["through"], rseg["through"], True)
        segments.append(out)
    return dict(raw_loop, start=fix(loop["start"], raw_loop["start"]), segments=segments)


def _stuck_curves(node, sketch):
    """`node` with every Curved value made stuck: the rebuilt outline does not keep its shape."""
    if isinstance(node, dict):
        return {k: _stuck_curves(v, sketch) for k, v in node.items()}
    if isinstance(node, list):
        return [_stuck_curves(v, sketch) for v in node]
    return Stuck(node.names(), CURVE, sketch) if isinstance(node, Curved) else node


def outline(ctx, item, profile, outer, inners, parts):
    """The `Outline` of one written profile, or None when sketch values do not follow sizes in this walk.

    `parts` are `(index, capture profile)` of the item's profiles it was made from: one for a profile written as it
    is, several for an outline merged from touching profiles (its values are taken from theirs). A corner that the
    probe could not fit is rebuilt from the sketch curves that cross there (sketch_crossings.py)."""
    if not active(ctx):
        return None
    sketch = profile.get("sketch") or ""
    loops = [outer] + list(inners)
    prefix = keys.profile(item.get("index"), parts[0][0])
    sources = _sources(ctx, item, parts, sketch)
    if len(parts) == 1:
        raw_loops = [_mend(loop, r, sources) for loop, r in zip(loops, _keyed_loops(ctx, prefix, loops, sketch))]
    else:
        anchors = Anchors(sketch)
        for n, source in parts:
            built = profile_loops(source)
            if not isinstance(built, Refusal):
                own = [built[0]] + list(built[1])
                for loop, raw_loop in zip(own, _keyed_loops(ctx, keys.profile(item.get("index"), n), own, sketch)):
                    anchors.add(loop, _mend(loop, raw_loop, sources))
        raw_loops = [_from_anchors(loop, anchors, sketch, sources) for loop in loops]
    if any(isinstance(v, Curved) for v in _raw_values(raw_loops)) and not keeps_order(
            ctx.table, ctx.motion, loops, raw_loops, sketch):
        raw_loops = _stuck_curves(raw_loops, sketch)
    # Merged parts share one frame, so the first part's plane stands for all of them.
    plane = raw(ctx, keys.plane(prefix), _dot(profile["frame"]["origin"], profile["frame"]["z"]), sketch)
    return Outline(ctx, profile["frame"], loops, raw_loops, plane, sketch)


def planes_apart(ctx, outlines_, item):
    """Fix the sizes that move the outlines of one step apart (on different sketches whose planes move unlike)."""
    planes = [o.plane for o in outlines_ if o is not None]
    if planes and not all(same(p, planes[0]) for p in planes[1:]):
        ctx.doubt([n for p in planes for n in movers(ctx.table, p)],
                  notes.stuck_reason("apart", item.get("name") or ""))


def points(ctx, item, rows):
    """Written 3D points of a hole's positions (`rows`): lists of numbers or formulas."""
    if not active(ctx):
        return [[round(float(c), 9) + 0.0 for c in p] for p in rows]
    sketch = (item.get("data") or {}).get("sketch") or ""
    out = []
    for n, p in enumerate(rows):
        row = []
        for c, number in enumerate(p):
            value = raw(ctx, keys.hole_point(item.get("index"), n, c), float(number), sketch)
            if isinstance(value, Affine) and not value.sketch:
                value = Affine(value.const, value.terms, sketch)
            row.append(quantity(ctx, value, float(number)).json())
        out.append(row)
    return out


def axis_point(ctx, item, frame, point2):
    """The revolve axis point in the sketch plane (`point2`, numbers) as written: it follows the axis line when the
    probe moved it. The plane only moves along its normal, so the in-plane coordinates read the line alone."""
    if not active(ctx):
        return [round(v, 9) + 0.0 for v in point2]
    axis = (item.get("data") or {}).get("axis") or {}
    sketch = axis.get("sketch") or ""
    coords = [raw(ctx, keys.axis_point(item.get("index"), c), float(axis["point"][c]), sketch) for c in range(3)]
    if all(isinstance(v, Affine) and v.is_constant for v in coords):
        return [round(v, 9) + 0.0 for v in point2]
    out = []
    for k, number in zip(("x", "y"), point2):
        value = combine([(frame[k][c], coords[c]) for c in range(3)] + [(-_dot(frame["origin"], frame[k]), 1.0)],
                        sketch)
        out.append(quantity(ctx, value, number).json())
    return out


def axis_raw(ctx, item):
    """The raw 3D axis point of a revolve, or None when sketch values do not follow sizes."""
    if not active(ctx):
        return None
    axis = (item.get("data") or {}).get("axis") or {}
    if "point" not in axis:
        return None
    sketch = axis.get("sketch") or ""
    return [raw(ctx, keys.axis_point(item.get("index"), c), float(axis["point"][c]), sketch) for c in range(3)]
