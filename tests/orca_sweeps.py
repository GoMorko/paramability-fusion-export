"""Captures of sweeps, lofts and spline outlines for the Orca tests and the live check (`scripts/orca_live_check.py
write <file>` with a capture these write). Each target box and volume is worked out from the shapes, so the live
check can compare what Orca builds, also after a variable change."""
import math

from tests import context  # noqa: F401
from tests.derived_fixtures import dimension
from tests.orca_extents import B1, UP, capture, circle, extrude, profile, rect, sketch_item
from tests.probe_helpers import model, user
from tests.sketch_solve_helpers import C, L, P, Sketch, rectangle

# A plane square to +x through the origin, its x along +y and its y along +z.
ACROSS_X = {"origin": [0.0, 0.0, 0.0], "x": [0.0, 1.0, 0.0], "y": [0.0, 0.0, 1.0], "z": [1.0, 0.0, 0.0]}


def _line(a, b, token):
    return {"kind": "line", "start": list(a), "end": list(b), "opposed": False, "entity": token,
            "flat": {"kind": "line", "start": list(a[:2]), "end": list(b[:2])}}


def _arc(centre, radius, start_deg, end_deg, token, z=0.0):
    """An arc in a plane of constant z, counter clockwise from `start_deg` to `end_deg` about +z."""
    def at(deg):
        return [centre[0] + radius * math.cos(math.radians(deg)), centre[1] + radius * math.sin(math.radians(deg)), z]

    a, b, m = at(start_deg), at(end_deg), at((start_deg + end_deg) / 2.0)
    return {"kind": "arc", "start": a, "end": b, "mid": m, "center": [centre[0], centre[1], z], "radius": radius,
            "normal": [0.0, 0.0, 1.0], "opposed": False, "entity": token,
            "flat": {"kind": "arc", "start": a[:2], "end": b[:2], "mid": m[:2], "center": list(centre),
                     "radius": radius}}


def path_record(curves, sketch="Path", token="sp", frame=UP):
    return {"closed": False, "kind": "sketch", "sketch": sketch, "sketch_token": token, "frame": dict(frame),
            "curves": curves, "edges": [], "reference": None, "projected": False}


def sweep(index, name, profiles, path, operation="newBody", areas=None, **extra):
    data = {"operation": operation, "solid": True, "profiles": profiles, "areas": areas, "path": path, "rail": None,
            "guide_surfaces": [], "orientation": "perpendicular", "distance_one": 1.0, "distance_two": 0.0,
            "taper_deg": 0.0, "twist_deg": 0.0, "scaling": "scale", "extent": None,
            "participants": [dict(B1)] if operation != "newBody" else [], "target_box_before": None,
            "params": {}}
    data.update(extra)
    return {"index": index, "name": name, "type": "SweepFeature", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [dict(B1)], "data": data}


def _bend_path(z=0.0, start=(0.0, 0.0), first=20.0, radius=10.0, last=30.0):
    """A line `first` long along +x from `start`, a quarter arc of `radius` turning to +y, then a line `last` long."""
    x0, y0 = start
    a, b = (x0, y0, z), (x0 + first, y0, z)
    centre = (x0 + first, y0 + radius)
    c = (x0 + first + radius, y0 + radius, z)
    d = (x0 + first + radius, y0 + radius + last, z)
    return [_line(a, b, "p0"), _arc(centre, radius, -90.0, 0.0, "p1", z), _line(c, d, "p2")]


def centred_rect_graph(width, height, sketch="Sketch1", token="s1"):
    """The graph of a `width` by `height` rectangle centred on the sketch origin, sized by `bar_w` and `bar_h`."""
    s = Sketch()
    hw, hh = width / 2.0, height / 2.0
    corners = [s.point(-hw, -hh), s.point(hw, -hh), s.point(hw, hh), s.point(-hw, hh)]
    lines = rectangle(s, corners)
    diagonal = s.line(corners[0], corners[2], construction=True)
    s.con("midpoint", P(0), L(diagonal))
    dimension(s, "linear", [L(lines[0])], width, "d1", "bar_w", "horizontal")
    dimension(s, "linear", [L(lines[1])], height, "d2", "bar_h", "vertical")
    record = s.record()
    record.update(sketch=sketch, token=token)
    for number, entity in enumerate(record["curves"]):
        entity["token"] = "e%d" % number
    return record


