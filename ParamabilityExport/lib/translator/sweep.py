"""Sweep feature handler (SweepFeature): one sketch outline carried along a path of sketch curves or body edges.

The path decides what is written (`paths.plan` orders it and checks the limits of the recipe's sweep step):
- a straight path is an extrude of the outline (`extrude.handle`);
- one arc or a full circle is a revolve of the outline about the arc's axis (`revolve.handle`);
- a chain of lines, arcs and free curves in one plane, or of lines and tangent arcs in 3D, is a `sweep` step.

The outline follows sizes as an extrude outline does. The path is written as measured, so the sizes behind its sketch
are marked: a path that follows sizes needs its own motion values. A new body must have the volume the outline area
and the path give. Twist, taper, guide rails, a path that is not square to the outline, closed paths other than a
circle and sweeps along part of a path are refused.
"""
import copy
import math

from . import extrude, loops, paths, placement, revolve, sketch_motion, values, vec
from .extrude import COMBINE
from .footprint import is_full, polyline
from .result import Refusal, StepResult
from .sizes import sketch_sizes
from .values import Quantity

ZERO_TOL = 1e-6
VOLUME_RELATIVE_TOL = 0.01
VOLUME_ABSOLUTE_TOL = 1e-3
CENTROID_ON_PATH_TOL = 0.01   # the path runs through the outline's centroid when it starts this close to it (mm)

UNREADABLE = "A setting of this sweep could not be read from Fusion."
PATH_UNREADABLE = "The path of this sweep could not be read from Fusion."
MIXED_PATH = "The path of this sweep mixes sketch curves and body edges, which is not copied yet."
SEVERAL_OUTLINES = "Sweeps of several outlines at once are not copied yet."
FACE_OUTLINE = "The outline of this sweep is a face of the part."
TWISTED = "Twisted sweeps are not copied yet."
TAPERED = "Tapered sweeps are not copied yet."
RAIL = "Sweeps with a guide rail are not copied yet."
OTHER_KIND = "This kind of sweep is not copied yet."
KEEPS_DIRECTION = "The outline keeps one direction along a bent path, which is not copied yet."
PART_OF_PATH = "This sweep covers only part of its path, which is not copied yet."
NOT_MATCHING = "The result of this sweep does not match its outline and path, so it is not copied yet."


# ---- the outline -----------------------------------------------------------------------------------------------

def _profile_points(profile):
    """Points along every curve of the outline, in the coordinates of the part."""
    frame = profile["frame"]
    return [vec.frame_apply(frame, [u, v, 0.0]) for loop in profile.get("loops") or []
            for curve in loop.get("curves") or [] for u, v in polyline(curve)]


def _loop_polygon(curves):
    """The points of one outline loop in order, or None when its curves do not close."""
    if len(curves) == 1 and is_full(curves[0]):
        return polyline(curves[0])[:-1]
    chain = loops.closed_chain(curves)
    return None if chain is None else [p for link in chain for p in polyline(link)[:-1]]


def _centroid(profile):
    """The centre of the area of the outline (holes taken out) in its sketch plane, or None when a loop is open."""
    area = cx = cy = 0.0
    for loop in profile.get("loops") or []:
        points = _loop_polygon(loop.get("curves") or [])
        if not points or len(points) < 3:
            return None
        twice = part_x = part_y = 0.0
        for a, b in zip(points, points[1:] + points[:1]):
            cross = a[0] * b[1] - b[0] * a[1]
            twice += cross
            part_x += (a[0] + b[0]) * cross
            part_y += (a[1] + b[1]) * cross
        if abs(twice) <= 1e-12:
            return None
        weight = 1.0 if loop.get("outer") else -1.0
        size = abs(twice) / 2.0
        area += weight * size
        cx += weight * size * part_x / (3.0 * twice)
        cy += weight * size * part_y / (3.0 * twice)
    return [cx / area, cy / area] if area > 1e-12 else None


def _outline(data):
    """The one outline profile, or a Refusal."""
    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        return Refusal(UNREADABLE)
    if not profiles:
        return Refusal("This sweep has no sketch outline.")
    if len(profiles) > 1:
        return Refusal(SEVERAL_OUTLINES)
    profile = profiles[0]
    if not isinstance(profile, dict):
        return Refusal(UNREADABLE)
    if profile.get("face"):
        return Refusal(FACE_OUTLINE)
    refusal = loops.outline_refusal(profile)
    if refusal is not None:
        return refusal
    if not isinstance(profile.get("frame"), dict):
        return Refusal("A sketch outline has no readable position.")
    return profile


