"""Sketch profiles as plain dicts: frame, loops and curves in the sketch's own 2D frame (mm)."""
import math

from . import read_geometry as geo
from ..translator import place
from .placement import read_sketch_placement, target_move

# Which space ProfileCurve.geometry is in. "auto" decides per profile: a point off z = 0 proves model space. When
# every point is at z = 0 and the sketch frame is not the identity, the curve is compared with its sketch entity
# (SketchCurve.geometry is in sketch space); if that cannot decide, the profile is marked "ambiguous" and the
# translator refuses it. Set "sketch" or "model" once hand test 2 (docs/hand-tests.md) shows which one Fusion uses.
GEOMETRY_SPACE = "auto"

_FLAT_CM = 1e-5  # 1e-4 mm
_IDENTITY = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
_SAMPLES = 200


def _probe_points(geometry):
    """Points that tell which space a curve is in."""
    out = []
    for name in ("startPoint", "endPoint", "center"):
        p = geo.safe(lambda: getattr(geometry, name), None)
        if p is not None:
            out.append(p)
    return out


def _near(a, b):
    return max(abs(a.x - b.x), abs(a.y - b.y), abs(a.z - b.z)) <= _FLAT_CM


def _frame_is_identity(frame):
    return all(
        max(abs(a - b) for a, b in zip(frame[key], want)) <= 1e-6 for key, want in _IDENTITY.items())


def _on_ground_plane(frame):
    """True when the sketch plane is the plane z = 0, where model and sketch points both have z = 0."""
    z = frame["z"]
    return abs(abs(z[2]) - 1.0) <= 1e-6 and abs(frame["origin"][2]) <= 1e-4


def _spread(points):
    """True when the points (mm) do not all lie on one line."""
    if len(points) < 3:
        return False
    a = points[0]
    b = max(points, key=lambda p: sum((p[i] - a[i]) ** 2 for i in range(3)))
    ab = [b[i] - a[i] for i in range(3)]
    length = math.sqrt(sum(c * c for c in ab))
    if length <= 1e-4:
        return False
    for p in points:
        ap = [p[i] - a[i] for i in range(3)]
        cross = [ap[1] * ab[2] - ap[2] * ab[1], ap[2] * ab[0] - ap[0] * ab[2], ap[0] * ab[1] - ap[1] * ab[0]]
        if math.sqrt(sum(c * c for c in cross)) / length > 1e-4:
            return True
    return False


def _decide_by_entity(sketch, curves):
    """"sketch", "model" or "ambiguous" from comparing profile curves with their sketch entities."""
    moved = False
    for curve in curves:
        entity = geo.safe(lambda: curve.sketchEntity, None)
        if entity is None:
            continue
        mine = _probe_points(curve.geometry)
        theirs = _probe_points(entity.geometry)
        for a, b in zip(mine, theirs):
            if not _near(a, b):
                return "model"
            if not _near(a, sketch.modelToSketchSpace(a)):
                moved = True
    return "sketch" if moved else "ambiguous"


class _Space:
    """Maps curve geometry of one profile into sketch 2D. `mode` is "sketch", "model" or "ambiguous"."""

    def __init__(self, sketch, curves, frame):
        mode = GEOMETRY_SPACE
        if mode == "auto":
            probes = [p for c in curves for p in _probe_points(c.geometry)]
            if any(abs(p.z) > _FLAT_CM for p in probes):
                mode = "model"
            elif _frame_is_identity(frame):
                mode = "sketch"
            elif not _on_ground_plane(frame) and _spread([geo.point(p) for p in probes]):
                # Model points off a line on a plane other than z = 0 cannot all have z = 0.
                mode = "sketch"
            else:
                mode = geo.safe(lambda: _decide_by_entity(sketch, curves), "ambiguous")
        self.sketch = sketch
        self.mode = mode
        self.model = mode == "model"

    def xy(self, p):
        if self.model:
            p = self.sketch.modelToSketchSpace(p)
        return geo.point2(p)

    def direction(self, vector, at):
        """Unit [x, y] of a direction at a point."""
        class _P:
            pass
        end = _P()
        end.x, end.y, end.z = at.x + vector.x, at.y + vector.y, at.z + vector.z
        a, b = self.xy(at), self.xy(end)
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.0
        return [round(dx / n, 9) + 0.0, round(dy / n, 9) + 0.0]