def bar_along_bend(width=6.0, height=4.0):
    """A `bar_w` by `bar_h` rectangle (6 by 4) swept along a 20 mm line, a quarter arc of radius 10 and a 30 mm line,
    in the XY plane. The outline's centre runs on the path, so the volume is the area times the path length."""
    outline = dict(profile("Sketch1", ACROSS_X, rect(-width / 2, -height / 2, width / 2, height / 2)),
                   sketch_token="s1", space="sketch")
    for n, curve in enumerate(outline["loops"][0]["curves"]):
        curve["entity"] = "e%d" % n
    items = [sketch_item(0, "Sketch1"), sketch_item(1, "Path"),
             sweep(2, "Bar", [outline], path_record(_bend_path()), areas=[width * height])]
    length = 20.0 + math.pi * 5.0 + 30.0
    users = [user("bar_w", "%g mm" % width, width), user("bar_h", "%g mm" % height, height)]
    models = [model("d1", "bar_w", width, sketch="Sketch1"), model("d2", "bar_h", height, sketch="Sketch1")]
    out = capture(items, ((0.0, -width / 2, -height / 2), (30.0 + width / 2, 40.0, height / 2)),
                  width * height * length, users, models)
    out["sketch_graphs"] = [centred_rect_graph(width, height)]
    return out


def groove(radius=2.0):
    """A 40 by 40 by 10 block with a round groove cut along its top face: a circle of `radius` on the path start
    (outside the block), along a line, a quarter arc of radius 10 and a line that leaves the block. Half the circle
    lies in the block, and its centre runs on the path, so the groove takes half the circle's area times the length of
    path inside the block."""
    outline = dict(profile("Sketch2", dict(ACROSS_X, origin=[-25.0, -5.0, 10.0]), circle(radius)), space="sketch")
    path = path_record(_bend_path(z=10.0, start=(-25.0, -5.0), first=25.0, radius=10.0, last=20.0))
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Block", [profile("Sketch1", UP, rect(-20, -20, 20, 20))], side_one={
                 "kind": "distance", "distance": 10.0, "taper_deg": 0.0}, end_offset=10.0, target_box_before=None),
             sketch_item(2, "Sketch2"), sketch_item(3, "Path"),
             sweep(4, "Groove", [outline], path, operation="cut", areas=[math.pi * radius ** 2],
                   target_box_before={"min": [-20, -20, 0], "max": [20, 20, 10]})]
    inside = 20.0 + math.pi * 5.0 + 15.0
    return capture(items, ((-20, -20, 0), (20, 20, 10)), 16000.0 - math.pi * radius ** 2 / 2.0 * inside)


def groove_then_hole(depth=1.0):
    """The groove, then a hole of radius 0.5 cut `depth` down from the top face inside the groove (at x -10 on the
    first line): with a depth under the groove's, it meets no material."""
    out = groove()
    hole = extrude(6, "Pin", [profile("Sketch3", dict(UP, origin=[-10.0, -5.0, 10.0]), circle(0.5))],
                   operation="cut", side_one={"kind": "distance", "distance": -depth, "taper_deg": 0.0},
                   end_offset=-depth, target_box_before={"min": [-20, -20, 0], "max": [20, 20, 10]})
    out["items"] += [sketch_item(5, "Sketch3"), hole]
    return out


# ---- lofts --------------------------------------------------------------------------------------------------------

def loft(index, name, profiles, operation="newBody", **extra):
    data = {"operation": operation, "solid": True, "profiles": profiles, "areas": None,
            "sections": [{"kind": "profile", "profile": n, "end": "free"} for n in range(len(profiles))],
            "rails": [], "centerline": None, "closed": False, "merge_tangent": True,
            "participants": [dict(B1)] if operation != "newBody" else [], "target_box_before": None}
    data.update(extra)
    return {"index": index, "name": name, "type": "LoftFeature", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [dict(B1)], "data": data}


def circle_graph(radius, param, sketch, token):
    """The graph of a circle of `radius` on the sketch origin, its diameter set by `param`."""
    s = Sketch()
    ring = s.circle(0, radius)
    dimension(s, "diameter", [C(ring)], 2.0 * radius, "d_" + param, param)
    record = s.record()
    record.update(sketch=sketch, token=token)
    for number, entity in enumerate(record["curves"]):
        entity["token"] = "%s%d" % (token, number)
    return record