# ---- settings --------------------------------------------------------------------------------------------------

def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _settings_refusal(data):
    """A Refusal for a setting the copy does not follow (twist, taper, guide rail, other kinds, part of the path)."""
    if data.get("rail") is not None:
        return Refusal(RAIL)
    twist, taper = data.get("twist_deg"), data.get("taper_deg")
    one, two = data.get("distance_one"), data.get("distance_two")
    if not (_number(twist) and _number(taper) and _number(one)) or data.get("orientation") is None:
        return Refusal(UNREADABLE)
    if abs(twist) > ZERO_TOL:
        return Refusal(TWISTED)
    if abs(taper) > ZERO_TOL:
        return Refusal(TAPERED)
    if data["orientation"] not in ("perpendicular", "parallel"):
        return Refusal(OTHER_KIND)
    if abs(one - 1.0) > ZERO_TOL or (_number(two) and abs(two) > ZERO_TOL):
        return Refusal(PART_OF_PATH)
    return None


def _pin_settings(ctx, item):
    """Values the copy writes as fixed settings: a size that moves one is marked."""
    name = item.get("name", "a sweep")
    for path, what in (("twist_deg", "twist"), ("taper_deg", "taper"), ("distance_one", "length along its path"),
                       ("distance_two", "length along its path")):
        values.pin(ctx, item, path, "it sets the %s of %s, which the copy keeps as it is now" % (what, name))


# ---- the volume ------------------------------------------------------------------------------------------------

def _made_volume(item, data):
    """The volume the sweep made (the body after, less the body before), or None when it was not measured."""
    after = data.get("volume_after")
    if after is None:
        after = (item.get("target_after") or {}).get("volume_mm3")
    if after is None:
        return None
    before = data.get("volume_before")
    if before is None:
        before = (item.get("target_before") or {}).get("volume_mm3") or 0.0
    return after - before


def _axis_distance(point, axis):
    along = vec.sub(point, axis["point"])
    direction = vec.unit(axis["dir"])
    return vec.length(vec.sub(along, vec.scale(direction, vec.dot(along, direction))))


def _expected_volume(profile, area, found):
    """The volume the outline sweeps along the path (area times the length its centre travels), or None when that is
    not known: a bent path counts only when it runs through the centre of the outline."""
    centre = _centroid(profile)
    if centre is None:
        return None
    middle = vec.frame_apply(profile["frame"], [centre[0], centre[1], 0.0])
    if found.kind == "line":
        return area * found.length
    if found.kind in ("arc", "circle"):
        return area * math.radians(found.angle_deg) * _axis_distance(middle, found.axis)
    if vec.length(vec.sub(middle, found.start)) <= CENTROID_ON_PATH_TOL:
        return area * found.length
    return None


def _volume_refusal(item, data, combine, profile, found):
    """A Refusal when a new body does not have the volume the outline and the path give; None when it does, or when
    it cannot be told."""
    areas = data.get("areas")
    if combine != "new" or not isinstance(areas, list) or len(areas) != 1 or not _number(areas[0]) or areas[0] <= 0:
        return None
    made = _made_volume(item, data)
    expected = _expected_volume(profile, areas[0], found)
    if made is None or expected is None:
        return None
    if abs(made - expected) > VOLUME_RELATIVE_TOL * expected + VOLUME_ABSOLUTE_TOL:
        return Refusal(NOT_MATCHING)
    return None


# ---- sizes the copy cannot follow --------------------------------------------------------------------------------

def _mark_path(ctx, item, path, found):
    """The path is written as measured: the sizes behind its sketch (or, for edges, behind the steps written so far)
    stay free with a warning."""
    name = item.get("name", "a sweep")
    if ctx.table is None:
        return
    if path.get("kind") == "edges":
        if ctx.written_reads:
            ctx.doubt(ctx.written_reads, "%s follows edges of the part, which the copy keeps as measured" % name)
        return
    sketch = path.get("sketch") or ""
    names = sketch_sizes(ctx.table, sketch) if sketch else ()
    if names:
        ctx.doubt(names, "%s copies its path from %s as measured" % (name, sketch))


def _mark_borrowed(ctx, item, profile):
    """A sweep has no placer that checks an outline of another component against the part."""
    if not profile.get("borrowed") or ctx.table is None:
        return
    names = sketch_sizes(ctx.table, profile.get("sketch") or "")
    if names:
        ctx.doubt(names, "%s cannot check that its outline from %s still meets the part"
                  % (item.get("name", "a sweep"), profile.get("sketch") or "another component"))