def _read_curve(geometry, space):
    name = geo.type_name(geometry)
    if name == "Line3D":
        return {"kind": "line", "start": space.xy(geometry.startPoint), "end": space.xy(geometry.endPoint)}
    if name == "Circle3D":
        return {"kind": "circle", "center": space.xy(geometry.center), "radius": geo.length(geometry.radius)}
    if name == "Arc3D":
        mid = geo.point_at(geometry, 0.5)
        if mid is not None:
            return {
                "kind": "arc",
                "start": space.xy(geometry.startPoint),
                "end": space.xy(geometry.endPoint),
                "mid": space.xy(mid),
                "center": space.xy(geometry.center),
                "radius": geo.length(geometry.radius),
            }
    if name == "Ellipse3D":
        return {
            "kind": "ellipse",
            "center": space.xy(geometry.center),
            "major_dir": space.direction(geometry.majorAxis, geometry.center),
            "major_radius": geo.length(geometry.majorRadius),
            "minor_radius": geo.length(geometry.minorRadius),
        }
    samples = []
    for i in range(_SAMPLES):
        p = geo.point_at(geometry, i / (_SAMPLES - 1))
        if p is not None:
            samples.append(space.xy(p))
    return {
        "kind": "other",
        "type": name,
        "start": samples[0] if samples else None,
        "end": samples[-1] if samples else None,
        "samples": samples,
    }


MAX_DEPENDENCY_NAMES = 256


def _dependency_names(parameter):
    """Names of every parameter `parameter` reads, directly or through others."""
    found, stack = [], [parameter]
    while stack and len(found) < MAX_DEPENDENCY_NAMES:
        current = stack.pop()
        for other in geo.collection_items(geo.safe(lambda: current.dependencyParameters, None)):
            name = geo.safe(lambda: other.name, None)
            if name and name not in found:
                found.append(name)
                stack.append(other)
    return found


def _sketch_params(sketch):
    """{ name, expression, reads } of each dimension of a sketch: what moves its outline."""
    out = []
    for dimension in geo.collection_items(geo.safe(lambda: sketch.sketchDimensions, None)):
        parameter = geo.safe(lambda: dimension.parameter, None)
        name = geo.safe(lambda: parameter.name, None)
        if parameter is None or not name:
            continue
        out.append({"name": name, "expression": geo.safe(lambda: parameter.expression, "") or "",
                    "reads": _dependency_names(parameter)})
    return out


def _moved_frame(frame, move):
    def apply(p, offset):
        return [sum(move.rows[i][k] * p[k] for k in range(3)) + (move.offset[i] if offset else 0.0) for i in range(3)]
    out = {"origin": [round(c, 6) + 0.0 for c in apply(frame["origin"], True)]}
    for key in ("x", "y", "z"):
        out[key] = [round(c, 9) + 0.0 for c in apply(frame[key], False)]
    return out


def into_target(frame, placement_frame, ctx):
    """A sketch frame of another component (`frame`, in that component) in the target's coordinates, given the
    component's place in the assembly; None when the target's place cannot be read."""
    target = target_move(ctx)
    if target is None:
        return None
    return _moved_frame(frame, place.move_from_frame(placement_frame).then(target.inverse()))


def _borrowed(proxy, sketch, frame, ctx):
    """Another component's sketch: that component, the sketch's place in the assembly, the dimensions that move it,
    and `frame` brought into the target's coordinates (`native_frame` keeps the sketch's own). Without a readable
    place on both sides the frame stays the sketch's own and `placement` holds the reason."""
    component = geo.safe(lambda: sketch.parentComponent, None)
    placement = read_sketch_placement(proxy, sketch)
    out = {
        "component": {"token": geo.safe(lambda: component.entityToken, "") or "",
                      "name": geo.safe(lambda: component.name, "") or ""},
        "placement": placement,
        "sketch_params": _sketch_params(sketch),
    }
    moved = into_target(frame, placement["frame"], ctx) if "frame" in placement else None
    if moved is not None:
        out.update(frame=moved, native_frame=frame)
    elif "frame" in placement:
        placement.pop("frame")
        placement["error"] = "The place of the part could not be read."
    return out


