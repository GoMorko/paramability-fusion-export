"""Sketch profiles as plain dicts: frame, loops and curves in the sketch's own 2D frame (mm)."""
import math

from . import read_geometry as geo
from ..translator import place, text_outlines
from .placement import read_sketch_placement, target_move

# Which space ProfileCurve.geometry is in. "auto" decides per profile: a point off z = 0 proves model space. When
# every point is at z = 0 and the sketch frame is not the identity, the curve is compared with its sketch entity
# (SketchCurve.geometry is in sketch space); if that cannot decide, the profile is marked "ambiguous" and the
# translator refuses it. Set "sketch" or "model" once hand test 2 (docs/hand-tests.md) shows which one Fusion uses.
# The curves of a SketchText have no sketch entity: they are compared with `SketchText.boundingBox` (sketch space).
GEOMETRY_SPACE = "auto"

_FLAT_CM = 1e-5  # 1e-4 mm
_IDENTITY = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
# A free curve is read as a dense polyline: 16 parameter spans, each split until its middle point is within
# _CHORD_TOL_MM of its chord, at most _MAX_SAMPLES points in all. The translator fits the recipe's spline through it.
_START_SPANS = 16
_CHORD_TOL_MM = 0.0005
_MAX_SAMPLES = 800
_MAX_SPLIT_DEPTH = 12
# Text outlines: past these the text is not read (the copy refuses it).
_MAX_TEXT_CURVES = 4000
_MAX_TEXT_PROFILES = 400
_BOX_MARGIN = 0.005


def _probe_points(geometry):
    """Points that tell which space a curve is in. A free curve has no named points: its ends and middle serve."""
    out = []
    for name in ("startPoint", "endPoint", "center"):
        p = geo.safe(lambda: getattr(geometry, name), None)
        if p is not None:
            out.append(p)
    if not out:
        out = [p for p in (geo.point_at(geometry, f) for f in (0.0, 0.5, 1.0)) if p is not None]
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


def _inside_box(xy, box):
    """True when a 2D point (mm) lies in `box` = [min x, min y, max x, max y], with a small margin."""
    margin = _BOX_MARGIN * max(box[2] - box[0], box[3] - box[1]) + 0.01
    return box[0] - margin <= xy[0] <= box[2] + margin and box[1] - margin <= xy[1] <= box[3] + margin


def _decide_by_box(sketch, probes, box):
    """"sketch" or "model" when only one reading puts every probe point inside the box, else "ambiguous"."""
    as_sketch = all(_inside_box(geo.point2(p), box) for p in probes)
    as_model = all(_inside_box(geo.point2(sketch.modelToSketchSpace(p)), box) for p in probes)
    if as_sketch != as_model:
        return "sketch" if as_sketch else "model"
    return "ambiguous"


class _Space:
    """Maps curve geometry of one profile into sketch 2D. `mode` is "sketch", "model" or "ambiguous". `box` is the
    sketch space bounding box of the outline when the curves have no sketch entity to compare with (sketch text)."""

    def __init__(self, sketch, curves, frame, box=None):
        mode = GEOMETRY_SPACE
        if mode == "auto":
            probes = [p for c in curves for p in _probe_points(c.geometry)]
            if any(abs(p.z) > _FLAT_CM for p in probes):
                mode = "model"
            elif _frame_is_identity(frame):
                mode = "sketch"
            elif box is not None:
                mode = geo.safe(lambda: _decide_by_box(sketch, probes, box), "ambiguous")
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
    return _read_free_curve(geometry, name, space)