def _keep_path_on_plane(ctx, item, drawn):
    """A path written as numbers starts on the plane the outline had when it was captured: a size that moves that
    plane is marked."""
    if drawn is None:
        return
    shift = drawn.plane_shift(ctx)
    if shift.sized:
        ctx.doubt(shift.reads, "%s starts its path on the plane of its outline, which the copy cannot move with it"
                  % item.get("name", "a sweep"))


# ---- what is written -------------------------------------------------------------------------------------------

def _common(data, profile):
    return {
        "operation": data["operation"],
        "profiles": [profile],
        "participants": data.get("participants") or [],
        "target_box_before": data.get("target_box_before"),
    }


def _as_extrude(item, data, profile, found, ctx):
    """The sweep along a straight path as the extrude it equals."""
    forward = vec.dot(found.direction, vec.unit(profile["frame"]["z"])) > 0
    built = dict(_common(data, profile), start={"kind": "profilePlane"}, extent_type="one", thin=False,
                 side_one={"kind": "distance", "distance": found.length, "taper_deg": 0.0,
                           "direction": 1 if forward else -1},
                 side_two=None, symmetric=None)
    return extrude.handle(dict(item, data=built), ctx)


def _as_revolve(item, data, combine, profile, found, ctx):
    """The sweep along an arc or a full circle as the revolve it equals. The start face of the turn faces against
    the travel (along it for a cut), which fixes which way the axis turns."""
    toward = 1.0 if combine == "cut" else -1.0
    built = dict(_common(data, profile), project_axis=True,
                 axis={"point": found.axis["point"], "dir": found.axis["dir"], "fixed": True},
                 extent={"kind": "angle", "angle_deg": found.angle_deg, "symmetric": False},
                 start_face_normal=vec.scale(found.direction, toward))
    return revolve.handle(dict(item, data=built), ctx)


def _as_sweep(item, combine, profile, found, ctx):
    """A `sweep` step: the outline on its own placement and the flat or corners path."""
    outcome = loops.profile_loops(profile)
    if isinstance(outcome, Refusal):
        return outcome
    outer, inners = outcome
    drawn = sketch_motion.outline(ctx, item, profile, outer, inners, [(0, profile)])
    on = placement.from_frame(profile["frame"])
    if drawn is not None:
        on["origin"] = drawn.origin(ctx, Quantity(0.0))
        outer, inners = drawn.written(ctx)
    _keep_path_on_plane(ctx, item, drawn)
    sketch = {"on": on, "outer": outer}
    if inners:
        sketch["inner"] = inners
    out = StepResult()
    out.add({"kind": "sweep", "sketch": sketch, "path": copy.deepcopy(found.recipe), "combine": combine})
    return out


def handle(item, ctx):
    data = item.get("data") or {}
    operation = data.get("operation")
    if operation == "newComponent":
        return Refusal("Sweeps that make a new component are not copied.")
    if operation not in COMBINE:
        return Refusal("This sweep combines with the part in a way that is not copied yet.")
    if data.get("solid") is not True:
        return Refusal("Surface sweeps are not copied." if data.get("solid") is False else UNREADABLE)
    combine = COMBINE[operation]
    profile = _outline(data)
    if isinstance(profile, Refusal):
        return profile
    refusal = _settings_refusal(data)
    if refusal is not None:
        return refusal
    path = data.get("path")
    if not isinstance(path, dict):
        return Refusal(PATH_UNREADABLE)
    if path.get("kind") == "mixed":
        return Refusal(MIXED_PATH)
    found = paths.plan(path, profile["frame"], _profile_points(profile))
    if isinstance(found, Refusal):
        return found
    if data["orientation"] == "parallel" and found.kind != "line":
        return Refusal(KEEPS_DIRECTION)
    refusal = _volume_refusal(item, data, combine, profile, found)
    if refusal is not None:
        return refusal
    _pin_settings(ctx, item)
    _mark_path(ctx, item, path, found)
    if found.kind != "line":
        _mark_borrowed(ctx, item, profile)
    if found.kind == "line":
        outcome = _as_extrude(item, data, profile, found, ctx)
    elif found.kind in ("arc", "circle"):
        outcome = _as_revolve(item, data, combine, profile, found, ctx)
    else:
        outcome = _as_sweep(item, combine, profile, found, ctx)
    if path.get("kind") == "edges" and isinstance(outcome, StepResult):
        for entry in outcome.entries:
            entry.repeatable = False
    return outcome