def cone(bottom=10.0, top=5.0, height=20.0, shift=6.0):
    """A circle of radius `bottom` at z 0 lofted to a circle of radius `top` (its diameter `top_d`) `height` above it
    and `shift` along x: an oblique cone frustum."""
    low = dict(profile("Sketch1", UP, circle(bottom)), sketch_token="s1", space="sketch")
    high = dict(profile("Sketch2", dict(UP, origin=[shift, 0.0, height]), circle(top)), sketch_token="s2",
                space="sketch")
    items = [sketch_item(0, "Sketch1"), sketch_item(1, "Sketch2"), loft(2, "Cone", [low, high])]
    users = [user("top_d", "%g mm" % (2 * top), 2 * top)]
    models = [model("d_top_d", "top_d", 2 * top, sketch="Sketch2")]
    out = capture(items, ((-bottom, -bottom, 0.0), (max(bottom, shift + top), bottom, height)),
                  math.pi * height / 3.0 * (bottom ** 2 + bottom * top + top ** 2), users, models)
    out["sketch_graphs"] = [circle_graph(top, "top_d", "Sketch2", "s2")]
    return out


def turned_squares(turn_deg=0.5, bottom=20.0, top=10.0, height=30.0):
    """A square of `bottom` at z 0 lofted to a square of `top` turned `turn_deg` about its centre, `height` above."""
    def square(side, deg):
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        corners = [(x * c - y * s, x * s + y * c) for x, y in ((-side / 2, -side / 2), (side / 2, -side / 2),
                                                               (side / 2, side / 2), (-side / 2, side / 2))]
        return [{"kind": "line", "start": list(corners[n]), "end": list(corners[(n + 1) % 4])} for n in range(4)]

    low = profile("Sketch1", UP, square(bottom, 0.0))
    high = profile("Sketch2", dict(UP, origin=[0.0, 0.0, height]), square(top, turn_deg))
    items = [sketch_item(0, "Sketch1"), sketch_item(1, "Sketch2"), loft(2, "Frustum", [low, high])]
    # The middle section joins each corner to the corner it turned from.
    c, s = math.cos(math.radians(turn_deg)), math.sin(math.radians(turn_deg))
    mid = [((bottom + top * c) / 4.0, top * s / 4.0)]
    middle_area = 4.0 * (mid[0][0] ** 2 + mid[0][1] ** 2) * 2.0
    volume = height / 6.0 * (bottom ** 2 + top ** 2 + 4.0 * middle_area / 2.0)
    half = bottom / 2.0
    return capture(items, ((-half, -half, 0.0), (half, half, height)), volume)


# ---- spline outlines ----------------------------------------------------------------------------------------------

def nurbs_point(degree, knots, poles, u):
    """A point of a non-rational B-spline by the Cox-de Boor sums (mm)."""
    def basis(i, p, t):
        if p == 0:
            last = t == knots[-1] and knots[i] < knots[i + 1] == knots[-1]
            return 1.0 if knots[i] <= t < knots[i + 1] or last else 0.0
        out = 0.0
        if knots[i + p] > knots[i]:
            out += (t - knots[i]) / (knots[i + p] - knots[i]) * basis(i, p - 1, t)
        if knots[i + p + 1] > knots[i + 1]:
            out += (knots[i + p + 1] - t) / (knots[i + p + 1] - knots[i + 1]) * basis(i + 1, p - 1, t)
        return out

    weights = [basis(i, degree, u) for i in range(len(poles))]
    return tuple(sum(w * p[k] for w, p in zip(weights, poles)) for k in range(2))


ARCH = {"degree": 3, "knots": [0, 0, 0, 0, 0.4, 1, 1, 1, 1],
        "poles": [(0.0, 0.0), (5.0, 8.0), (15.0, 12.0), (25.0, 6.0), (30.0, 0.0)]}


