"""Sketch profiles as plain dicts: frame, loops and curves in the sketch's own 2D frame (mm)."""
import math

from . import read_geometry as geo

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


def read_profile(profile):
    """One Profile as { sketch, frame, loops }."""
    sketch = profile.parentSketch
    loops = geo.collection_items(profile.profileLoops)
    loop_curves = [geo.collection_items(loop.profileCurves) for loop in loops]
    frame = geo.frame_of(sketch.transform)
    space = _Space(sketch, [c for curves in loop_curves for c in curves], frame)
    return {
        "sketch": sketch.name,
        "frame": frame,
        "space": space.mode,
        "loops": [
            {"outer": bool(loop.isOuter), "curves": [_read_curve(c.geometry, space) for c in curves]}
            for loop, curves in zip(loops, loop_curves)
        ],
    }


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


def read_profiles(raw):
    """Profiles of a feature's `profile` property: a Profile, a planar BRepFace or a collection of them."""
    name = geo.type_name(raw)
    if name == "Profile":
        return [read_profile(raw)]
    if name == "BRepFace":
        return [{"face": True, "type": "BRepFace"}]
    if raw is not None and hasattr(raw, "count") and hasattr(raw, "item"):
        out = []
        for entity in geo.collection_items(raw):
            out.extend(read_profiles(entity))
        return out
    return [{"kind": "other", "type": name}]
