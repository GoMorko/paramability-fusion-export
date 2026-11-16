"""Edges and faces of the part matched to the straight extrude that made them: which sizes may turn a pattern
direction taken from one, and which may change the thickness a tapped hole goes through.

Both outputs write such a direction and such a thread length as numbers. In general every size read before the step
may change them (`reach.reference_sizes`, `reach.hole_end_sizes`). The capture can show less:

- a side edge of a straight extrude (along its axis), and a flat end face across that axis, turn only with the
  extrude's sketch plane (`reach.placement_sizes`);
- an edge across the axis that lies over a line of the extrude's outline runs along that line, and a flat side face
  over such a line stands square to it: they turn only with the sketch plane and with the line, and the line keeps
  its direction at every size when the sketch solver gives its two ends a gap of zero across or along, or a constant
  gap (`sketch_solve`, default reading);
- the thickness between the two end faces of a one sided straight extrude changes only with its length.

An extrude is straight here when it starts on its sketch plane (or at an offset from it), has no taper and each side
ends at a distance. The match is by where the edge or face lies now. A step between the extrude and the step that
moves bodies, may turn faces (`StepType.turns_faces`) or is not in the step kind table voids the match, and so does a
sketch graph that cannot be solved. Without a match the general sizes stay. Several matching extrudes give the sizes of
all of them.
"""
from ..capture_model import step_kinds
from ..geometry import footprint, plane2d, vec
from ..sketch_solve.constants import constants_of
from ..sketch_solve.solve import solve_sketch
from . import reach

# How far (mm) a point may lie from where an outline puts it.
TOL_MM = 1e-4
# How far from 1 the cosine of two directions may be for them to count as one line.
PARALLEL_TOL = 1e-6


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _straight(data):
    if not isinstance(data.get("profiles"), list) or "extent_type" not in data or data.get("thin"):
        return False
    if (data.get("start") or {}).get("kind", "profilePlane") not in ("profilePlane", "offset"):
        return False
    sides = [data.get("side_one")] + ([data["side_two"]] if data.get("side_two") is not None else [])
    return all(isinstance(s, dict) and s.get("kind") == "distance" and not s.get("taper_deg") for s in sides)


def _voids(item):
    """True for a step that may move, turn or reshape what an earlier extrude made."""
    if item.get("suppressed") or item.get("in_target_component") is False:
        return False
    spec = step_kinds.step_type(item.get("type"))
    if spec is None:
        return True
    return spec.role == step_kinds.MODELING and (spec.moves_bodies or spec.turns_faces)


def _profiles(timeline, before):
    """`(extrude item, profile)` of the straight extrudes of the body's component before timeline index `before`
    with no step between them and `before` that voids a match, each profile with its sketch frame."""
    out = []
    for item in timeline:
        index = item.get("index")
        if (not isinstance(index, int) or index >= before or item.get("suppressed")
                or item.get("in_target_component") is False or not _straight(_data(item))):
            continue
        if any(isinstance(i.get("index"), int) and index < i["index"] < before and _voids(i) for i in timeline):
            continue
        for profile in _data(item)["profiles"]:
            frame = profile.get("frame") if isinstance(profile, dict) else None
            if (isinstance(frame, dict) and all(isinstance(frame.get(k), list) for k in ("origin", "x", "y", "z"))
                    and not profile.get("face") and not profile.get("foreign") and not profile.get("borrowed")):
                out.append((item, profile))
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


def _graph(capture, profile):
    """The sketch graph record of an outline's sketch: by its token, else by a name only one record has."""
    graphs = [g for g in capture.get("sketch_graphs") or [] if isinstance(g, dict) and not g.get("error")]
    token = profile.get("sketch_token")
    found = [g for g in graphs if token and g.get("token") == token] or \
        [g for g in graphs if not token and g.get("sketch") == profile.get("sketch")]
    return found[0] if len(found) == 1 else None