def spline_curve(spec=ARCH, samples=400, **nurbs):
    """A capture curve of a spline: its measured points and its exact definition (`nurbs`)."""
    knots = spec["knots"]
    points = [list(nurbs_point(spec["degree"], knots, spec["poles"], knots[0] + (knots[-1] - knots[0]) * k / samples))
              for k in range(samples + 1)]
    record = {"degree": spec["degree"], "knots": list(knots), "poles": [list(p) for p in spec["poles"]],
              "rational": False, "weights": None, "periodic": False}
    record.update(nurbs)
    return {"kind": "other", "type": "NurbsCurve3D", "start": points[0], "end": points[-1],
            "mid": points[len(points) // 2], "samples": points, "nurbs": record}


def arch(height=10.0, spec=ARCH, **nurbs):
    """An arch: a cubic spline of two pieces with uneven knots from (0, 0) up and over to (30, 0), closed by the line
    back, extruded `height`. Its area is worked out from many points of the spline."""
    curve = spline_curve(spec, **nurbs)
    dense = [nurbs_point(spec["degree"], spec["knots"], spec["poles"], k / 20000.0) for k in range(20001)]
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(dense, dense[1:] + dense[:1])) / 2.0)
    outline = [curve, {"kind": "line", "start": [30.0, 0.0], "end": [0.0, 0.0]}]
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Arch", [profile("Sketch1", UP, outline)], side_one={
                 "kind": "distance", "distance": height, "taper_deg": 0.0}, end_offset=height, target_box_before=None)]
    top = max(p[1] for p in dense)
    return capture(items, ((0.0, 0.0, 0.0), (30.0, top, height)), area * height)


def quarter_bend(radius=2.0, bend=10.0, clockwise=False):
    """A circle of `radius` swept along a quarter arc of `bend` about the Z axis from (bend, 0, 0): counter clockwise
    to (0, bend, 0), or clockwise to (0, -bend, 0). The outline's centre runs on the arc (Pappus)."""
    frame = {"origin": [bend, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 0.0, 1.0], "z": [0.0, 1.0, 0.0]}
    outline = dict(profile("Sketch1", frame, circle(radius)), space="sketch")
    arc = _arc((0.0, 0.0), bend, 0.0, 90.0, "p0") if not clockwise else _arc((0.0, 0.0), bend, -90.0, 0.0, "p0")
    if clockwise:  # run from (bend, 0) down to (0, -bend)
        arc = dict(arc, start=arc["end"], end=arc["start"],
                   flat=dict(arc["flat"], start=arc["flat"]["end"], end=arc["flat"]["start"]))
    items = [sketch_item(0, "Sketch1"), sketch_item(1, "Path"),
             sweep(2, "Bend", [outline], path_record([arc]), areas=[math.pi * radius ** 2])]
    low, high = (0.0, bend + radius) if not clockwise else (-bend - radius, 0.0)
    return capture(items, ((0.0, low, -radius), (bend + radius, high, radius)),
                   math.pi * radius ** 2 * math.pi / 2.0 * bend)


def block_and_bend(clockwise=False):
    """A 4 by 5 by 4 block behind the start of `quarter_bend` (y from -5 to 0 for the counter clockwise bend, 0 to 5
    for the clockwise one), then the bend joined to it: the block shows which way the bend turned."""
    out = quarter_bend(clockwise=bool(clockwise))
    y0, y1 = (-5.0, 0.0) if not clockwise else (0.0, 5.0)
    block = extrude(0, "Block", [profile("Block sketch", dict(UP, origin=[0.0, 0.0, -2.0]), rect(8, y0, 12, y1))],
                    side_one={"kind": "distance", "distance": 4.0, "taper_deg": 0.0}, end_offset=4.0,
                    target_box_before=None)
    bend = out["items"][2]
    bend["index"] = 3
    bend["data"].update(operation="join", participants=[dict(B1)])
    out["items"] = [block, sketch_item(1, "Sketch1"), sketch_item(2, "Path"), bend]
    box = out["target"]["box"]
    box["min"][1], box["max"][1] = min(box["min"][1], y0), max(box["max"][1], y1)
    out["target"]["volume_mm3"] = round(out["target"]["volume_mm3"] + 80.0, 4)
    return out


# ---- sweeps along a spline ----------------------------------------------------------------------------------------

# A cubic of two pieces with uneven knots from (20, 0), leaving along +x (so it meets a line along +x smoothly), and
# bending up to (40, 20); `BEND_BACK` is the same curve drawn from its far end.
BEND_SPLINE = {"degree": 3, "knots": [0, 0, 0, 0, 0.3, 1, 1, 1, 1],
               "poles": [(20.0, 0.0), (28.0, 0.0), (36.0, 4.0), (40.0, 12.0), (40.0, 20.0)]}
BEND_BACK = dict(BEND_SPLINE, knots=[0, 0, 0, 0, 0.7, 1, 1, 1, 1], poles=list(reversed(BEND_SPLINE["poles"])))


