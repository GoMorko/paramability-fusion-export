"""Captures of revolves with holes, several outlines and symmetric angles that follow sizes, for the Orca tests and
the live check:

    python3 -m tests.orca_revolves <name> <capture.json>
    python3 scripts/orca_live_check.py write <capture.json> <out.3mf>

The outlines lie on the XZ plane (sketch x along X, sketch y along Z) and turn about the Z axis, so each part lies
flat on the plate. Volumes are exact: a loop of area A whose centre lies at radius R turns into 2 pi R A per full turn.
"""
import copy
import json
import math
import sys

from tests import context  # noqa: F401
from tests.orca_sized import fixture, sized
from lib.geometry import vec

XZ = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 0, 1], "z": [0, -1, 0]}
AXIS = {"point": [0, 0, 0], "dir": [0, 0, 1]}


def rect(u0, v0, u1, v1):
    corners = [[u0, v0], [u1, v0], [u1, v1], [u0, v1]]
    return [{"kind": "line", "start": a, "end": b} for a, b in zip(corners, corners[1:] + corners[:1])]


def ring_loops(hole=True):
    """The outline from radius 10 to 20, 10 high, with a hole of radius 2 at radius 15, 5 up."""
    loops = [{"outer": True, "curves": rect(10, 0, 20, 10)}]
    if hole:
        loops.append({"outer": False, "curves": [{"kind": "circle", "center": [15, 5], "radius": 2}]})
    return loops


def _box(lo, hi):
    return {"min": list(lo), "max": list(hi)}


def revolve_item(index, loops_list, operation="newBody", angle=360.0, symmetric=False, **data):
    profiles = [{"sketch": "Sketch%d" % index, "frame": copy.deepcopy(XZ), "loops": loops} for loops in loops_list]
    found = {"operation": operation, "profiles": profiles, "axis": copy.deepcopy(AXIS), "project_axis": False,
             "extent": {"kind": "angle", "angle_deg": angle, "symmetric": symmetric}, "participants": [],
             "start_face_normal": None}
    found.update(data)
    return {"index": index, "name": "Revolve%d" % index, "type": "RevolveFeature", "suppressed": False,
            "health": "ok", "message": "", "in_target_component": True,
            "bodies_after": [{"token": "t1", "name": "Body1"}], "data": found}


def _capture(items, box, volume, comment):
    return {"_comment": comment, "capture": 3, "fusion": "2.0.0", "design": "Test", "up_axis": "z",
            "target": {"token": "t1", "name": "Body1", "box": box, "volume_mm3": volume}, "items": items}


def _sketch(index):
    return {"index": index, "name": "Sketch%d" % index, "type": "Sketch", "suppressed": False, "health": "ok",
            "message": "", "in_target_component": True, "bodies_after": [], "data": {}}


def ring_with_hole():
    """A full turn of the ring outline with its hole: 3000 pi - 120 pi^2 = 8240.42 mm3."""
    volume = 3000 * math.pi - 120 * math.pi ** 2
    return _capture([_sketch(0), revolve_item(1, [ring_loops()])], _box([-20, -20, 0], [20, 20, 10]), volume,
                    "Ring from radius 10 to 20, 10 high, with a hole of radius 2 at radius 15, turned a full circle.")


def _rod(items_after, volume, comment, top=30, reach=20):
    """A rod of radius 12 from z 0 to `top` (Extrude1), then `items_after`; the part reaches `reach` from the axis."""
    rod = copy.deepcopy(fixture("extrude_ring")["items"][1])
    rod["data"]["profiles"][0]["loops"] = [{"outer": True, "curves": [{"kind": "circle", "center": [0, 0],
                                                                         "radius": 12}]}]
    rod["data"]["side_one"]["distance"] = float(top)
    return _capture([_sketch(0), rod] + items_after, _box([-reach, -reach, 0], [reach, reach, top]), volume, comment)


def ring_on_rod():
    """The holed ring joined onto the rod: rod 4320 pi, ring outside it 2560 pi - 120 pi^2; 20429.80 mm3."""
    volume = 6880 * math.pi - 120 * math.pi ** 2
    return _rod([_sketch(2), revolve_item(3, [ring_loops()], "join")], volume,
                "A rod of radius 12, 30 high, with the holed ring (radius 10 to 20, 10 high, hole radius 2 at 15) "
                "joined at its foot.")