def _keeps_direction(capture, table, profile, line):
    """True when the sketch solver gives the ends of the outline's `line` a gap that turns with no size."""
    record = _graph(capture, profile)
    if record is None:
        return False
    xy = {p["id"]: p["xy"] for p in record.get("points") or [] if isinstance(p, dict) and p.get("xy")}
    ends = [line.get("start"), line.get("end")]

    def at(point):
        return next((pid for pid, found in xy.items() if vec.length(vec.sub(list(found) + [0.0],
                                                                              list(point) + [0.0])) <= TOL_MM), None)
    ids = [at(p) for p in ends]
    if None in ids or not any(c.get("kind") == "line" and set(c.get("points") or ()) == set(ids)
                              for c in record.get("curves") or [] if isinstance(c, dict)):
        return False
    try:
        linked = bool(reach.linked_sizes(table, record.get("sketch")))
        solution = solve_sketch(record, None, constants_of(record, linked))
        a, b = solution.points.get(ids[0]), solution.points.get(ids[1])
        if not a or not b or not all(v.derived for v in a + b):
            return False
        gaps = [b[k].expr - a[k].expr for k in (0, 1)]
    except Exception:  # a sketch the solver cannot read keeps the general sizes
        return False
    zero = [g.is_constant and abs(g.const) <= TOL_MM for g in gaps]
    return any(zero) or all(g.is_constant for g in gaps)


def _turners(capture, table, timeline, item, profile, line=None):
    """The sizes that may turn what lies along the extrude's axis or across it (`line`: over that outline line), or
    None when the line may turn."""
    if line is not None and not _keeps_direction(capture, table, profile, line):
        return None
    return set(reach.placement_sizes(table, timeline, profile, item.get("index")))


def _edge_match(capture, table, timeline, step, record, direction):
    """The sizes that may turn an edge of the part (`record`, with `edge_points`: the middle of an open edge) that
    runs along `direction`, or None without a match."""
    points = [p for p in record.get("edge_points") or [] if isinstance(p, (list, tuple)) and len(p) == 3]
    if not points:
        return None
    found, matched = set(), False
    for item, profile in _profiles(timeline, step.get("index")):
        frame = profile["frame"]
        local = [vec.frame_to_local(frame, p) for p in points]
        if _along(direction, frame["z"]):
            corners = [c[k] for c in _curves(profile) for k in ("start", "end") if isinstance(c.get(k), list)]
            if not all(any(abs(p[0] - c[0]) <= TOL_MM and abs(p[1] - c[1]) <= TOL_MM for c in corners)
                       for p in local):
                continue
            names = _turners(capture, table, timeline, item, profile)
        elif _across(direction, frame["z"]):
            line = next((c for c in _curves(profile) if c.get("kind") == "line" and _runs_along(frame, c, direction)
                         and all(plane2d.to_segment(p[:2], c["start"], c["end"]) <= TOL_MM for p in local)), None)
            if line is None:
                continue
            names = _turners(capture, table, timeline, item, profile, line)
        else:
            continue
        if names is None:
            return None
        found |= names
        matched = True
    return found if matched else None


def _runs_along(frame, line, direction):
    """True when the outline `line` (sketch coordinates) runs along the model `direction`."""
    run = vec.sub(vec.frame_apply(frame, list(line["end"]) + [0.0]),
                  vec.frame_apply(frame, list(line["start"]) + [0.0]))
    return vec.length(run) > TOL_MM and _along(run, direction)


def _face_match(capture, table, timeline, step, record, direction):
    """The sizes that may turn a flat face of the part whose normal is `direction`: an end face across the axis of a
    straight extrude (its point inside the outline), or a side face over a line of its outline. None without a match."""
    point = record.get("face_point")
    if record.get("surface") not in (None, "Plane") or not isinstance(point, (list, tuple)) or len(point) != 3:
        return None
    found, matched = set(), False
    for item, profile in _profiles(timeline, step.get("index")):
        frame = profile["frame"]
        local = vec.frame_to_local(frame, point)
        if _along(direction, frame["z"]):
            ring = _ring(profile)
            if not ring or not plane2d.inside_ring(local[:2], ring):
                continue
            names = _turners(capture, table, timeline, item, profile)
        elif _across(direction, frame["z"]):
            line = next((c for c in _curves(profile) if c.get("kind") == "line"
                         and _runs_along(frame, c, vec.cross(frame["z"], direction))
                         and plane2d.to_segment(local[:2], c["start"], c["end"]) <= TOL_MM), None)
            if line is None:
                continue
            names = _turners(capture, table, timeline, item, profile, line)
        else:
            continue
        if names is None:
            return None
        found |= names
        matched = True
    return found if matched else None


