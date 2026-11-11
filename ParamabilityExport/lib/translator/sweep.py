"""Sweep feature handler (SweepFeature): one sketch outline carried along a path of sketch curves or body edges.

The path decides what is written (`paths.plan` orders it and checks the limits of the recipe's sweep step):
- a straight path is an extrude of the outline (`extrude.handle`);
- one arc or a full circle is a revolve of the outline about the arc's axis (`revolve.handle`);
- a chain of lines, arcs and free curves in one plane, or of lines and tangent arcs in 3D, is a `sweep` step; a closed
  chain in one plane is a `sweep` step along a closed flat path (a full circle stays a revolve unless it twists);
- a twist, a taper, or an outline kept in one direction (parallel) along a path that turns, also makes a `sweep` step
  (a line becomes a path of two points, an arc a flat path), with `twistDeg`, `taperDeg` and `orientation`.

The outline follows sizes as an extrude outline does. The path is written as measured, so the sizes behind its sketch
are marked: a path that follows sizes needs its own motion values. A new body must have the volume the outline area
and the path give; along a closed path that is Pappus' volume. Twist together with taper or parallel, tapers along
free curves, guide rails, a path that is not square to the outline, closed paths that bend in 3D or that taper or keep
the outline's direction, a twist along a closed path that is not whole turns, and sweeps along part of a path are
refused.

Fusion does not document how it measures the sweep taper (an offset of the outline or a scale) or which way a twist
turns. Until a hand test settles both, every written twist or taper marks the sizes behind it and the outline, and
adds a note asking the person to check the shape.
"""
import copy
import math

from . import borrowed, extrude, loops, paths, placement, revolve, sketch_motion, sweep_reach, sweep_taper, values, vec
from .extrude import COMBINE
from .footprint import is_full, polyline
from .result import Refusal, StepResult
from .sizes import construction_sizes, sketch_sizes
from .values import Quantity

ZERO_TOL = 1e-6
VOLUME_RELATIVE_TOL = 0.01
VOLUME_ABSOLUTE_TOL = 1e-3
CENTROID_ON_PATH_TOL = 0.01   # the path runs through the outline's centroid when it starts this close to it (mm)
WHOLE_TURN_TOL = 1e-6 / 360.0  # a twist along a closed path is whole turns within this share of a turn, as in the app
MAX_TAPER_DEG = 45.0          # the recipe takes a taper under this either way
MAX_TWIST_DEG = 3600.0        # the recipe takes a twist up to this either way
MAX_TAPER_STATIONS = 65       # the recipe builds a taper through at most this many places along the path
TAPER_MEANING_CONFIRMED = False   # set once a hand test shows how Fusion measures the sweep taper
TWIST_SIGN_CONFIRMED = False      # set once a hand test shows which way Fusion's twist turns
# Signs between Fusion's angles and the recipe's: Fusion's extrude taper widens the walls where the recipe narrows
# them, and the sweep is taken the same way. A twist turns the same way in both. Not yet confirmed on a real export.
TAPER_SIGN = -1
TWIST_SIGN = 1

