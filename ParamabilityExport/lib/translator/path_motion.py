"""A sweep path written as formulas over the sizes, from the probe's motion file.

The probe measures each sketch curve of a sweep path (`sketch_values.keys`: points in the path sketch's plane, radii,
the angle an arc turns, the plane's position). Here those raw values are looked up for the points the path planner
wrote (`path_model.PathPlan`): a written point is the start, end or middle of a curve of the sketch, found by its place.
The exception is the place where a closed path was cut open at the outline's plane: when that is inside a straight
line square to the plane, the point follows the line and the plane. A path where some written point is none of these
(a cut inside an arc, a free curve) is not followed: the caller writes it as measured.

What follows depends on how the sweep is written:
- a straight path is an extrude: its distance follows the line's length;
- one arc is a revolve: its axis point follows the arc's centre and its angle the angle the arc turns;
- a chain of lines and arcs in the sketch's own plane is a flat path: its start and every `to` and `through` point
  follow, and its placement follows the sketch plane;
- a straight path that twists is a path of two corner points: both points follow.

`Followed.curves_at` gives the path as plain numbers at any size setting, so the caller can test the app's rules over
the size ranges (`path_rebuilt.rebuilt_refusal`).
"""
import copy
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from ..geometry import vec
from ..params.expressions.evaluation import evaluate_tree
from ..params.expressions.formula import parse_formula
from ..sketch_values import keys
from ..sketch_values.motion import Stuck
from . import path_curves, path_limits, path_rebuilt, range_check, sketch_motion
from .curved import combine
from .values import Quantity, Sized, reads_in

MATCH_TOL = 1e-4      # a written point is a curve's point when this close (mm), as curves join in `path_curves.chain`
FRAME_TOL = 1e-6      # the written placement is the sketch's own when this close
LENGTH_TOL = 1e-3     # a formula gives the measured length (mm) or angle (degrees) this closely at every setting
_POINTS = {"line": ("start", "end"), "arc": ("start", "mid", "end"), "circle": ()}


def swept_degrees(arc):
    """The angle in degrees an arc (`start`, `mid`, `end`, `center` in 2D) turns from its start through its middle."""
    a, m, e = ([arc[k][c] - arc["center"][c] for c in range(2)] for k in ("start", "mid", "end"))

    def turn(u, v):
        return math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])

    return math.degrees(abs(turn(a, m)) + abs(turn(m, e)))


_tree = lru_cache(maxsize=4096)(parse_formula)


def worked_out(formula, env):
    """The value of a written formula over the size values `env`; the formula is read once."""
    return evaluate_tree(_tree(formula), env)


def _numbers(node, env):
    """A written value or step with every formula worked out over the size values `env`."""
    if isinstance(node, Sized):
        return worked_out(node["expr"], env)
    if isinstance(node, dict):
        return {k: _numbers(v, env) for k, v in node.items()}
    if isinstance(node, list):
        return [_numbers(v, env) for v in node]
    return node


@dataclass
class Followed:
    """A sweep path that follows sizes.

    written: the path as it is written (formulas where it follows sizes); for a straight or arc path written as an
      extrude or a revolve, the same path as it would be written flat, kept to test the rules.
    flat: for a straight path written as corner points, the same path written flat, to test the rules (else None).
    length: for a straight path, the line's length as a Quantity.
    centre, turn: for an arc path, the raw 3D centre and the Quantity of the angle in degrees.
    on_plane: the raw 3D points that must stay on the outline's plane (the path start, an arc's centre).
    pairs: `(Quantity, function(curves) -> number)` for each formula that must give what the path measures.
    reads: the Fusion names of the sizes the path reads.
    """

    written: dict
    on_plane: list
    reads: tuple = ()
    length: Optional[Quantity] = None
    centre: Optional[list] = None
    turn: Optional[Quantity] = None
    pairs: list = field(default_factory=list)
    flat: Optional[dict] = None

    def curves_at(self, env):
        """The path as lines and arcs with numbers at the size values `env` (raises ValueError, ExpressionError,
        ZeroDivisionError when it cannot be worked out)."""
        return path_rebuilt.flat_curves(_numbers(self.flat or self.written, env))

    def disagrees_at(self, env, curves):
        """True when a formula does not give what the path measures at the size values `env`."""
        for quantity, measure in self.pairs:
            number = worked_out(quantity.text, env) if quantity.sized else quantity.n
            if abs(number - measure(curves)) > LENGTH_TOL:
                return True
        return False


