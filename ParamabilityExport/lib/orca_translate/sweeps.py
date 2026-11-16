"""Sweep steps as Orca features: an outline carried along a path.

Orca's Sweep (`CadDocument::apply_feature`, `SketchEngine::make_sweep`) makes a face of the outline sketch and runs it
along the wire of the path sketch with OCCT's `BRepOffsetAPI_MakePipe`: the outline stays where it is drawn and is
carried along the path from the wire's first point, turning with the path. It has no twist, no taper, no guide rail
and no way to keep the outline in one direction, and its outline must be one closed loop (no holes). Orca builds the
wire of an open path from the free end of the first entity written, and of a closed path from the start of the first
entity, so the copy writes the path entities in order from the outline.

The path is planned as for a recipe (`design_model.paths.planner.plan`, with the recipe's caps and free curve fit:
the chain ordered from the outline's plane, a closed chain cut open there, and the rules the shape needs: no
crossing, the outline clear of the tightest bend and of the other parts of the path). Then:
- a straight path is an Orca Extrude of the outline (`steps.extrude`, holes included);
- one arc or a full circle is an Orca Revolve about its axis (`revolve.revolve`);
- a chain of lines and arcs in one plane, open or closed, that meet smoothly is an Orca Sweep along a sketch of the
  path. Its shape for later cuts (`solid`) is the outline carried along each part: a prism along a line, the outline
  turned about the centre of an arc.

Left out: a twist or a taper, an outline kept in one direction along a path that turns, guide rails and surfaces, part
of a path, a path that bends out of one plane, free curves in the path, sharp corners, an outline with holes along a
bent path, an outline that is not square to the path where it starts, and a new body whose measured volume or end
face does not match the outline and path (`design_model.steps.sweep`).

Orca cannot tie a path to a variable, so the path keeps its numbers and the sizes that move it are marked. The outline
of an extrude or a sweep follows its sizes as an extrude outline does.
"""
import math

from ..capture_model import gap_hints
from ..design_model import design, reach
from ..design_model.paths import curves as path_curves, planner
from ..design_model.paths.checks import bend_problem, overlap_problem
from ..design_model.paths.curves import tangents
from ..design_model.paths.model import PathOptions
from ..design_model.problem import is_problem
from ..design_model.steps.sweep import cover_problem, end_check, profile_points, settings_problem, volume_problem
from ..geometry import spline_fit, vec
from ..orca_recipe.enums import BooleanMode, FeatureType
from ..geometry.footprint import polyline
from . import causes, extents, limits, revolve, sketch_sizes, steps
from ..design_model.values import Quantity
from ..design_model import words as shared
from .sketches import entities_of, graph_for, outline_sketch, outlines_of
from .skip import Skip
from .solid import ADD, CUT, INTERSECT, Prism, Solid, Turned
from .tools import OPERATIONS, feature, label

_SOLID_MODES = {"newBody": ADD, "join": ADD, "cut": CUT, "intersect": INTERSECT}
_COMBINE = {"newBody": "new", "join": "add", "cut": "remove", "intersect": "intersect"}
# The outline must leave its plane this square (the sine of the angle between the path and the outline's normal),
# since Orca's extrude runs along the normal and its sweep keeps the angle the outline is drawn at.
_SQUARE = 1e-6
# Two parts of the path that meet at a turn above this (degrees) make a sharp corner.
_SMOOTH_DEG = 0.01
_ZERO = 1e-6
# The path is planned with the caps and the free curve fit of a recipe sweep step, so the parts of a path the copy
# takes are the ones the recipe output takes.
_MAX_SEGMENTS = 64
_MAX_POINTS = 64

_TWIST = "Orca's sweep cannot twist or taper its outline, so this sweep is left out."
_KEEPS_DIRECTION = ("Orca's sweep turns the outline with its path and cannot keep it in one direction, so this sweep "
                    "is left out.")
