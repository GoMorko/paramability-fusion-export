"""Raw Orca recipes that sweep a round wire along Orca's Helix, to compare in OrcaSlicer with the shape of a Fusion coil:

    python3 -m tests.orca_coils <name> <out.3mf>
    python3 scripts/orca_live_check.py check

The Orca copy leaves every coil out (`orca_translate/coils.py`). These probes show what Orca builds instead. Each is a
Helix on the XY plane through `ORIGIN` (its start at `ORIGIN + (R, 0, 0)`, turning right hand about +Z), a circle
sketch of radius `r` centred on that start, and a Sweep of the circle along the helix as a new body:
- `square`: the circle on the plane square to the helix at its start. Orca's sweep keeps it square, so the body is a
  round tube: pi r^2 times the helix length.
- `upright`: the circle on the plane through the axis at the start, where Fusion's coil has its section. Fusion
  carries it along the helix with a screw motion: the volume is pi r^2 times 2 pi R times the turns, and the ends lie
  on planes through the axis. Orca's sweep builds this shape only if its frame does not turn about the path.

`expected` gives the volume and the box (Orca's world mm) of the tube and of the Fusion coil for a probe.
"""
import math
import sys

from tests import context  # noqa: F401

from lib.geometry import mesh as meshes
from lib.orca_recipe.enums import BooleanMode, FeatureType, SketchShape
from lib.orca_recipe.recipe import Recipe, serialize
from lib.orca_recipe.sketch import SketchPlane
from lib.orca_recipe.threemf import MeshObject, write_3mf
from lib.orca_translate.tools import feature

ORIGIN = (128.0, 128.0, 2.0)

# name: (helix radius R at the wire's centre, pitch, height, wire radius r, section).
PROBES = {
    "spring_square": (10.0, 5.0, 20.0, 1.0, "square"),
    "spring_upright": (10.0, 5.0, 20.0, 1.0, "upright"),
    "quarter_square": (10.0, 20.0, 5.0, 1.0, "square"),
    "quarter_upright": (10.0, 20.0, 5.0, 1.0, "upright"),
}


def _tangent(radius, pitch):
    length = math.hypot(2.0 * math.pi * radius, pitch)
    return (0.0, 2.0 * math.pi * radius / length, pitch / length)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def recipe(name):
    """The Recipe of a probe: the helix, the circle sketch and the sweep."""
    radius, pitch, height, wire, section = PROBES[name]
    out = Recipe()
    out.modeling_origin = ORIGIN
    out.add(feature(FeatureType.HELIX, "Helix", plane=SketchPlane.xy(ORIGIN), helix_radius=radius,
                    helix_pitch=pitch, helix_height=height))
    normal = _tangent(radius, pitch) if section == "square" else (0.0, 1.0, 0.0)
    x_axis = (1.0, 0.0, 0.0)
    start = (ORIGIN[0] + radius, ORIGIN[1], ORIGIN[2])
    plane = SketchPlane(start, normal, x_axis, _cross(normal, x_axis))
    circle = out.add(feature(FeatureType.SKETCH, "Wire", shape=SketchShape.CIRCLE, radius=wire, plane=plane))
    out.add(feature(FeatureType.SWEEP, "Coil", sketch_ref=circle, sweep_path_ref=0, mode=BooleanMode.NEW))
    return out


def _tube_points(radius, pitch, height, wire, steps=3000, around=180):
    turn = 2.0 * math.pi * height / pitch
    for i in range(steps + 1):
        u = turn * i / steps
        centre = (radius * math.cos(u), radius * math.sin(u), pitch * u / (2.0 * math.pi))
        t = _tangent(radius, pitch)
        tangent = (-t[1] * math.sin(u), t[1] * math.cos(u), t[2])
        inward = (-math.cos(u), -math.sin(u), 0.0)
        other = _cross(tangent, inward)
        for k in range(around):
            a = 2.0 * math.pi * k / around
            yield tuple(centre[j] + wire * (math.cos(a) * inward[j] + math.sin(a) * other[j]) for j in range(3))


def _screw_points(radius, pitch, height, wire, steps=3000, around=180):
    turn = 2.0 * math.pi * height / pitch
    for i in range(steps + 1):
        u = turn * i / steps
        for k in range(around):
            a = 2.0 * math.pi * k / around
            out, up = radius + wire * math.cos(a), wire * math.sin(a)
            yield (out * math.cos(u), out * math.sin(u), up + pitch * u / (2.0 * math.pi))


def _box(points):
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for p in points:
        for j in range(3):
            lo[j], hi[j] = min(lo[j], p[j]), max(hi[j], p[j])
    return {"min": [round(v + o, 3) for v, o in zip(lo, ORIGIN)], "max": [round(v + o, 3) for v, o in zip(hi, ORIGIN)]}


def expected(name):
    """`{tube: (volume, box), fusion: (volume, box)}` of a probe: what a round tube along the helix has, and what
    Fusion's coil of the same sizes has. Volumes are exact, boxes sampled to about 0.001 mm."""
    radius, pitch, height, wire, _ = PROBES[name]
    turns = height / pitch
    area = math.pi * wire ** 2
    return {"tube": (area * turns * math.hypot(2.0 * math.pi * radius, pitch),
                     _box(_tube_points(radius, pitch, height, wire))),
            "fusion": (area * 2.0 * math.pi * radius * turns, _box(_screw_points(radius, pitch, height, wire)))}


def write(name, path):
    found = expected(name)
    plate = found["fusion"][1]
    vertices, triangles = meshes.box_mesh(plate)
    write_3mf(path, serialize(recipe(name)), [MeshObject(name, vertices, triangles)])
    return found


if __name__ == "__main__":
    shapes = write(sys.argv[1], sys.argv[2])
    for kind, (volume, box) in shapes.items():
        print("%-6s volume %.2f mm3, box %s .. %s" % (kind, volume, box["min"], box["max"]))