def _spline_path_curve(spec, token, opposed=False):
    """A path curve of a spline in the XY plane: its points in 3D and its exact definition in `flat`."""
    flat = spline_curve(spec)
    lift = [list(p) + [0.0] for p in flat["samples"]]
    return {"kind": "other", "type": "NurbsCurve3D", "start": lift[0], "end": lift[-1], "mid": lift[len(lift) // 2],
            "samples": lift, "opposed": opposed, "entity": token, "flat": flat}


# A cubic of three pieces that leaves (20, 0) along +x, bends left, then right through a turning point, and ends
# along +x at (72, 0): Orca must carry the outline through the turning point without flipping it.
S_SPLINE = {"degree": 3, "knots": [0, 0, 0, 0, 0.4, 0.6, 1, 1, 1, 1],
            "poles": [(20.0, 0.0), (32.0, 0.0), (40.0, 14.0), (52.0, -14.0), (60.0, 0.0), (72.0, 0.0)]}


def spline_bend_points(spec=BEND_SPLINE, count=4000):
    return [nurbs_point(spec["degree"], spec["knots"], spec["poles"], k / float(count)) for k in range(count + 1)]


def _along_spline(name, outline, area, across, up, spec, drawn_back=False):
    """`outline` (in `ACROSS_X`, of `area`, reaching `across` in the XY plane and `up` out of it from its centre on
    the path start) swept along a 20 mm line along +x from the origin and the spline `spec` on from its end. The
    outline's centre runs on the path, so the volume is the area times the path length; the box is the path grown
    by `across` square to it and by `up` along z. With `drawn_back` both curves are drawn from the far end of the path
    (`BEND_BACK`, then the line back to the origin), so the copy must turn both round."""
    outline = dict(profile("Sketch1", ACROSS_X, outline), space="sketch")
    curves = [_line((0.0, 0.0, 0.0), (20.0, 0.0, 0.0), "p0"), _spline_path_curve(spec, "p1")]
    if drawn_back:
        curves = [_spline_path_curve(BEND_BACK, "p1"), _line((20.0, 0.0, 0.0), (0.0, 0.0, 0.0), "p0")]
    items = [sketch_item(0, "Sketch1"), sketch_item(1, "Path"),
             sweep(2, name, [outline], path_record(curves), areas=[area])]
    dense = spline_bend_points(spec)
    length = 20.0 + sum(math.dist(a, b) for a, b in zip(dense, dense[1:]))
    grown = [(0.0, -across), (0.0, across)]
    for a, b in zip(dense, dense[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        size = math.hypot(dx, dy)
        for p in (a, b):
            grown += [(p[0] - dy / size * across, p[1] + dx / size * across),
                      (p[0] + dy / size * across, p[1] - dx / size * across)]
    low = (min(p[0] for p in grown), min(p[1] for p in grown), -up)
    high = (max(p[0] for p in grown), max(p[1] for p in grown), up)
    return capture(items, (low, high), area * length)


def pipe_along_spline(radius=2.0, drawn_back=False):
    """A circle of `radius` swept along a line and `BEND_SPLINE` (`_along_spline`)."""
    return _along_spline("Pipe", circle(radius), math.pi * radius ** 2, radius, radius, BEND_SPLINE, drawn_back)


def bar_along_s_spline(width=4.0, height=1.5):
    """A `width` (in the path's plane) by `height` rectangle swept along a line and `S_SPLINE` (`_along_spline`): a
    rectangle that flipped at the turning point would stand `width` high there."""
    return _along_spline("Bar", rect(-width / 2, -height / 2, width / 2, height / 2), width * height, width / 2,
                         height / 2, S_SPLINE)


# Two half loops that close a 40 by 20 track: from (40, 0) out to the right and back to (40, 20), and from (0, 20) out
# to the left and back to (0, 0), each leaving and meeting its lines smoothly.
RIGHT_END = {"degree": 3, "knots": [0, 0, 0, 0, 1, 1, 1, 1], "poles": [(40.0, 0.0), (52.0, 0.0), (52.0, 20.0),
                                                                     (40.0, 20.0)]}
LEFT_END = {"degree": 3, "knots": [0, 0, 0, 0, 1, 1, 1, 1], "poles": [(0.0, 20.0), (-12.0, 20.0), (-12.0, 0.0),
                                                                    (0.0, 0.0)]}


def _grown_box(points, across, up):
    """The box of a closed or open chain of `points` (2D, dense) grown by `across` square to it and `up` along z."""
    grown = []
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        size = math.hypot(dx, dy)
        if size < 1e-12:
            continue
        for p in (a, b):
            grown += [(p[0] - dy / size * across, p[1] + dx / size * across),
                      (p[0] + dy / size * across, p[1] - dx / size * across)]
    return ((min(p[0] for p in grown), min(p[1] for p in grown), -up),
            (max(p[0] for p in grown), max(p[1] for p in grown), up))


def ring_along_splines(radius=1.5):
    """A circle of `radius` on the middle of the bottom line swept once round the closed track of two lines and the
    splines `RIGHT_END` and `LEFT_END`. The outline's centre runs on the path, so the volume is the area times the
    path length."""
    outline = dict(profile("Sketch1", dict(ACROSS_X, origin=[20.0, 0.0, 0.0]), circle(radius)), space="sketch")
    curves = [_line((0.0, 0.0, 0.0), (40.0, 0.0, 0.0), "p0"), _spline_path_curve(RIGHT_END, "p1"),
              _line((40.0, 20.0, 0.0), (0.0, 20.0, 0.0), "p2"), _spline_path_curve(LEFT_END, "p3")]
    path = dict(path_record(curves), closed=True)
    items = [sketch_item(0, "Sketch1"), sketch_item(1, "Path"),
             sweep(2, "Ring", [outline], path, areas=[math.pi * radius ** 2])]
    dense = ([(0.0, 0.0), (40.0, 0.0)] + spline_bend_points(RIGHT_END) + [(0.0, 20.0)]
             + spline_bend_points(LEFT_END))
    length = sum(math.dist(a, b) for a, b in zip(dense, dense[1:]))
    return capture(items, _grown_box(dense, radius, radius), math.pi * radius ** 2 * length)


def block_and_spline_pipe(operation, radius=2.0):
    """The wire of `pipe_along_spline` with a block first: for "cut" a block from (-10, -10, -5) to (60, 30, 5) that
    holds the whole pipe, which the sweep cuts out; for "join" a 10 mm block behind the pipe's start (x -10 to 0,
    y and z -5 to 5), which the pipe joins."""
    out = pipe_along_spline(radius)
    if operation == "cut":
        low, high = (-10.0, -10.0, -5.0), (60.0, 30.0, 5.0)
    else:
        low, high = (-10.0, -5.0, -5.0), (0.0, 5.0, 5.0)
    block = extrude(0, "Block", [profile("Block sketch", dict(UP, origin=[0.0, 0.0, low[2]]),
                                         rect(low[0], low[1], high[0], high[1]))],
                    side_one={"kind": "distance", "distance": high[2] - low[2], "taper_deg": 0.0},
                    end_offset=high[2] - low[2], target_box_before=None)
    block_volume = (high[0] - low[0]) * (high[1] - low[1]) * (high[2] - low[2])
    pipe = out["items"][2]
    pipe["index"] = 3
    pipe["data"].update(operation=operation, participants=[dict(B1)],
                        target_box_before={"min": list(low), "max": list(high)})
    out["items"] = [block, sketch_item(1, "Sketch1"), sketch_item(2, "Path"), pipe]
    box = out["target"]["box"]
    if operation == "cut":
        out["target"]["box"] = {"min": list(low), "max": list(high)}
        out["target"]["volume_mm3"] = round(block_volume - out["target"]["volume_mm3"], 4)
    else:
        box["min"] = [min(a, b) for a, b in zip(box["min"], low)]
        box["max"] = [max(a, b) for a, b in zip(box["max"], high)]
        out["target"]["volume_mm3"] = round(block_volume + out["target"]["volume_mm3"], 4)
    return out


def sized_spline_pipe(wire=4.0, run=20.0):
    """`pipe_along_spline` with the circle's diameter set by `wire` (its sketch graph) and the first line's length by
    `run`, a dimension of the path sketch."""
    out = pipe_along_spline(wire / 2.0)
    out["parameters"] = {"user": [user("wire", "%g mm" % wire, wire), user("run", "%g mm" % run, run)],
                         "model": [model("d_wire", "wire", wire, sketch="Sketch1"),
                                   model("d_run", "run", run, sketch="Path")]}
    out["sketch_graphs"] = [circle_graph(wire / 2.0, "wire", "Sketch1", "s1")]
    out["items"][2]["data"]["profiles"][0]["sketch_token"] = "s1"
    return out
