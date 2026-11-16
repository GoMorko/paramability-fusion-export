"""Edges and faces of the part matched to the straight extrudes that made them: which sizes may turn a pattern
direction taken from one, which may change the angle between two faces, and which may change the thickness a tapped
hole goes through. Also which sizes may turn or stretch a sketch line a step takes as numbers (`line_sizes`): only
the dimensions the sketch solver shows on the gap between its ends, and what moves the sketch plane.

Both outputs write such a direction and such a thread length as numbers. In general every size read before the step
may change them (`reach.reference_sizes`, `reach.hole_end_sizes`). The capture can show less, but only for a part
that is plain before the step (`_plain_body`): every step of the body's component before it is a straight extrude, a
simple hole through all (round faces and round edges only), a sketch or construction geometry. Any other step (a
revolve, a loft, a sweep, a pattern, a round, a move, a step the step kind table does not know) may make an edge or a
face where an extrude's would lie, so the general sizes stay.

An extrude is straight here when it starts on its sketch plane (or at an offset from it), has no taper, each side
ends at a distance, its outlines are read in full and lie in one plane, and its measured end face (`end_offset`)
shows where its end caps lie. In a plain part:

- a side edge (along the axis, over a corner of an outline, between the end caps), an end face (across the axis,
  inside the outline, at an end cap), an edge across the axis over a line of an outline at an end cap, and a flat
  side face over such a line between the end caps were made by that extrude. They turn only with the sketch planes
  (`reach.placement_sizes`; of every extrude of the part, since an edge where two extrudes meet turns with both) and
  with the line, which keeps its direction at every size when the sketch solver gives its two ends a gap of zero
  across or along, or a constant gap (`sketch_solve`, default reading). A sketch graph that cannot be solved keeps
  the general sizes. Two such flat faces keep the angle between them at every size but the sizes of the sketch
  planes;
- when every extrude is one sided, makes or joins material along the hole and spans the same two planes, and each
  hole goes in at one of these planes and out at the other inside an outline, the part is that thick wherever a hole
  can go (outside every outline it cuts nothing). The thickness then changes only with the lengths and sketch planes
  of the extrudes (a plane may tilt against the hole) and, for several extrudes, with their start offsets.
"""
from ..capture_model import step_kinds
from ..geometry import footprint, plane2d, vec
from ..sketch_solve.constants import constants_of
from ..sketch_solve.solve import solve_sketch
from . import reach

# How far (mm) a point may lie from where an outline puts it.
TOL_MM = 1e-4
# How far (mm) a point may lie from an end cap, and a measured end cap from where the extrude's length puts it.
CAP_TOL = 1e-3
# How far from 1 the cosine of two directions may be for them to count as one line.
PARALLEL_TOL = 1e-6


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _usable(profile):
    """True for an outline of the part's own sketch with its frame read."""
    frame = profile.get("frame") if isinstance(profile, dict) else None
    return (isinstance(frame, dict) and all(isinstance(frame.get(k), list) for k in ("origin", "x", "y", "z"))
            and not profile.get("face") and not profile.get("foreign") and not profile.get("borrowed"))


def _one_plane(profiles):
    """True when every outline lies in the plane of the first."""
    first = profiles[0]["frame"]
    return all(_along(p["frame"]["z"], first["z"])
               and abs(vec.dot(vec.sub(p["frame"]["origin"], first["origin"]), vec.unit(first["z"]))) <= TOL_MM
               for p in profiles)


def _records(item):
    """The sketch records the step kind table lists for the type of `item`."""
    spec = step_kinds.step_type(item.get("type"))
    return spec.sketches if spec is not None else ()