def _chord_gap(p, a, b):
    """Distance of a 2D point from the segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    size = dx * dx + dy * dy
    t = 0.0 if size <= 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / size))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _dense_samples(geometry, space):
    """([[x, y], ...], truncated): the curve as a polyline within `_CHORD_TOL_MM` of it (`truncated` when the point
    cap stopped the refinement), or None when the curve cannot be evaluated."""
    evaluator = geo.safe(lambda: geometry.evaluator, None)
    extents = geo.safe(lambda: evaluator.getParameterExtents(), None)
    if not extents or not extents[0]:
        return None
    low, high = extents[1], extents[2]

    def at(t):
        ok, p = evaluator.getPointAtParameter(t)
        return space.xy(p) if ok else None

    params = [low + (high - low) * i / _START_SPANS for i in range(_START_SPANS + 1)]
    points = [geo.safe(lambda t=t: at(t), None) for t in params]
    if any(p is None for p in points):
        return None
    out, state = [points[0]], {"truncated": False}

    def split(t0, p0, t1, p1, depth):
        mid_t = (t0 + t1) / 2.0
        mid = geo.safe(lambda: at(mid_t), None)
        if (mid is not None and depth < _MAX_SPLIT_DEPTH and _chord_gap(mid, p0, p1) > _CHORD_TOL_MM):
            if len(out) >= _MAX_SAMPLES:
                state["truncated"] = True
            else:
                split(t0, p0, mid_t, mid, depth + 1)
                split(mid_t, mid, t1, p1, depth + 1)
                return
        out.append(p1)

    for i in range(_START_SPANS):
        split(params[i], points[i], params[i + 1], points[i + 1], 0)
    return out, state["truncated"]


def _end_direction(geometry, space, parameter_at_end):
    """Unit [x, y] of the curve direction at its start (False) or end (True), or None."""
    evaluator = geo.safe(lambda: geometry.evaluator, None)
    extents = geo.safe(lambda: evaluator.getParameterExtents(), None)
    if not extents or not extents[0]:
        return None
    t = extents[2] if parameter_at_end else extents[1]
    found = geo.safe(lambda: evaluator.getTangent(t), None)
    point = geo.point_at(geometry, 1.0 if parameter_at_end else 0.0)
    if not found or not found[0] or point is None:
        return None
    return geo.safe(lambda: space.direction(found[1], point), None)


def _read_free_curve(geometry, name, space):
    """A curve that is not a line, circle, arc or ellipse (a spline, an elliptical arc): its dense samples, ends,
    middle point and end directions. A curve that cannot be evaluated has no samples and is refused later."""
    dense = _dense_samples(geometry, space)
    samples, truncated = dense if dense else ([], False)
    record = {
        "kind": "other",
        "type": name,
        "start": samples[0] if samples else None,
        "end": samples[-1] if samples else None,
        "samples": samples,
    }
    if samples:
        record["mid"] = samples[len(samples) // 2]
        for key, at_end in (("tangent_start", False), ("tangent_end", True)):
            direction = _end_direction(geometry, space, at_end)
            if direction is not None:
                record[key] = direction
    if truncated:
        record["truncated"] = True
    return record


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


def _text_marker(text, ctx, problem):
    """A SketchText that is not read as outlines: { text: true, sketch, sketch_token?, problem }. The sketch token
    keeps the size probe from following that sketch."""
    sketch = geo.safe(lambda: text.parentSketch, None)
    record = {"text": True, "sketch": geo.safe(lambda: sketch.name, "") or "", "problem": problem}
    token = geo.safe(lambda: sketch.entityToken, "")
    if token:
        record["sketch_token"] = token
    return geo.mark_foreign(record, text, ctx)


class _OnCurve:
    """The geometry of one text outline curve, shaped like a profile curve for `_Space`."""

    sketchEntity = None

    def __init__(self, geometry):
        self.geometry = geometry


def _text_box(text):
    """[min x, min y, max x, max y] in mm of `SketchText.boundingBox` (sketch space), or None."""
    box = geo.safe(lambda: text.boundingBox, None)
    low, high = geo.safe(lambda: geo.point2(box.minPoint), None), geo.safe(lambda: geo.point2(box.maxPoint), None)
    return low + high if low and high else None


def read_text_outlines(text, ctx=None):
    """(profiles, areas) of a SketchText: one profile record per outer outline, with its holes, from
    `SketchText.asCurves()` (transient curves; the text and the design are not changed). Each record is { text: true,
    sketch, sketch_token?, frame, space, reference?, loops }; its area (mm2, outer less holes) is in `areas`.
    A text that cannot be read, is too big or sits in an unknown space is one record without loops and with a
    `problem` the translator words."""
    text = geo.native_input(text, ctx)
    if geo.foreign(text, ctx):
        return [_text_marker(text, ctx, "foreign")], [None]
    sketch = geo.safe(lambda: text.parentSketch, None)
    raw = geo.safe(lambda: text.asCurves(), None)
    geometries = list(raw) if isinstance(raw, (list, tuple)) else geo.collection_items(raw)
    if sketch is None or not geometries:
        return [_text_marker(text, ctx, "unread")], [None]
    if len(geometries) > _MAX_TEXT_CURVES:
        return [_text_marker(text, ctx, "too_many")], [None]
    frame = geo.frame_of(sketch.transform)
    space = _Space(sketch, [_OnCurve(g) for g in geometries], frame, _text_box(text))
    if space.mode not in ("sketch", "model"):
        return [_text_marker(text, ctx, "space")], [None]
    curves = [_read_curve(g, space) for g in geometries]
    found = text_outlines.outlines_of(curves)
    if isinstance(found, str):
        return [_text_marker(text, ctx, found)], [None]
    if len(found) > _MAX_TEXT_PROFILES:
        return [_text_marker(text, ctx, "too_many")], [None]
    base = {"text": True, "sketch": geo.safe(lambda: sketch.name, "") or "", "frame": frame, "space": space.mode}
    token = geo.safe(lambda: sketch.entityToken, "")
    if token:
        base["sketch_token"] = token
    reference = _reference(sketch, ctx)
    if reference is not None:
        base["reference"] = reference
    profiles = [dict(base, loops=outline["loops"]) for outline in found]
    return profiles, [outline["area"] for outline in found]


def read_outlines(raw, ctx=None, measure=True):
    """(profiles, areas) of a feature's `profile` property: a Profile, a planar BRepFace, a SketchText or a
    collection of them. `areas` has one entry per profile record: `Profile.areaProperties` in mm2 for a Profile
    (read only when `measure`), the area of the text outlines for a SketchText record, else None."""
    name = geo.type_name(raw)
    if name == "Profile":
        return [read_profile(raw, ctx)], [profile_area(raw) if measure else None]
    if name == "SketchText":
        return read_text_outlines(raw, ctx)
    if name == "BRepFace":
        return [geo.mark_foreign({"face": True, "type": "BRepFace"}, raw, ctx)], [None]
    if raw is not None and hasattr(raw, "count") and hasattr(raw, "item"):
        profiles, areas = [], []
        for entity in geo.collection_items(raw):
            found = read_outlines(entity, ctx, measure)
            profiles.extend(found[0])
            areas.extend(found[1])
        return profiles, areas
    return [{"kind": "other", "type": name}], [None]


def read_profiles(raw, ctx=None):
    """Profiles of a feature's `profile` property: see `read_outlines`."""
    return read_outlines(raw, ctx, measure=False)[0]
