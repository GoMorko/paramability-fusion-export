"""Sketch profiles as plain dicts: frame, loops and curves in the sketch's own 2D frame (mm)."""
import math

from . import read_geometry as geo

# Which space ProfileCurve.geometry is in. "auto" treats geometry with every point at z near 0 as sketch space and
# anything else as model space. A sketch lying in a model plane with turned axes is not told apart by "auto"; set
# "sketch" or "model" after hand test 2 (docs/hand-tests.md).
GEOMETRY_SPACE = "auto"

_FLAT_CM = 1e-5  # 1e-4 mm
_SAMPLES = 200


def _probe_points(geometry):
    """Points that tell which space a curve is in."""
    out = []
    for name in ("startPoint", "endPoint", "center"):
        p = geo.safe(lambda: getattr(geometry, name), None)
        if p is not None:
            out.append(p)
    return out


class _Space:
    """Maps curve geometry of one profile into sketch 2D."""

    def __init__(self, sketch, geometries):
        mode = GEOMETRY_SPACE
        if mode == "auto":
            probes = [p for g in geometries for p in _probe_points(g)]
            mode = "model" if any(abs(p.z) > _FLAT_CM for p in probes) else "sketch"
        self.sketch = sketch
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
    loop_curves = [[pc.geometry for pc in geo.collection_items(loop.profileCurves)] for loop in loops]
    space = _Space(sketch, [g for curves in loop_curves for g in curves])
    return {
        "sketch": sketch.name,
        "frame": geo.frame_of(sketch.transform),
        "loops": [
            {"outer": bool(loop.isOuter), "curves": [_read_curve(g, space) for g in curves]}
            for loop, curves in zip(loops, loop_curves)
        ],
    }


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