def _caps(item):
    """The end caps `(low, high)` of a straight extrude (a step with outlines and the extent of an extrude) along the
    normal of its first outline's sketch, or None."""
    data = _data(item)
    profiles = data.get("profiles")
    if (step_kinds.PROFILES not in _records(item) or "extent_type" not in data or data.get("thin")
            or not isinstance(profiles, list) or not profiles or not all(_usable(p) for p in profiles)
            or not _one_plane(profiles)):
        return None
    begin = data.get("start") or {}
    kind = begin.get("kind", "profilePlane")
    start = _number(begin.get("offset")) if kind == "offset" else 0.0 if kind == "profilePlane" else None
    one, two = data.get("side_one"), data.get("side_two")
    sides = [one] + ([two] if two is not None else [])
    end = _number(data.get("end_offset"))
    if start is None or end is None or not all(
            isinstance(s, dict) and s.get("kind") == "distance" and not s.get("taper_deg")
            and _number(s.get("distance")) is not None for s in sides):
        return None
    first = abs(one["distance"])
    if data.get("extent_type") == "one" and two is None:
        return tuple(sorted((start, end))) if abs(abs(end - start) - first) <= CAP_TOL else None
    if data.get("extent_type") == "two" and two is not None and kind == "profilePlane" \
            and one["distance"] > 0 and two["distance"] > 0:
        # The sides run either way from the sketch plane; the measured end face tells which side runs along +z.
        sign = 1.0 if end > 0 else -1.0
        if abs(abs(end) - first) <= CAP_TOL:
            return tuple(sorted((sign * first, -sign * two["distance"])))
        if abs(abs(end) - two["distance"]) <= CAP_TOL:
            return tuple(sorted((-sign * first, sign * two["distance"])))
    return None


def _through_hole(item):
    """True for a simple hole through all: it makes round faces and round edges only."""
    data = _data(item)
    return (step_kinds.HOLE_POINTS in _records(item) and data.get("hole_type") == "simple"
            and not data.get("counterbore") and not data.get("countersink")
            and (data.get("extent") or {}).get("kind") == "throughAll")


def _plain_body(timeline, before):
    """`[(extrude item, caps)]` of the straight extrudes of the body's component before timeline index `before`, or
    None when another step before it may have made or changed an edge or face (see the module text)."""
    if not isinstance(before, int):
        return None
    out = []
    for item in timeline:
        index = item.get("index")
        if not isinstance(index, int) or index >= before or item.get("suppressed"):
            continue
        kind = item.get("type")
        if step_kinds.makes_no_body(kind):
            continue
        if item.get("in_target_component") is False:
            if step_kinds.keeps_to_own_bodies(kind):
                continue
            return None
        if _through_hole(item):
            continue
        caps = _caps(item)
        if caps is None:
            return None
        out.append((item, caps))
    return out


def _curves(profile):
    return [c for loop in profile.get("loops") or [] if isinstance(loop, dict)
            for c in loop.get("curves") or [] if isinstance(c, dict)]


def _ring(profile):
    """The outer loop of an outline as points, or None."""
    for loop in profile.get("loops") or []:
        curves = loop.get("curves") if isinstance(loop, dict) and loop.get("outer") else None
        if not curves:
            continue
        try:
            if len(curves) == 1 and curves[0].get("kind") == "circle":
                return footprint.polyline(curves[0])[:-1]
            chain = footprint.closed_chain(curves)
            return [p for c in chain for p in footprint.polyline(c)[:-1]] if chain else None
        except (KeyError, TypeError, ValueError, IndexError):  # a loop that is not read in full
            return None
    return None


def _along(a, b):
    return abs(abs(vec.dot(vec.unit(a), vec.unit(b))) - 1.0) <= PARALLEL_TOL


def _across(a, b):
    return abs(vec.dot(vec.unit(a), vec.unit(b))) <= PARALLEL_TOL


def _at_cap(z, caps):
    return any(abs(z - c) <= CAP_TOL for c in caps)


def _between(z, caps):
    return caps[0] - CAP_TOL <= z <= caps[1] + CAP_TOL


def _graph(capture, profile):
    """The sketch graph record of an outline's sketch: by its token, else by a name only one record has."""
    graphs = [g for g in capture.get("sketch_graphs") or [] if isinstance(g, dict) and not g.get("error")]
    token = profile.get("sketch_token")
    found = [g for g in graphs if token and g.get("token") == token] or \
        [g for g in graphs if not token and g.get("sketch") == profile.get("sketch")]
    return found[0] if len(found) == 1 else None


