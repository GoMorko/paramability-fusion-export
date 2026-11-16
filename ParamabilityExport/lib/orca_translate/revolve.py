"""Revolve steps as Orca Revolve features.

Each outline becomes a sketch of its lines and arcs, plus a construction line along the turning axis that the
Revolve names (`revolve_axis_entity`), so the axis may sit anywhere in the sketch plane. Orca turns by the right hand
rule about that line; Fusion does not say which way it turned, so the measured start face decides (its outward normal
points against the turn for new material, along it for a cut). `revolve_angle` follows the angle's parameter. A
symmetric turn starts half the angle back: the sketch plane is turned there, so its angle keeps its number.

Orca needs the axis in the sketch plane, an outline on one side of it and no holes in the outline; anything else is
left out with the reason. A cut that removes nothing stops Orca's rebuild, so a cut that misses the copied part is
left out (`solid.Turned` is the shape the check uses).
"""
from ..capture_model import gap_hints
from ..geometry import vec
from ..geometry.footprint import polyline
from ..orca_recipe.enums import BooleanMode, EntityType, FeatureType
from ..orca_recipe.sketch import SketchEntity
from . import causes, extents
from .context import Value
from .sketches import entities_of, outlines_of
from .solid import ADD, CUT, INTERSECT, Turned
from .sketch_sizes import profile_sizes, projection_doubts
from .steps import Skip
from .tools import OPERATIONS, data_of, feature, label

FULL_TURN_DEG = 360.0
# How far (mm) the axis may sit off the sketch plane, and how far it may lean out of it, and still count as in it.
AXIS_PLANE_TOL = 1e-4
AXIS_TILT_TOL = 1e-6
# How far (mm) an outline may reach across the axis.
SIDE_TOL = 1e-6
_SOLID_MODES = {"newBody": ADD, "join": ADD, "cut": CUT, "intersect": INTERSECT}


def _profile_problem(profile):
    if profile.get("face"):
        return "This revolve turns a face of the body, which the Orca copy does not copy yet."
    if profile.get("text"):
        return "Sketch text is not copied to Orca yet."
    if profile.get("foreign"):
        return "This revolve uses a sketch of another component, which is not copied yet."
    if profile.get("space") not in (None, "sketch", "model") or not isinstance(profile.get("frame"), dict):
        return "The outline of this revolve could not be read."
    return None


def _angle(ctx, item, extent):
    """`(Value of the angle, symmetric)` or a Skip."""
    kind = (extent or {}).get("kind")
    if kind == "twoSidesAngle":
        return Skip("Revolves turned to both sides by two angles are not copied to Orca yet.",
                    causes.REVOLVE_TWO_ANGLES)
    if kind != "angle" or not isinstance(extent.get("angle_deg"), (int, float)):
        return Skip("This way of setting the revolve angle is not copied yet.")
    angle = abs(float(extent["angle_deg"]))
    if not 0 < angle <= FULL_TURN_DEG + 1e-9:
        return Skip("This revolve turns by an angle that is not copied.")
    value = ctx.quantity(item, "extent.angle_deg", angle, "angle").magnitude()
    if angle >= FULL_TURN_DEG - 1e-9:
        if value.formula is not None:
            ctx.doubt(value.reads, "%s turns a full circle only while its angle is 360" % label(item))
        return Value(FULL_TURN_DEG), False
    symmetric = bool(extent.get("symmetric"))
    if symmetric and value.formula is not None:
        ctx.doubt(value.reads, "%s turns to both sides of its sketch, so its angle keeps its number in Orca"
                  % label(item))
        value = Value(angle)
    return value, symmetric


def _points(curves):
    return [p for c in curves for p in polyline(c)]


def _sense(data, operation, frame, outer, point, direction):
    """+1 when Fusion turned by the right hand rule about `direction`, -1 when the other way, or a Skip."""
    normal = data.get("start_face_normal")
    if not isinstance(normal, (list, tuple)) or vec.length(normal) < 1e-9:
        return Skip("The turning direction of this revolve could not be read.")
    travel = vec.scale(vec.unit(normal), 1.0 if operation == "cut" else -1.0)
    flat = _points(outer)
    centre = [sum(p[0] for p in flat) / len(flat), sum(p[1] for p in flat) / len(flat)]
    v = vec.sub(vec.frame_apply(frame, [centre[0], centre[1], 0.0]), point)
    radial = vec.sub(v, vec.scale(direction, vec.dot(v, direction)))
    if vec.length(radial) < 1e-9:
        return Skip("The sketch of this revolve lies on its axis.")
    side = vec.dot(travel, vec.cross(direction, vec.unit(radial)))
    if abs(side) < 1e-6:
        return Skip("The turning direction of this revolve could not be read.")
    return 1.0 if side > 0 else -1.0


def _turned_frame(frame, point, direction, degrees):
    if not degrees:
        return frame
    return {"origin": vec.rotate(frame["origin"], direction, degrees, point),
            "x": vec.rotate(frame["x"], direction, degrees), "y": vec.rotate(frame["y"], direction, degrees),
            "z": vec.rotate(frame["z"], direction, degrees)}