_NOT_FLAT = "Orca's copy of a sweep takes a path in one plane only, so this sweep is left out."
_FREE_CURVE = "The path of this sweep has a free curve (a spline), which the Orca copy cannot draw, so it is left out."
_SHARP = "The path of this sweep has a sharp corner, which the Orca copy does not build the way Fusion does."
_HOLES = "Orca's sweep cannot carry an outline with holes along a bent path, so this sweep is left out."
_NOT_SQUARE = "The outline of this sweep is not square to its path, which the Orca copy cannot build the same way."
_PATH_FIXED = "%s: Orca cannot tie the path of a sweep to a variable, so the path keeps its drawn numbers"


def _profile_problem(profile):
    if not isinstance(profile, dict):
        return "The outline of this sweep could not be read."
    if profile.get("face"):
        return "The outline of this sweep is a face of the part, which the Orca copy does not copy yet."
    if profile.get("text"):
        return "Sketch text is not copied to Orca yet."
    if profile.get("foreign"):
        return "This sweep uses a sketch of another component, which is not copied yet."
    if profile.get("space") not in (None, "sketch", "model") or not isinstance(profile.get("frame"), dict) \
            or outlines_of(profile) is None:
        return "The outline of this sweep could not be read."
    return None


def _path_problem(path):
    if not isinstance(path, dict):
        return Skip(shared.SWEEP_PATH_UNREAD)
    if path.get("foreign"):
        return Skip("The path of this sweep is in another component, which is not copied yet.",
                    gap_hints.OTHER_COMPONENT)
    if path.get("kind") == "mixed":
        return Skip(shared.SWEEP_PATH_MIXED)
    if path.get("truncated"):
        return Skip(shared.SWEEP_PATH_TOO_LONG)
    return None


def sweep(ctx, step):
    """The Orca features of a sweep, or a Skip."""
    item, data = step.brought, step.brought_data
    operation = data.get("operation")
    if operation == "newComponent":
        return Skip("This sweep makes a new component, which is not copied yet.", gap_hints.NEW_COMPONENT)
    if operation not in _SOLID_MODES:
        return Skip(shared.SWEEP_KIND)
    if data.get("solid") is not True:
        if data.get("solid") is False:
            return Skip(shared.SWEEP_SURFACE, gap_hints.SURFACE)
        return Skip(shared.SWEEP_UNREAD)
    if not ctx.has_body and operation in ("cut", "intersect"):
        return Skip("The part this %s works on is not in the copy." % ("cut" if operation == "cut" else "intersect"),
                    gap_hints.AFTER_GAP)
    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        return Skip("This sweep has no outline that could be read.")
    for profile in profiles:
        problem = _profile_problem(profile)
        if problem:
            return Skip(problem)
    if len(profiles) > 1 and operation == "intersect":
        return Skip(shared.SWEEP_SEVERAL_OUTLINES)
    problem = settings_problem(data) or cover_problem(data)
    if problem is not None:
        return Skip.of(problem)
    if abs(data["twist_deg"]) > _ZERO or abs(data["taper_deg"]) > _ZERO:
        return Skip(_TWIST, causes.SWEEP_SHAPE)
    path = data.get("path")
    problem = _path_problem(path)
    if problem is not None:
        return problem
    frame = profiles[0]["frame"]
    if any(abs(abs(vec.dot(vec.unit(p["frame"]["z"]), vec.unit(frame["z"]))) - 1.0) > _ZERO
           or abs(vec.dot(vec.sub(p["frame"]["origin"], frame["origin"]), vec.unit(frame["z"]))) > 1e-4
           for p in profiles):
        return Skip("The outlines of this sweep lie in different planes, which is not copied to Orca yet.")
    points = [q for p in profiles for q in profile_points(p)]
    found = planner.plan(path, frame, points,
                         PathOptions(max_segments=_MAX_SEGMENTS, max_points=_MAX_POINTS, splines=spline_fit))
    if is_problem(found):
        return Skip.of(found)
    if found.kind == "corners":
        return Skip(_NOT_FLAT, causes.SWEEP_PATH)
    if any(c.get("kind") not in ("line", "arc", "circle") for c in found.curves):
        return Skip(_FREE_CURVE, causes.SWEEP_PATH)
    if data["orientation"] == "parallel" and found.kind != "line":
        return Skip(_KEEPS_DIRECTION, causes.SWEEP_SHAPE)
    if vec.length(vec.cross(found.direction, vec.unit(frame["z"]))) > _SQUARE:
        return Skip(_NOT_SQUARE)
    if found.kind == "flat" and _sharp(found):
        return Skip(_SHARP, gap_hints.SHARP_CORNER)
    combine = _COMBINE[operation]
    for profile in profiles:
        if len(profiles) == 1:
            problem = volume_problem(item, data, combine, profile, found)
            if problem is not None:
                return Skip.of(problem)
        problem, _ = end_check(data, combine, profile, found, profile_points(profile), False, False)
        if problem is not None:
            return Skip.of(problem)
    if found.kind == "line":
        made = _as_extrude(ctx, item, data, profiles, found)
    elif found.kind in ("arc", "circle"):
        made = _as_revolve(ctx, item, data, profiles, found)
    else:
        made = _as_sweep(ctx, item, data, profiles, found)
    if not isinstance(made, Skip):
        _mark_path(ctx, item, path)
    return made