def _line_gaps(capture, table, source, line):
    """The gaps `[x, y]` from the start to the end of the sketch line `line` (`start`, `end` in the sketch's own
    plane) of the sketch `source` names (`sketch_token`, else `sketch`), as `Expr`s of the sketch's dimensions and
    measured inputs, from the sketch solver (default reading); None when the line is not in the sketch graph or the
    solver does not give both ends."""
    record = _graph(capture, source)
    if record is None or not isinstance(line, dict):
        return None
    xy = {p["id"]: p["xy"] for p in record.get("points") or [] if isinstance(p, dict) and p.get("xy")}
    ends = [line.get("start"), line.get("end")]
    if not all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in ends):
        return None

    def at(point):
        return next((pid for pid, found in xy.items() if vec.length(vec.sub(list(found[:2]) + [0.0],
                                                                              list(point[:2]) + [0.0])) <= TOL_MM),
                    None)
    ids = [at(p) for p in ends]
    if None in ids or not any(c.get("kind") == "line" and set(c.get("points") or ()) == set(ids)
                              for c in record.get("curves") or [] if isinstance(c, dict)):
        return None
    try:
        linked = bool(reach.linked_sizes(table, record.get("sketch")))
        fixed = reach.plane_fixed(table, capture.get("items") or [], source, None)
        solution = solve_sketch(record, None, constants_of(record, linked, fixed))
        a, b = solution.points.get(ids[0]), solution.points.get(ids[1])
        if not a or not b or not all(v.derived for v in a + b):
            return None
        return [b[k].expr - a[k].expr for k in (0, 1)]
    except Exception:  # a sketch the solver cannot read keeps the general sizes
        return None


def _keeps_direction(capture, table, profile, line):
    """True when the sketch solver gives the ends of the outline's `line` a gap that turns with no size."""
    gaps = _line_gaps(capture, table, profile, line)
    if gaps is None:
        return False
    zero = [g.is_constant and abs(g.const) <= TOL_MM for g in gaps]
    return any(zero) or all(g.is_constant for g in gaps)


def line_sizes(table, capture, item, source, line):
    """Fusion names of the ticked sizes that may turn the sketch line `line` (`start`, `end` in the sketch's own
    plane) that the step `item` uses, or change its length, in table order. `source` names the sketch (`sketch`,
    `sketch_token`) and says what it sits on (`reference`, `projected`), as for `reach.sketch_line_sizes`, which gives
    the answer in general. When the sketch solver gives the gap between the line's ends as formulas of the sketch's
    own dimensions (no projected or linked geometry), only the sizes behind those dimensions and the sizes that may
    move the sketch plane (`reach.placement_sizes`) can turn or stretch the line."""
    if table is None:
        return []
    timeline = capture.get("items") or []
    sketch = source.get("sketch") or ""
    names = reach.sketch_line_sizes(table, timeline, item, sketch, source.get("reference"), source.get("projected"))
    gaps = _line_gaps(capture, table, source, line)
    if gaps is not None:
        leaves = {leaf for gap in gaps for leaf in gap.names()}
        if not any(leaf.startswith("@") for leaf in leaves):
            on = source.get("reference") if isinstance(source.get("reference"), dict) else {"kind": "other"}
            found = set(reach.placement_sizes(table, timeline, {"sketch": sketch, "reference": on}, item.get("index")))
            for leaf in leaves:
                found |= set(table.depends(leaf))
            names = names & found
    return [name for name in table.ticked if name in names]


def _runs_along(frame, line, direction):
    """True when the outline `line` (sketch coordinates) runs along the model `direction`."""
    run = vec.sub(vec.frame_apply(frame, list(line["end"]) + [0.0]),
                  vec.frame_apply(frame, list(line["start"]) + [0.0]))
    return vec.length(run) > TOL_MM and _along(run, direction)