UNREADABLE = "A setting of this sweep could not be read from Fusion."
PATH_UNREADABLE = "The path of this sweep could not be read from Fusion."
MIXED_PATH = "The path of this sweep mixes sketch curves and body edges, which is not copied yet."
SEVERAL_OUTLINES = "Sweeps of several outlines at once are not copied yet."
FACE_OUTLINE = "The outline of this sweep is a face of the part."
TWIST_AND_TAPER = "Sweeps that both twist and taper are not copied yet."
TAPER_CURVES = "Tapered sweeps along curves are not copied yet."
TAPER_STATIONS = "Tapered sweeps along a path with so many parts are not copied."
TWIST_CLOSED = "The twist of this sweep along a closed path is not whole turns, which is not copied."
TAPER_STEEP = "The taper of this sweep is too steep to copy."
TWIST_LONG = "The twist of this sweep is more than ten turns, which is not copied."
SCALED_OUTLINE = "This sweep scales its outline along the path, which is not copied yet."
PARALLEL_AND_SHAPE = "Sweeps that keep their outline in one direction and also twist or taper are not copied."
RAIL = "Sweeps with a guide rail are not copied yet."
RAIL_UNREADABLE = "The guide rail of this sweep could not be read from Fusion."
PATH_TOO_LONG = "The path of this sweep has more parts than can be read, so it is not copied."
OTHER_KIND = "This kind of sweep is not copied yet."
KEEPS_DIRECTION = paths.TURNS_BACK
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
    """A Refusal for a setting the copy does not follow (a twist with a taper or a fixed direction, a taper that is
    too steep, guide rail, other kinds, part of the path)."""
    rail = data.get("rail")
    if isinstance(rail, dict) and rail.get("kind") == "unread":
        return Refusal(RAIL_UNREADABLE)
    if rail is not None:
        return Refusal(RAIL)
    twist, taper = data.get("twist_deg"), data.get("taper_deg")
    one, two = data.get("distance_one"), data.get("distance_two")
    if not (_number(twist) and _number(taper) and _number(one)) or data.get("orientation") is None:
        return Refusal(UNREADABLE)
    if data["orientation"] not in ("perpendicular", "parallel"):
        return Refusal(OTHER_KIND)
    if abs(twist) > ZERO_TOL and abs(taper) > ZERO_TOL:
        return Refusal(TWIST_AND_TAPER)
    if data["orientation"] == "parallel" and (abs(twist) > ZERO_TOL or abs(taper) > ZERO_TOL):
        return Refusal(PARALLEL_AND_SHAPE)
    if abs(taper) >= MAX_TAPER_DEG:
        return Refusal(TAPER_STEEP)
    if abs(twist) > MAX_TWIST_DEG:
        return Refusal(TWIST_LONG)
    if abs(one - 1.0) > ZERO_TOL or (_number(two) and abs(two) > ZERO_TOL):
        return Refusal(PART_OF_PATH)
    return None


def _pin_settings(ctx, item, data, closed):
    """Values the copy writes as fixed settings: a size that moves one is marked. A twist or taper that is set is
    written as a value that can follow sizes instead (`_angle`), except a twist along a closed path, which has to
    stay whole turns."""
    name = item.get("name", "a sweep")
    for path, what in (("twist_deg", "twist"), ("taper_deg", "taper"), ("distance_one", "length along its path"),
                       ("distance_two", "length along its path")):
        if path in ("twist_deg", "taper_deg") and abs(data.get(path) or 0.0) > ZERO_TOL and not (
                closed and path == "twist_deg"):
            continue
        values.pin(ctx, item, path, "it sets the %s of %s, which the copy keeps as it is now" % (what, name))


def _angle(ctx, item, path, fusion_deg, sign, follows=True):
    """The twist or taper as the recipe writes it, a Quantity that follows sizes when its parameter does (unless
    `follows` is false: then it is the plain number, and `_pin_settings` marks the sizes behind it)."""
    if abs(fusion_deg) <= ZERO_TOL:
        return None
    if not follows:
        return Quantity(sign * fusion_deg)
    return values.quantity(ctx, item, path, sign * fusion_deg, dim="angle", sign=sign)


# ---- the volume ------------------------------------------------------------------------------------------------

def _made_volume(item, data):
    """The volume of the body a new body sweep made, or None when it was not measured. A walk of a tool body lists
    its own `volume_after` (null when not measured); otherwise the body of the capture is the one made."""
    if "volume_after" in data:
        return data["volume_after"]
    return (item.get("target_after") or {}).get("volume_mm3")


def _axis_distance(point, axis):
    along = vec.sub(point, axis["point"])
    direction = vec.unit(axis["dir"])
    return vec.length(vec.sub(along, vec.scale(direction, vec.dot(along, direction))))