class _Raw:
    """The raw values of the curves of one sweep path sketch. `drawn` is the outline's `sketch_motion.Outline`: a
    closed path is cut open where it meets its plane."""

    def __init__(self, ctx, index, path, drawn):
        self.ctx = ctx
        self.drawn = drawn
        self.frame = path["frame"]
        self.sketch = path.get("sketch") or ""
        origin, z = self.frame["origin"], self.frame["z"]
        self.plane0 = sum(o * c for o, c in zip(origin, z))
        self.plane = sketch_motion.raw(ctx, keys.path_plane(index), self.plane0, self.sketch)
        self.curves = path["curves"]
        self.anchors = []   # (point in the sketch plane, (raw x, raw y))
        self.fields = []    # per curve: name -> (raw x, raw y), "radius" and "turn" -> raw
        for number, curve in enumerate(path["curves"]):
            flat, prefix, found = curve["flat"], keys.path_curve(index, number), {}
            for name in _POINTS[curve["kind"]] + (("center",) if curve["kind"] != "line" else ()):
                found[name] = tuple(sketch_motion.raw(ctx, "%s%s.%d" % (prefix, name, c), float(flat[name][c]),
                                                      self.sketch) for c in range(2))
            if curve["kind"] != "line":
                found["radius"] = sketch_motion.raw(ctx, prefix + "radius", float(flat["radius"]), self.sketch)
            if curve["kind"] == "arc":
                found["turn"] = sketch_motion.raw(ctx, prefix + "turn", swept_degrees(flat), self.sketch)
            self.fields.append(found)
            self.anchors += [(flat[name], found[name]) for name in _POINTS[curve["kind"]]]

    def at(self, uv):
        """The raw (x, y) of the curve point at `uv`, or None."""
        best = None
        for point, raw in self.anchors:
            gap = math.hypot(point[0] - uv[0], point[1] - uv[1])
            if gap <= MATCH_TOL and (best is None or gap < best[0]):
                best = (gap, raw)
        return self.cut_at(uv) if best is None else best[1]

    def cut_at(self, uv):
        """The raw (x, y) of a point inside a straight line of the sketch that runs square to the outline's plane,
        where the line meets that plane (the place a closed path is cut open), or None. The point keeps the line's
        place across the plane's normal and follows the plane along it."""
        f, z = self.frame, vec.unit(self.drawn.frame["z"])
        for curve, found in zip(self.curves, self.fields):
            if curve["kind"] != "line":
                continue
            a, b = curve["flat"]["start"], curve["flat"]["end"]
            d = [b[0] - a[0], b[1] - a[1]]
            size = math.hypot(*d)
            t = ((uv[0] - a[0]) * d[0] + (uv[1] - a[1]) * d[1]) / (size * size) if size > 0 else -1.0
            if not 0.0 < t < 1.0 or math.hypot(uv[0] - a[0] - t * d[0], uv[1] - a[1] - t * d[1]) > MATCH_TOL:
                continue
            along = vec.unit([f["x"][c] * d[0] + f["y"][c] * d[1] for c in range(3)])
            if vec.length(vec.cross(along, z)) > FRAME_TOL:
                return None
            start = self.in_space(found["start"])
            across = combine([(z[j], start[j]) for j in range(3)], self.sketch)
            at = [combine([(1.0, start[c]), (-z[c], across), (z[c], self.drawn.plane)], self.sketch)
                  for c in range(3)]
            return tuple(combine([(f[axis][c], at[c]) for c in range(3)] + [(-vec.dot(f[axis], f["origin"]), 1.0)],
                                 self.sketch) for axis in ("x", "y"))
        return None

    def in_space(self, xy):
        """The raw 3D point of a raw point in the sketch plane, moved along the plane's normal with the plane."""
        f = self.frame
        shift = combine([(1.0, self.plane), (-1.0, self.plane0)], self.sketch)
        return [combine([(f["x"][c], xy[0]), (f["y"][c], xy[1]), (f["z"][c], shift), (1.0, f["origin"][c])],
                        self.sketch) for c in range(3)]

    def local(self, point):
        """A 3D point in the sketch plane's own coordinates."""
        f = self.frame
        d = vec.sub(point, f["origin"])
        return [vec.dot(d, f["x"]), vec.dot(d, f["y"])]

    def origin(self):
        """The written placement origin: the sketch's own, moved along its normal with the sketch plane."""
        outline = sketch_motion.Outline(self.ctx, self.frame, [], [], self.plane, self.sketch)
        return outline.origin(self.ctx, Quantity(0.0))


def _points_of(recipe):
    """`[(owner dict or list, key or index, [x, y])]` for every written point of a flat path, start first."""
    out = [(recipe, "start", recipe["start"])]
    for segment in recipe["segments"]:
        if "through" in segment:
            out.append((segment, "through", segment["through"]))
        out.append((segment, "to", segment["to"]))
    return out


def _written(raw, recipe):
    """The flat `recipe` with each point as formulas where the sketch's values move, or None when a point is not one
    of the sketch curves' points. The last point of a closed path is the start."""
    found = [raw.at(point) for _, _, point in _points_of(recipe)]
    if any(f is None for f in found):
        return None
    if recipe.get("closed"):
        found[-1] = found[0]
    out = copy.deepcopy(recipe)
    for (owner, key, point), xy in zip(_points_of(out), found):
        owner[key] = [sketch_motion.quantity(raw.ctx, xy[c], point[c]).json() for c in range(2)]
    out["on"]["origin"] = raw.origin()
    return out