def _outlines(body):
    """`(profile, caps)` of each outline of the straight extrudes `body`."""
    return [(profile, caps) for item, caps in body for profile in _data(item)["profiles"]]


def _edge_match(capture, table, body, record, direction):
    """True when an edge of the part (`record`, with `edge_points`: the middle of an open edge) that runs along
    `direction` lies where a straight extrude of `body` made it, and every outline line it lies over keeps its
    direction."""
    points = [p for p in record.get("edge_points") or [] if isinstance(p, (list, tuple)) and len(p) == 3]
    if not points:
        return False
    matched = False
    for profile, caps in _outlines(body):
        frame = profile["frame"]
        local = [vec.frame_to_local(frame, p) for p in points]
        if _along(direction, frame["z"]):
            corners = [c[k] for c in _curves(profile) for k in ("start", "end") if isinstance(c.get(k), list)]
            if not all(_between(p[2], caps) and any(abs(p[0] - c[0]) <= TOL_MM and abs(p[1] - c[1]) <= TOL_MM
                                                    for c in corners) for p in local):
                continue
        elif _across(direction, frame["z"]):
            line = next((c for c in _curves(profile) if c.get("kind") == "line" and _runs_along(frame, c, direction)
                         and all(_at_cap(p[2], caps) and plane2d.to_segment(p[:2], c["start"], c["end"]) <= TOL_MM
                                 for p in local)), None)
            if line is None:
                continue
            if not _keeps_direction(capture, table, profile, line):
                return False
        else:
            continue
        matched = True
    return matched


def _face_match(capture, table, body, record, direction):
    """True when a flat face of the part whose normal is `direction` lies where a straight extrude of `body` made
    it: an end cap (its point inside the outline) or a side face over a line of the outline that keeps its
    direction."""
    point = record.get("face_point")
    if record.get("surface") not in (None, "Plane") or not isinstance(point, (list, tuple)) or len(point) != 3:
        return False
    matched = False
    for profile, caps in _outlines(body):
        frame = profile["frame"]
        local = vec.frame_to_local(frame, point)
        if _along(direction, frame["z"]):
            ring = _ring(profile)
            if not _at_cap(local[2], caps) or not ring or not plane2d.inside_ring(local[:2], ring):
                continue
        elif _across(direction, frame["z"]):
            line = next((c for c in _curves(profile) if c.get("kind") == "line"
                         and _runs_along(frame, c, vec.cross(frame["z"], direction))
                         and plane2d.to_segment(local[:2], c["start"], c["end"]) <= TOL_MM), None)
            if line is None or not _between(local[2], caps):
                continue
            if not _keeps_direction(capture, table, profile, line):
                return False
        else:
            continue
        matched = True
    return matched


def _plane_sizes(table, timeline, body):
    """The sizes that may move the sketch plane of any extrude of `body`."""
    found = set()
    for item, _ in body:
        for profile in _data(item)["profiles"]:
            found |= set(reach.placement_sizes(table, timeline, profile, item.get("index")))
    return found


def direction_sizes(table, capture, item, which):
    """Fusion names of the ticked sizes that may turn the direction `which` ("one" or "two") of the rectangular
    pattern `item`, in table order. A direction taken from an edge or a face that a straight extrude of a plain part
    made (see the module text) turns with the sketch planes of the part's extrudes; any other one gives
    `reach.direction_sizes`."""
    if table is None:
        return []
    timeline = capture.get("items") or []
    data = _data(item)
    place = data.get("direction_%s_place" % which)
    direction = data.get("direction_%s" % which)
    if isinstance(place, dict) and place.get("own") and isinstance(direction, (list, tuple)) \
            and vec.length(direction) > 0:
        body = _plain_body(timeline, item.get("index"))
        kind = place.get("entity_type")
        matched = False
        if body and kind == "BRepEdge":
            matched = _edge_match(capture, table, body, place, list(direction))
        elif body and kind == "BRepFace":
            matched = _face_match(capture, table, body, place, list(direction))
        if matched:
            found = _plane_sizes(table, timeline, body)
            return [name for name in table.ticked if name in found]
    return reach.direction_sizes(table, timeline, item, which)