_REFERENCE_KINDS = {"ConstructionPlane": "constructionPlane", "BRepFace": "face", "Plane": "plane"}


def _reference(sketch, ctx):
    """{ kind, token } of what the sketch sits on (`Sketch.referencePlane`), or None when it cannot be read."""
    entity = geo.safe(lambda: sketch.referencePlane, None)
    if entity is None:
        return None
    entity = geo.native_input(entity, ctx)
    return {"kind": _REFERENCE_KINDS.get(geo.type_name(entity), "other"),
            "token": geo.safe(lambda: entity.entityToken, "") or ""}


def _curve_record(profile_curve, space):
    """The curve dict, with `entity`: the token of the sketch curve it came from (same across recomputes)."""
    record = _read_curve(profile_curve.geometry, space)
    token = geo.safe(lambda: profile_curve.sketchEntity.entityToken, "")
    if token:
        record["entity"] = token
    return record


def read_profile(profile, ctx=None):
    """One Profile as { sketch, frame, loops }; "foreign": true when its sketch is not the target component's.

    `sketch_token` and `reference` (what the sketch sits on) are added when Fusion gives them.

    A profile of another component's sketch, seen through an occurrence, is read from its native object (that
    component's coordinates) and adds `component`, `placement` and `sketch_params` (see `_borrowed`).
    """
    profile = geo.native_input(profile, ctx)
    proxy = None
    if geo.foreign(profile, ctx) and geo.safe(lambda: profile.assemblyContext, None) is not None:
        native = geo.safe(lambda: profile.nativeObject, None)
        if native is not None:
            proxy, profile = profile, native
    sketch = profile.parentSketch
    loops = geo.collection_items(profile.profileLoops)
    loop_curves = [geo.collection_items(loop.profileCurves) for loop in loops]
    frame = geo.frame_of(sketch.transform)
    space = _Space(sketch, [c for curves in loop_curves for c in curves], frame)
    record = {
        "sketch": sketch.name,
        "frame": frame,
        "space": space.mode,
        "loops": [
            {"outer": bool(loop.isOuter), "curves": [_curve_record(c, space) for c in curves]}
            for loop, curves in zip(loops, loop_curves)
        ],
    }
    token = geo.safe(lambda: sketch.entityToken, "")
    if token:
        record["sketch_token"] = token
    reference = _reference(sketch, ctx)
    if reference is not None:
        record["reference"] = reference
    if proxy is not None:
        record["foreign"] = True
        record.update(_borrowed(proxy, sketch, frame, ctx))
    elif geo.foreign(profile, ctx) or geo.foreign(sketch, ctx):
        record["foreign"] = True
    return record


def first_profile(raw):
    """The first Profile of a feature's `profile` property (a Profile or a collection), or None."""
    if geo.type_name(raw) == "Profile":
        return raw
    for entity in geo.collection_items(raw):
        found = first_profile(entity)
        if found is not None:
            return found
    return None


def profile_area(profile):
    """Area of a Profile in mm2, or None."""
    return geo.safe(lambda: round(profile.areaProperties().area * 100.0, 6) + 0.0, None)


def read_profiles(raw, ctx=None):
    """Profiles of a feature's `profile` property: a Profile, a planar BRepFace or a collection of them."""
    name = geo.type_name(raw)
    if name == "Profile":
        return [read_profile(raw, ctx)]
    if name == "BRepFace":
        return [geo.mark_foreign({"face": True, "type": "BRepFace"}, raw, ctx)]
    if raw is not None and hasattr(raw, "count") and hasattr(raw, "item"):
        out = []
        for entity in geo.collection_items(raw):
            out.extend(read_profiles(entity, ctx))
        return out
    return [{"kind": "other", "type": name}]