def _closed_volume(area, middle, found, twisted):
    """The volume of an outline swept once round a closed flat path (Pappus): the area times the length its centre
    travels, which is the path's length less the centre's offset towards the inside times the turn of the path. A
    twisting outline turns its centre about the path, so that counts only when the centre sits on the path."""
    offset = vec.sub(middle, found.start)
    if twisted:
        return area * found.length if vec.length(offset) <= CENTROID_ON_PATH_TOL else None
    inward = vec.dot(offset, vec.cross(found.recipe["on"]["normal"], found.direction)) * found.winding
    return area * (found.length - inward * 2.0 * math.pi)


def _expected_volume(profile, area, found, twisted):
    """The volume the outline sweeps along the path (area times the length its centre travels), or None when that is
    not known: a bent path counts only when it runs through the centre of the outline."""
    centre = _centroid(profile)
    if centre is None:
        return None
    middle = vec.frame_apply(profile["frame"], [centre[0], centre[1], 0.0])
    if found.closed:
        return _closed_volume(area, middle, found, twisted)
    if found.kind == "line":
        return area * found.length
    if found.kind in ("arc", "circle"):
        return area * math.radians(found.angle_deg) * _axis_distance(middle, found.axis)
    if vec.length(vec.sub(middle, found.start)) <= CENTROID_ON_PATH_TOL:
        return area * found.length
    return None


def _volume_refusal(item, data, combine, profile, found):
    """A Refusal when a new body does not have the volume the outline and the path give; None when it does, or when
    it cannot be told. A taper or an outline kept in one direction changes the volume, so those are not told here."""
    areas = data.get("areas")
    if abs(data["taper_deg"]) > ZERO_TOL or data["orientation"] == "parallel" or combine != "new":
        return None
    if not isinstance(areas, list) or len(areas) != 1 or not _number(areas[0]) or areas[0] <= 0:
        return None
    made = _made_volume(item, data)
    expected = _expected_volume(profile, areas[0], found, abs(data["twist_deg"]) > ZERO_TOL)
    if made is None or expected is None:
        return None
    if abs(made - expected) > VOLUME_RELATIVE_TOL * expected + VOLUME_ABSOLUTE_TOL:
        return Refusal(NOT_MATCHING)
    return None


# ---- sizes the copy cannot follow --------------------------------------------------------------------------------

def _mark_path(ctx, item, path):
    """The path is written as measured: the sizes behind its sketch (or, for edges, behind the steps written so far)
    stay free with a warning."""
    name = item.get("name", "a sweep")
    if ctx.table is None:
        return
    if path.get("kind") == "edges":
        _mark_edges(ctx, name, path)
        return
    sketch = path.get("sketch") or ""
    names = sketch_sizes(ctx.table, sketch) if sketch else ()
    if names:
        ctx.doubt(names, "%s copies its path from %s as measured" % (name, sketch))
    _mark_sketch_place(ctx, name, path)


def _mark_edges(ctx, name, path):
    """Edges of the part move with the steps written so far; edges of another body of the component may move with any
    size."""
    if any(edge.get("body") and not ctx.is_target(edge["body"]) for edge in path.get("edges") or []):
        ctx.doubt(ctx.table.ticked, "%s follows edges of another body, which the copy keeps as measured" % name)
    elif ctx.written_reads:
        ctx.doubt(ctx.written_reads, "%s follows edges of the part, which the copy keeps as measured" % name)


def _mark_sketch_place(ctx, name, path):
    """A path sketch sits on a plane or face and may hold projected curves: sizes that move those move the path in
    Fusion, not in the copy."""
    reference = path.get("reference")
    kind = reference.get("kind") if isinstance(reference, dict) else None
    if kind == "constructionPlane":
        names = construction_sizes(ctx.table, "constructionPlane", reference.get("token") or "")
        if names:
            ctx.doubt(names, "%s copies its path from a sketch on a construction plane, as measured" % name)
    elif kind in ("face", "other") or path.get("projected") or ("reference" in path and reference is None):
        if ctx.written_reads:
            ctx.doubt(ctx.written_reads, "%s copies its path from a sketch on or projected from the part, as measured"
                      % name)