def angle_sizes(table, capture, item, faces):
    """Fusion names of the ticked sizes that may change the angle between `faces`, in table order. `faces` are records
    of faces of the part that the step `item` uses, each with `face_point`, `surface` and its outward `normal`. Flat
    faces that straight extrudes of a plain part made (see the module text) turn only with the sketch planes of the
    part's extrudes; any other face may turn with every size an item of the body's component reads before the step
    (`reach.any_face_sizes`)."""
    if table is None:
        return []
    timeline = capture.get("items") or []
    body = _plain_body(timeline, item.get("index")) if faces else None
    if body and all(_flat_face_match(capture, table, body, face) for face in faces):
        found = _plane_sizes(table, timeline, body)
        return [name for name in table.ticked if name in found]
    return reach.any_face_sizes(table, timeline, item)


def _flat_face_match(capture, table, body, face):
    normal = face.get("normal") if isinstance(face, dict) else None
    if not isinstance(normal, (list, tuple)) or len(normal) != 3 or vec.length(normal) <= 0:
        return False
    return _face_match(capture, table, body, face, list(normal))


def through_sizes(table, timeline, item, data):
    """Fusion names of the ticked sizes that may change how thick the part is where the holes of `item` (its `data`)
    go through, in table order. In a plain part that is as thick wherever the holes can go (see the module text), the
    sizes of the extrudes' lengths and sketch planes (and, for several extrudes, their start offsets); else
    `reach.hole_end_sizes`."""
    if table is None:
        return []
    found = _even_sizes(table, timeline, item, data)
    if found is not None:
        return [name for name in table.ticked if name in found]
    return reach.hole_end_sizes(table, timeline, item, data)


def _even_sizes(table, timeline, item, data):
    """The sizes that may change the thickness of a plain part made of one sided extrudes that all span the two
    planes each hole goes in and comes out at (`positions`, `end_points`), or None."""
    positions = [p for p in data.get("positions") or [] if isinstance(p, (list, tuple)) and len(p) == 3]
    ends = [p for p in data.get("end_points") or [] if isinstance(p, (list, tuple)) and len(p) == 3]
    normal = data.get("direction")
    if not positions or len(ends) != len(positions) or not isinstance(normal, (list, tuple)) \
            or vec.length(normal) <= 0:
        return None
    body = _plain_body(timeline, item.get("index"))
    if not body:
        return None
    axis = vec.unit(list(normal))
    span = None
    for extrude, caps in body:
        frame = _data(extrude)["profiles"][0]["frame"]
        if (_data(extrude).get("operation") not in ("newBody", "join") or _data(extrude).get("extent_type") != "one"
                or not _along(axis, frame["z"])):
            return None
        planes = sorted(vec.dot(vec.add(frame["origin"], vec.scale(frame["z"], c)), axis) for c in caps)
        if span is not None and any(abs(a - b) > CAP_TOL for a, b in zip(span, planes)):
            return None
        span = planes
    outlines = [(profile, _ring(profile)) for profile, _ in _outlines(body)]
    for a, b in zip(positions, ends):
        low, high = sorted((vec.dot(a, axis), vec.dot(b, axis)))
        if abs(low - span[0]) > CAP_TOL or abs(high - span[1]) > CAP_TOL:
            return None
        if not any(ring and plane2d.inside_ring(vec.frame_to_local(profile["frame"], a)[:2], ring)
                   for profile, ring in outlines):
            return None
    keys = ("side_one.distance", "start.offset") if len(body) > 1 else ("side_one.distance",)
    found = _plane_sizes(table, timeline, body)
    for extrude, _ in body:
        params = _data(extrude).get("params") or {}
        for key in keys:
            entry = params.get(key)
            if isinstance(entry, dict) and entry.get("name"):
                found |= set(table.depends(entry["name"]))
    return found & set(table.ticked)