def _sharp(found):
    """True when two parts of a flat path (and the seam of a closed one) meet at a corner."""
    curves = found.curves
    pairs = list(zip(curves, curves[1:])) + ([(curves[-1], curves[0])] if found.closed else [])
    for before, after in pairs:
        a, b = tangents(before)[1], tangents(after)[0]
        turn = math.degrees(math.atan2(vec.length(vec.cross(a, b)), vec.dot(a, b)))
        if turn > _SMOOTH_DEG:
            return True
    return False


# ---- a straight path: an extrude -------------------------------------------------------------------------------

def _as_extrude(ctx, item, data, profiles, found):
    """The outline extruded along the line: the extrude handler with a side as long as the path."""
    sign = 1.0 if vec.dot(found.direction, profiles[0]["frame"]["z"]) > 0 else -1.0
    length = sign * found.length
    extrude = {"operation": data.get("operation"), "profiles": profiles, "start": {"kind": "profilePlane"},
               "extent_type": "one", "side_one": {"kind": "distance", "distance": length, "taper_deg": 0.0},
               "thin": False, "end_offset": length, "target_box_before": data.get("target_box_before"),
               "participants": data.get("participants") or [], "params": {}}
    return steps.extrude(ctx, design.as_read(dict(item, data=extrude)))


# ---- one arc or a full circle: a revolve -----------------------------------------------------------------------

def _as_revolve(ctx, item, data, profiles, found):
    """The outline turned about the arc's axis: the revolve handler, one outline at a time (the first with the
    sweep's operation, the rest joined to it for a new body)."""
    out = []
    mark = ctx.checkpoint()
    operation = data.get("operation")
    for n, profile in enumerate(profiles):
        step = "join" if n and operation == "newBody" else operation
        # The start face's outward normal points against the turn for new material and along it for a cut.
        start = vec.scale(found.direction, 1.0 if step == "cut" else -1.0)
        turned = {"operation": step, "profiles": [profile], "axis": dict(found.axis),
                  "extent": {"kind": "angle", "angle_deg": found.angle_deg}, "start_face_normal": start,
                  "params": {}}
        made = revolve.revolve(ctx, design.as_read(dict(item, data=turned)))
        if isinstance(made, Skip):
            ctx.rollback(mark)
            return made
        out += made
    return out


# ---- a flat chain: an Orca sweep -------------------------------------------------------------------------------

def _path_frame(found):
    """The frame of the path's plane at its start: x along the path, z the plane's normal."""
    normal = vec.unit(found.recipe["on"]["normal"])
    x = vec.unit(found.direction)
    return {"origin": list(found.start), "x": x, "y": vec.cross(normal, x), "z": normal}