def _keep_path_on_plane(ctx, item, profile):
    """The path is written as numbers and starts on the plane the outline had when it was captured: a size that moves
    that plane is marked, whichever form the sweep is written in."""
    outcome = loops.profile_loops(profile)
    if isinstance(outcome, Refusal):
        return
    drawn = sketch_motion.outline(ctx, item, profile, outcome[0], outcome[1], [(0, profile)])
    if drawn is None:
        return
    shift = drawn.plane_shift(ctx)
    if shift.sized:
        ctx.doubt(shift.reads, "%s starts its path on the plane of its outline, which the copy cannot move with it"
                  % item.get("name", "a sweep"))


def _keep_outline_in_bends(ctx, item, profile, found, outer, growth):
    """A larger outline can reach past the tightest bend of the path, which the app refuses: mark the sizes behind
    the outline that can do so. `growth` is how far a taper can lean the walls out by the path's end."""
    if ctx.table is None or found.tightest == math.inf:
        return
    frame = profile["frame"]
    offset = vec.sub(found.start, frame["origin"])
    names = sweep_reach.outgrown_reads(ctx.table, outer, [vec.dot(offset, frame["x"]), vec.dot(offset, frame["y"])],
                                       found.tightest - growth * found.length)
    if names:
        ctx.doubt(names, "it can make the outline of %s reach past the tightest bend of its path"
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


def _doubt_angle(ctx, item, what, quantity, outline_reads):
    """Until the way Fusion measures a twist or taper is confirmed: mark the sizes behind the angle and the outline,
    and ask for a look at the shape."""
    name = item.get("name", "a sweep")
    reads = tuple(dict.fromkeys(tuple(quantity.reads) + tuple(outline_reads)))
    if reads:
        ctx.doubt(reads, "Fusion may measure the %s of %s another way than the copy reads it" % (what, name))
    ctx.note("The %s of %s is copied as Paramability reads it; check the shape." % (what, name))


def _as_sweep(item, combine, profile, found, ctx, angles=(), fixed=False, growth=0.0):
    """A `sweep` step: the outline on its own placement and the path, with the twist, taper and direction setting.
    `angles` are `(what, recipe key, Quantity, confirmed)`."""
    outcome = loops.profile_loops(profile)
    if isinstance(outcome, Refusal):
        return outcome
    outer, inners = outcome
    drawn = sketch_motion.outline(ctx, item, profile, outer, inners, [(0, profile)])
    on = placement.from_frame(profile["frame"])
    if drawn is not None:
        on["origin"] = drawn.origin(ctx, Quantity(0.0))
        outer, inners = drawn.written(ctx)
        _keep_outline_in_bends(ctx, item, profile, found, outer, growth)
    sketch = {"on": on, "outer": outer}
    if inners:
        sketch["inner"] = inners
    step = {"kind": "sweep", "sketch": sketch, "path": copy.deepcopy(found.recipe), "combine": combine}
    for what, key, quantity, confirmed in angles:
        step[key] = quantity.json()
        if not confirmed:
            _doubt_angle(ctx, item, what, quantity, sweep_reach.written_reads(outer, *inners))
    if fixed:
        step["orientation"] = "fixed"
    out = StepResult()
    out.add(step)
    return out


def _taper_growth(profile, taper_deg):
    """How far the walls can lean out per mm of path for a taper of `taper_deg` either way, corners of the outline
    included."""
    if abs(taper_deg) <= ZERO_TOL:
        return 0.0
    outer = next((loop for loop in profile.get("loops") or [] if loop.get("outer")), None)
    ring = _loop_polygon(outer.get("curves") or []) if outer else None
    factor = sweep_taper.corner_factor(ring) if ring else 1.0
    return math.tan(math.radians(abs(taper_deg))) * factor


def _taper_path_refusal(found):
    """A Refusal when the path cannot carry a taper: free curves, or more parts than the recipe builds through."""
    parts = found.recipe["segments"] if found.recipe["kind"] == "flat" else found.curves
    if found.recipe["kind"] == "flat" and any(segment["kind"] == "spline" for segment in parts):
        return Refusal(TAPER_CURVES)
    return Refusal(TAPER_STATIONS) if len(parts) + 1 > MAX_TAPER_STATIONS else None


def _taper_lean(item, profile, data, combine, found, slope):
    """The taper's meaning read from the volume of a new body along a straight path: `OFFSET`, `FLIPPED` (it leans the
    other way), `SCALED`, or None when it cannot be told."""
    areas, made = data.get("areas"), _made_volume(item, data)
    if found.kind != "line" or combine != "new" or made is None or not isinstance(areas, list) or len(areas) != 1:
        return None
    shapes = []
    for loop in profile.get("loops") or []:
        points = _loop_polygon(loop.get("curves") or [])
        if not points or len(points) < 3:
            return None
        shapes.append((points, bool(loop.get("outer"))))
    return sweep_taper.meaning(shapes, found.length, made, slope)


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
    if path.get("truncated"):
        return Refusal(PATH_TOO_LONG)
    twist, taper = data["twist_deg"], data["taper_deg"]
    twisted, tapered, fixed = abs(twist) > ZERO_TOL, abs(taper) > ZERO_TOL, data["orientation"] == "parallel"
    options = paths.PathOptions(as_step=twisted or tapered or fixed, twisted=twisted, tapered=tapered,
                                growth=_taper_growth(profile, taper), fixed=fixed)
    found = paths.plan(path, profile["frame"], _profile_points(profile), options)
    if isinstance(found, Refusal):
        return found
    if found.closed and twisted and abs(twist / 360.0 - round(twist / 360.0)) > WHOLE_TURN_TOL:
        return Refusal(TWIST_CLOSED)
    taper_sign = TAPER_SIGN
    if tapered:
        refusal = _taper_path_refusal(found)
        if refusal is not None:
            return refusal
        lean = _taper_lean(item, profile, data, combine, found, math.tan(math.radians(TAPER_SIGN * taper)))
        if lean == sweep_taper.SCALED:
            return Refusal(SCALED_OUTLINE)
        if lean == sweep_taper.FLIPPED:
            taper_sign = -TAPER_SIGN
    refusal = _volume_refusal(item, data, combine, profile, found)
    if refusal is not None:
        return refusal
    _pin_settings(ctx, item, data, found.closed)
    _mark_path(ctx, item, path)
    _keep_path_on_plane(ctx, item, profile)
    if found.kind != "line":
        borrowed.mark_unchecked(ctx, item, profile)
    angles = [(what, key, quantity, confirmed)
              for what, key, quantity, confirmed in (
                  ("twist", "twistDeg", _angle(ctx, item, "twist_deg", twist, TWIST_SIGN, not found.closed),
                   TWIST_SIGN_CONFIRMED),
                  ("taper", "taperDeg", _angle(ctx, item, "taper_deg", taper, taper_sign), TAPER_MEANING_CONFIRMED))
              if quantity is not None]
    if twisted or tapered or (fixed and found.kind != "line"):
        outcome = _as_sweep(item, combine, profile, found, ctx, angles, fixed, options.growth)
    elif found.kind == "line":
        outcome = _as_extrude(item, data, profile, found, ctx)
    elif found.kind in ("arc", "circle"):
        outcome = _as_revolve(item, data, combine, profile, found, ctx)
    else:
        outcome = _as_sweep(item, combine, profile, found, ctx)
    if path.get("kind") == "edges" and isinstance(outcome, StepResult):
        for entry in outcome.entries:
            entry.repeatable = False
    return outcome