def _same_frame(recipe, frame):
    """True when the recipe's placement is the sketch's own, so its points are the sketch's coordinates."""
    on = recipe["on"]
    pairs = (("normal", vec.unit(frame["z"])), ("xDir", vec.unit(frame["x"])), ("origin", frame["origin"]))
    return all(vec.length(vec.sub(on[key], other)) <= FRAME_TOL for key, other in pairs)


def _as_flat(raw, found):
    """The path as a flat recipe in the sketch's own placement: the planner's own for a chain, else made from the
    one line or arc."""
    if found.recipe is not None and found.recipe.get("kind") == "flat":
        return found.recipe if _same_frame(found.recipe, raw.frame) else None
    f = raw.frame
    on = {"origin": [round(float(v), 9) + 0.0 for v in f["origin"]],
          "normal": [round(float(v), 9) + 0.0 for v in vec.unit(f["z"])],
          "xDir": [round(float(v), 9) + 0.0 for v in vec.unit(f["x"])]}
    start = [round(v, 9) for v in raw.local(found.start)]
    curve = found.curves[0]
    if found.kind == "line":
        return {"kind": "flat", "on": on, "start": start,
                "segments": [{"kind": "line", "to": [round(v, 9) for v in raw.local(found.end)]}]}
    return {"kind": "flat", "on": on, "start": start,
            "segments": [{"kind": "arc", "through": [round(v, 9) for v in raw.local(curve["mid"])],
                          "to": [round(v, 9) for v in raw.local(found.end)]}]}


def follow(ctx, item, path, found, form, drawn):
    """The `Followed` path for a path the planner found (`found`, a `path_model.PathPlan`) that is written as `form`
    (`extrude` for a line, `revolve` for an arc, `sweep` for a flat chain or for a line that twists), or None when it is not followed: no motion
    values for it, a form that cannot follow, or a point that is none of the sketch's. `drawn` is the outline's
    `sketch_motion.Outline`."""
    index = item.get("index")
    if not sketch_motion.active(ctx) or keys.path(index) not in ctx.motion.curves:
        return None
    if (form, found.kind) not in (("extrude", "line"), ("revolve", "arc"), ("sweep", "flat"), ("sweep", "line")):
        return None
    if not all(isinstance(c.get("flat"), dict) and isinstance(c.get("entity"), str) for c in path["curves"]):
        return None
    raw = _Raw(ctx, index, path, drawn)
    flat = _as_flat(raw, found)
    if flat is None:
        return None
    written = _written(raw, flat)
    if written is None:
        return None
    first = flat["start"]
    start = raw.in_space(raw.at(first))
    followed = Followed(written, [start])
    if form == "extrude":
        end = raw.in_space(raw.at(flat["segments"][0]["to"]))
        along = combine([(found.direction[c], end[c]) for c in range(3)]
                        + [(-found.direction[c], start[c]) for c in range(3)], raw.sketch)
        followed.length = sketch_motion.quantity(ctx, along, found.length, positive=True)
        followed.pairs.append((followed.length, lambda curves: vec.length(vec.sub(curves[0]["end"],
                                                                                  curves[0]["start"]))))
    elif form == "revolve":
        centre = raw.fields[0]["center"]
        followed.centre = raw.in_space(centre)
        followed.on_plane.append(followed.centre)
        followed.turn = sketch_motion.quantity(ctx, raw.fields[0]["turn"], found.angle_deg, positive=True)
        followed.pairs.append((followed.turn, lambda curves: path_curves.turn_degrees(curves[0])))
    elif found.kind == "line":
        followed.flat = written
        followed.written = dict(found.recipe, points=[
            [sketch_motion.quantity(ctx, space[c], number).json() for c, number in enumerate(point)]
            for space, point in ((start, found.recipe["points"][0]),
                                 (raw.in_space(raw.at(flat["segments"][0]["to"])), found.recipe["points"][1]))])
    followed.reads = tuple(dict.fromkeys(reads_in(written) + reads_in(followed.written) + (followed.length.reads if followed.length else ())
                                         + (followed.turn.reads if followed.turn else ())))
    return followed


def keep_on_plane(ctx, followed, profile_frame, drawn, name):
    """Mark the sizes behind a path start (or arc centre) that leaves the outline's plane at other values: the path
    would no longer start on the plane its outline lies in. Both move with the same sizes when the sketches are tied
    together. `drawn` is the outline's `sketch_motion.Outline`."""
    z = vec.unit(profile_frame["z"])
    why = "%s starts its path on the plane of its outline, which the copy cannot move with it" % name
    for point in followed.on_plane:
        q = sketch_motion.rendered(ctx.table, combine([(z[c], point[c]) for c in range(3)] + [(-1.0, drawn.plane)],
                                                      drawn.sketch), 0.0)
        if isinstance(q, Stuck):
            names = sketch_motion.movers(ctx.table, q)
            if names:
                ctx.doubt(names, why)
        elif q.sized:
            span = range_check.sweep(ctx.table, q.text, q.reads)
            if not (span.at_least(-path_limits.PLANE_TOL) and span.at_most(path_limits.PLANE_TOL)):
                ctx.doubt(q.reads, why)