def _flat_curve(curve, frame):
    """A path curve in the 2D frame of the path's plane, as a capture curve."""
    def local(p):
        return vec.frame_to_local(frame, p)[:2]

    if curve["kind"] == "line":
        return {"kind": "line", "start": local(curve["start"]), "end": local(curve["end"])}
    if curve["kind"] == "circle":
        return {"kind": "circle", "center": local(curve["center"]), "radius": float(curve["radius"])}
    return {"kind": "arc", "start": local(curve["start"]), "end": local(curve["end"]), "mid": local(curve["mid"]),
            "center": local(curve["center"]), "radius": float(curve["radius"])}


def carried(frame, loops, found):
    """The shape of the outline (`loops` of capture curves in `frame`) swept along the flat path `found`, turning
    with it: a `solid.Solid` that adds a prism along each line and the outline turned about the centre of each arc."""
    normal = vec.unit(found.recipe["on"]["normal"])
    first = vec.unit(found.direction)
    shape = Solid()
    for curve in found.curves:
        start = tangents(curve)[0]
        turn = math.degrees(math.atan2(vec.dot(vec.cross(first, start), normal), vec.dot(first, start)))

        def moved(p, offset=True, turn=turn, at=curve["start"]):
            if not offset:
                return vec.rotate(p, normal, turn)
            return vec.add(vec.rotate(vec.sub(p, found.start), normal, turn), at)

        here = {"origin": moved(frame["origin"]), "x": moved(frame["x"], False), "y": moved(frame["y"], False),
                "z": moved(frame["z"], False)}
        if curve["kind"] == "line":
            length = vec.length(vec.sub(curve["end"], curve["start"]))
            along = 1.0 if vec.dot(here["z"], start) > 0 else -1.0
            shape.add(ADD, Prism(here, loops, 0.0, along * length))
        else:
            centre = curve["center"]
            axis = vec.unit(vec.cross(vec.sub(curve["start"], centre), start))
            shape.add(ADD, Turned(here, loops, centre, axis, math.degrees(_arc_angle(curve, centre, axis))))
    return shape


def _arc_angle(curve, centre, axis):
    """The angle (radians, up to a full turn) an arc turns about `axis` from its start to its end; `axis` is the one
    the arc turns positively about at its start."""
    a, b = vec.sub(curve["start"], centre), vec.sub(curve["end"], centre)
    whole = math.atan2(vec.dot(vec.cross(a, b), axis), vec.dot(a, b)) % (2 * math.pi)
    return whole if whole > 1e-12 else 2 * math.pi