def direction_sizes(table, capture, item, which):
    """Fusion names of the ticked sizes that may turn the direction `which` ("one" or "two") of the rectangular
    pattern `item`, in table order. A direction taken from an edge or a face of the part that matches a straight
    extrude (see the module text) turns with that extrude's sketch plane, and with its outline line when that line may
    turn; any other one gives `reach.direction_sizes`."""
    if table is None:
        return []
    timeline = capture.get("items") or []
    data = _data(item)
    place = data.get("direction_%s_place" % which)
    direction = data.get("direction_%s" % which)
    if isinstance(place, dict) and place.get("own") and isinstance(direction, (list, tuple)) \
            and vec.length(direction) > 0:
        kind = place.get("entity_type")
        found = None
        if kind == "BRepEdge":
            found = _edge_match(capture, table, timeline, item, place, list(direction))
        elif kind == "BRepFace":
            found = _face_match(capture, table, timeline, item, place, list(direction))
        if found is not None:
            return [name for name in table.ticked if name in found]
    return reach.direction_sizes(table, timeline, item, which)


def through_sizes(table, timeline, item, data):
    """Fusion names of the ticked sizes that may change how thick the part is where the holes of `item` (its `data`)
    go through, in table order. When every hole goes in at one end face of a one sided straight extrude across its
    axis and comes out at the other (`positions` and `end_points`), only the sizes of that extrude's length; else
    `reach.hole_end_sizes`."""
    if table is None:
        return []
    positions = [p for p in data.get("positions") or [] if isinstance(p, (list, tuple)) and len(p) == 3]
    ends = [p for p in data.get("end_points") or [] if isinstance(p, (list, tuple)) and len(p) == 3]
    normal = data.get("direction")
    if positions and len(ends) == len(positions) and isinstance(normal, (list, tuple)) and vec.length(normal) > 0:
        for extrude, profile in _profiles(timeline, item.get("index")):
            found = _length_sizes(table, extrude, profile, positions, ends, list(normal))
            if found is not None:
                return [name for name in table.ticked if name in found]
    return reach.hole_end_sizes(table, timeline, item, data)


def _length_sizes(table, extrude, profile, positions, ends, normal):
    """The sizes of the extrude's length when every hole runs from one of its end faces to the other, else None."""
    data = _data(extrude)
    length = data.get("end_offset")
    if (data.get("extent_type") != "one" or not isinstance(length, (int, float))
            or not _along(normal, profile["frame"]["z"])):
        return None
    begin = data.get("start") or {}
    start = float(begin.get("offset") or 0.0) if begin.get("kind") == "offset" else 0.0
    # The measured end face is the far end cap when it lies a side's length from the start.
    if abs(abs(float(length) - start) - abs(float(data["side_one"].get("distance") or 0.0))) > 1e-3:
        return None
    caps = (start, float(length))
    ring = _ring(profile)
    if not ring:
        return None
    for a, b in zip(positions, ends):
        za, zb = vec.frame_to_local(profile["frame"], a), vec.frame_to_local(profile["frame"], b)
        if not plane2d.inside_ring(za[:2], ring) or not plane2d.inside_ring(zb[:2], ring):
            return None
        if sorted((abs(za[2] - caps[0]) <= TOL_MM, abs(zb[2] - caps[0]) <= TOL_MM)) != [False, True] \
                or not any(abs(z - caps[1]) <= TOL_MM for z in (za[2], zb[2])):
            return None
    found = (data.get("params") or {}).get("side_one.distance")
    return set(table.depends(found["name"])) & set(table.ticked) if isinstance(found, dict) and found.get("name") \
        else set()