def revolve(ctx, item):
    data = data_of(item)
    operation = data.get("operation")
    if operation == "newComponent":
        return Skip("This revolve makes a new component, which is not copied yet.", gap_hints.NEW_COMPONENT)
    if operation not in _SOLID_MODES:
        return Skip("This kind of revolve is not copied yet.")
    if not ctx.has_body and operation in ("cut", "intersect"):
        return Skip("The part this %s works on is not in the copy." % ("cut" if operation == "cut" else "intersect"),
                    gap_hints.AFTER_GAP)
    profiles = data.get("profiles") or []
    if not profiles:
        return Skip("This revolve has no outline that could be read.")
    if len(profiles) > 1:
        return Skip("A revolve of several outlines is not copied to Orca yet.")
    profile = profiles[0]
    problem = _profile_problem(profile)
    if problem:
        return Skip(problem)
    axis = data.get("axis") or {}
    if axis.get("foreign"):
        return Skip("The revolve axis belongs to another component and could not be brought into the part's place, "
                    "which is not copied to Orca.", gap_hints.OTHER_COMPONENT)
    if not isinstance(axis.get("point"), (list, tuple)) or not isinstance(axis.get("dir"), (list, tuple)):
        return Skip("The revolve axis could not be read as a line.")
    found = _angle(ctx, item, data.get("extent"))
    if isinstance(found, Skip):
        return found
    angle, symmetric = found
    outline = outlines_of(profile)
    if outline is None:
        return Skip("The outline of this revolve could not be read.")
    if outline.holes:
        return Skip("A revolve of an outline with holes is not copied to Orca yet.", causes.OUTLINE_HOLES)
    frame = profile["frame"]
    normal = vec.unit(frame["z"])
    point, direction = [float(c) for c in axis["point"]], vec.unit(axis["dir"])
    if abs(vec.dot(vec.sub(point, frame["origin"]), normal)) > AXIS_PLANE_TOL \
            or abs(vec.dot(direction, normal)) > AXIS_TILT_TOL:
        return Skip("The revolve axis does not lie in the plane of the sketch, which Orca needs.", causes.REVOLVE_AXIS)
    across = [vec.dot(vec.cross(direction, vec.sub(vec.frame_apply(frame, [p[0], p[1], 0.0]), point)), normal)
              for p in _points(outline.outer)]
    if min(across) < -SIDE_TOL and max(across) > SIDE_TOL:
        return Skip("The outline of this revolve reaches across its axis, which Orca does not turn.",
                    causes.REVOLVE_ACROSS_AXIS)
    entities = entities_of([outline.outer])
    if entities is None:
        return Skip("The outline of this revolve has a curve the Orca copy cannot draw yet (it draws lines, arcs, "
                        "circles and splines Fusion gives exactly).")
    sense = 1.0
    if angle.number < FULL_TURN_DEG:
        sense = _sense(data, operation, frame, outline.outer, point, direction)
        if isinstance(sense, Skip):
            return sense
    turn_axis = vec.scale(direction, sense)
    start = -angle.number / 2.0 if symmetric else 0.0
    tool = Turned(frame, [outline.outer], point, turn_axis, angle.number, start)
    if operation in ("cut", "intersect") and not ctx.solid.meets(tool):
        gap = bool(ctx.left_out)
        what = "cut" if operation == "cut" else "intersect"
        return Skip("This %s does not meet the part as the Orca copy builds it%s, and Orca stops the whole rebuild on "
                    "a %s that removes nothing, so it is left out." % (
                        what, " (a step before it is left out)" if gap else "", what),
                    gap_hints.AFTER_GAP if gap else causes.MISSES_PART)

    name = label(item)
    on = _turned_frame(frame, point, turn_axis, start)
    local = vec.frame_to_local(frame, point)
    along = [vec.dot(turn_axis, frame["x"]), vec.dot(turn_axis, frame["y"])]
    line = SketchEntity(type=EntityType.LINE, p0=(local[0], local[1]),
                        p1=(local[0] + 10.0 * along[0], local[1] + 10.0 * along[1]), construction=True)
    sketch = feature(FeatureType.SKETCH, "%s sketch" % name, plane=ctx.place.plane(on["origin"], on["x"], on["y"],
                                                                                   on["z"]),
                     entities=entities + [line])
    at = ctx.add(sketch)
    made = feature(FeatureType.REVOLVE, name, sketch_ref=at, revolve_axis_entity=len(entities),
                   mode=OPERATIONS.get(operation, BooleanMode.ADD) if ctx.has_body else BooleanMode.NEW)
    ctx.bind(made, "revolve_angle", angle, "%s angle" % name)
    ctx.add(made)
    ctx.has_body = True
    ctx.solid.add(_SOLID_MODES[operation], tool)
    projection_doubts(ctx, item, profile, outlines_of(profile))
    loose = profile_sizes(ctx, profile)
    if loose:
        ctx.doubt(loose, "%s: the outline from %s keeps its drawn numbers: Orca can tie only the size of a plain "
                  "rectangle or circle to a variable" % (name, profile.get("sketch") or "the sketch"))
    ctx.doubt(extents.sketch_plane_sizes(ctx, item, profile), "%s: its sketch sits on a plane or face that moves with "
              "it, and Orca cannot move a sketch plane with a variable" % name)
    return [sketch, made]


HANDLERS = {"RevolveFeature": revolve}