def two_rings_on_rod():
    """Two separate outlines joined onto the rod: radius 10 to 20 and 0 to 5 high, radius 10 to 16 and 20 to 25 high.
    Rod 4320 pi, rings outside it 1280 pi and 560 pi: 6160 pi = 19352.21 mm3."""
    loops = [[{"outer": True, "curves": rect(10, 0, 20, 5)}], [{"outer": True, "curves": rect(10, 20, 16, 25)}]]
    return _rod([_sketch(2), revolve_item(3, loops, "join")], 6160 * math.pi,
                "A rod of radius 12, 30 high, with two separate rings joined in one revolve: radius 10 to 20 from "
                "z 0 to 5, and radius 10 to 16 from z 20 to 25.")


def groove_both_sides(reach=12.0):
    """A groove cut into the rod by one Revolve Cut of a full turn with two outlines drawn on the two sides of the
    axis: radius 9 to 12 from z 10 to 14, and its mirror from x = -`reach` to -9. Both turn into the same ring, so Orca
    gets one cut: rod 4320 pi less the groove 252 pi = 4068 pi = 12780.0 mm3."""
    loops = [[{"outer": True, "curves": rect(9, 10, 12, 14)}], [{"outer": True, "curves": rect(-reach, 10, -9, 14)}]]
    return _rod([_sketch(2), revolve_item(3, loops, "cut")], 4068 * math.pi,
                "A rod of radius 12, 30 high, with a groove from radius 9 to 12, z 10 to 14, cut by one Revolve Cut "
                "of a full turn whose two outlines lie on the two sides of the axis.", reach=12)


def caps(per_side_deg, cut=False):
    """The measured outward normals (start, end) of a symmetric turn of the ring outline about +Z, `per_side_deg` to
    each side: the outline moves along +Y at the sketch plane."""
    first = vec.rotate([0.0, 1.0, 0.0], [0.0, 0.0, 1.0], -per_side_deg)
    last = vec.rotate([0.0, 1.0, 0.0], [0.0, 0.0, 1.0], per_side_deg)
    sign = 1.0 if cut else -1.0
    return vec.scale(first, sign), vec.scale(last, -sign)


def symmetric_ring(per_side=45.0, hole=False):
    """The ring outline (no hole unless `hole`) turned `per_side` degrees to each side of the XZ plane, the angle read
    from the user parameter `half_deg`. Without the hole: 3000 pi x 2 per_side / 360, so 750 pi = 2356.19 mm3 at 45,
    1500 pi = 4712.39 at 90 and the full 3000 pi = 9424.78 at 180 or more."""
    start, end = caps(per_side)
    total = min(2.0 * per_side, 360.0)
    area = 3000 * math.pi - (120 * math.pi ** 2 if hole else 0.0)
    half = min(per_side, 180.0)
    angles = [math.radians(t) for t in [-half, half] + [k / 10.0 for k in range(-1800, 1801) if abs(k) <= 10 * half]]
    points = [(r * math.cos(t), r * math.sin(t)) for r in (10, 20) for t in angles]
    item = revolve_item(1, [ring_loops(hole)], angle=per_side, symmetric=True,
                        start_face_normal=None if total >= 360 else start,
                        end_face_normal=None if total >= 360 else end)
    capture = _capture([_sketch(0), item], _box([min(p[0] for p in points), min(p[1] for p in points), 0],
                            [max(p[0] for p in points), max(p[1] for p in points), 10]), area * total / 360.0,
                       "Ring from radius 10 to 20, 10 high, turned %g degrees to each side of the XZ plane; the "
                       "angle reads the user parameter half_deg." % per_side)
    return sized(capture, 1, "extent.angle_deg", "half_deg", per_side, unit="deg")


BUILDERS = {"ring_with_hole": ring_with_hole, "ring_on_rod": ring_on_rod, "two_rings_on_rod": two_rings_on_rod,
            "symmetric_ring": symmetric_ring, "groove_both_sides": groove_both_sides}


if __name__ == "__main__":
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        json.dump(BUILDERS[sys.argv[1]](), out, indent=1)