def _as_sweep(ctx, item, data, profiles, found):
    operation = data.get("operation")
    frame = _path_frame(found)
    entities = entities_of([[_flat_curve(c, frame) for c in found.curves]])
    if entities is None:
        return Skip(_FREE_CURVE, causes.SWEEP_PATH)
    written = []
    for n, profile in enumerate(profiles):
        outline = outlines_of(profile)
        if outline.holes:
            return Skip(_HOLES, causes.OUTLINE_HOLES)
        made = outline_sketch(outline, profile["frame"], ctx.place, sketch_sizes.sketch_formulas(ctx, profile),
                              "%s outline%s" % (label(item), " %d" % (n + 1) if len(profiles) > 1 else ""))
        if made is None:
            return Skip("The outline of this sweep has a curve the Orca copy cannot draw yet (it draws lines, arcs, "
                        "circles and splines Fusion gives exactly).")
        written.append((profile, outline, made, carried(profile["frame"], [outline.outer], found)))
    mode = _SOLID_MODES[operation]
    if mode != ADD:
        kept = [w for w in written if ctx.solid.meets(w[3])]
        if not kept:
            return Skip(*steps.misses_reason(ctx, "cut" if mode == CUT else "intersect"))
        if len(kept) < len(written):
            ctx.notes.append("%s: %d of its outlines do not meet the part as the Orca copy builds it and are left "
                             "out." % (label(item), len(written) - len(kept)))
        written = kept
    sketch_sizes.sketch_doubts(ctx, item, [(p, o) for p, o, _, _ in written], [(m, o, p) for p, o, m, _ in written])
    for profile, _, _, _ in written:
        moving = reach.sketch_plane_sizes(ctx.table, ctx.capture.get("items") or [], item, profile)
        ctx.doubt(moving, "%s: an outline sits on a plane or face that moves with it, and Orca cannot move a sketch "
                  "plane with a variable" % label(item))

    name = label(item)
    path_sketch = feature(FeatureType.SKETCH, "%s path" % name, entities=entities,
                          plane=ctx.place.plane(frame["origin"], frame["x"], frame["y"], frame["z"]))
    out = []
    path_at = None
    for n, (profile, outline, made, shape) in enumerate(written):
        at = ctx.add(made.feature)
        out.append(made.feature)
        for field, (formula, reads) in made.bound.items():
            ctx.bind(made.feature, field, Quantity(getattr(made.feature, field), formula, reads),
                     "%s %s" % (made.feature.name, field))
        made.feature.thread_major_nominal = made.feature.pattern_inclusive = True
        if path_at is None:
            path_at = ctx.add(path_sketch)
            out.append(path_sketch)
        step = feature(FeatureType.SWEEP, name if n == 0 else "%s (%d)" % (name, n + 1), sketch_ref=at,
                       sweep_path_ref=path_at)
        step.mode = BooleanMode.NEW if not ctx.has_body else OPERATIONS.get(operation, BooleanMode.ADD)
        ctx.add(step)
        ctx.has_body = True
        ctx.solid.add(mode, shape)
        out.append(step)
        _limit(ctx, made.feature, outline.outer, path_sketch.plane, found)
    return out


def _limit(ctx, sketch, outer, plane, found):
    """Tell how far the variables of a swept outline (a plain rectangle or circle) may go: the outline must stay
    clear of the centre of the tightest bend of the path, and of the other parts of the path, or Orca's sweep runs
    into itself. `plane` is the path sketch's plane; distances are taken in Orca's frame, which keeps them."""
    if not any(field in sketch.expr for field in ("width", "height", "radius")):
        return
    points = [p for c in found.curves for p in path_curves.polyline(c)]
    fields = [(sketch, field, "%s %s" % (sketch.name, field)) for field in ("width", "height", "radius")]

    def ok(numbers):
        loop = extents.drawn_loop(sketch, outer, *numbers)
        reach = max(_across(sketch.plane, plane, p) for c in loop for p in polyline(c))
        return bend_problem(reach, found.tightest) is None and overlap_problem(points, reach, found.closed) is None

    limits.guard(ctx, fields, ok, "%s: the Orca copy cannot tell how far this may change before the sweep runs into "
                 "itself" % sketch.name)


def _across(outline_plane, path_plane, uv):
    """How far the outline point `uv` lies from the start of the path, across the path's plane."""
    point = [outline_plane.origin[i] + uv[0] * outline_plane.x_axis[i] + uv[1] * outline_plane.y_axis[i]
             for i in range(3)]
    d = vec.sub(point, list(path_plane.origin))
    normal = vec.unit(list(path_plane.normal))
    return vec.length(vec.sub(d, vec.scale(normal, vec.dot(d, normal))))


# ---- sizes that move the path ----------------------------------------------------------------------------------

def _mark_path(ctx, item, path):
    """Mark the sizes that move the path: the dimensions of its sketch and what its plane sits on, or for body edges
    every size read before the step."""
    if ctx.table is None:
        return
    items = ctx.capture.get("items") or []
    if path.get("kind") == "edges":
        names = reach.any_face_sizes(ctx.table, items, item)
    else:
        names = (reach.profile_sizes(ctx.table, path, graph_for(ctx.capture, path))
                 + reach.placement_sizes(ctx.table, items, path, item.get("index")))
    ctx.doubt(list(dict.fromkeys(names)), _PATH_FIXED % label(item))


HANDLERS = {"SweepFeature": sweep}
