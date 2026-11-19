"""Captures of thin extrudes along a line with arcs, for the tests and the live check:
`python3 -m tests.orca_thin_arcs <name> <file>` writes the capture `<name>` of `BUILDERS` to `<file>`, for
`scripts/orca_live_check.py write <file> <out.3mf>`. Each is a new body 15 high on the XY plane, its wall 2 thick
(`wall_mm`); the box and volume are worked out from the exact band (lines and arcs).

- `thin_arc_ell`: line (0, 0) to (30, 0), a quarter arc of radius 10 about (30, 10) to (40, 10), line to (40, 30).
  Inside the turn (side one): 30 * 2 + 20 * 2 + pi / 4 * (10^2 - 8^2) = 100 + 9 pi = 128.274 mm2, so 1924.115 mm3;
  box (0, 0, 0) to (40, 30, 15).
- `thin_arc_u`: line (0, 0) to (30, 0), a half arc of radius 10 about (30, 10) to (30, 20), line back to (0, 20). Centred:
  2 * 30 * 2 + pi / 2 * (11^2 - 9^2) = 120 + 20 pi = 182.832 mm2, so 2742.478 mm3; box (0, -1, 0) to (41, 21, 15).
"""
import json
import math
import sys

from tests.orca_extents import UP, capture, extrude, side, sketch_item
from tests.probe_helpers import model, user

from lib.design_model.steps import thin as facts
from lib.design_model.steps import thin_arc
from lib.geometry.footprint import Footprint, arc_span, polyline

HEIGHT = 15.0
THICKNESS = 2.0


def line(a, b):
    return {"kind": "line", "start": list(a), "end": list(b)}


def arc(centre, radius, from_deg, to_deg):
    """An arc about `centre` from the angle `from_deg` to `to_deg`, turning left when `to_deg` is larger."""
    def at(deg):
        return [centre[0] + radius * math.cos(math.radians(deg)), centre[1] + radius * math.sin(math.radians(deg))]
    return {"kind": "arc", "start": at(from_deg), "mid": at((from_deg + to_deg) / 2.0), "end": at(to_deg),
            "center": list(centre), "radius": radius}


ELL = [line((0.0, 0.0), (30.0, 0.0)), arc((30.0, 10.0), 10.0, -90.0, 0.0), line((40.0, 10.0), (40.0, 30.0))]
U = [line((0.0, 0.0), (30.0, 0.0)), arc((30.0, 10.0), 10.0, -90.0, 90.0), line((30.0, 20.0), (0.0, 20.0))]


def path_record(pieces, sketch="Sketch1", token="s1"):
    """The path of `pieces` (in path order) as the reader writes it: a sketch arc runs left from its start, so an arc
    that turns right is written the other way and `opposed`."""
    curves = []
    for n, piece in enumerate(pieces):
        flat = dict(piece)
        opposed = piece["kind"] == "arc" and thin_arc.sweep(piece) < 0
        if opposed:
            flat["start"], flat["end"] = piece["end"], piece["start"]
        record = {"kind": piece["kind"], "start": flat["start"] + [0.0], "end": flat["end"] + [0.0],
                  "opposed": opposed, "entity": "c%d" % n, "flat": flat}
        if piece["kind"] == "arc":
            record.update(center=piece["center"] + [0.0], radius=piece["radius"])
        curves.append(record)
    return {"closed": False, "kind": "sketch", "sketch": sketch, "sketch_token": token, "frame": UP,
            "reference": {"kind": "constructionPlane", "token": "tok_xy", "origin": True}, "projected": False,
            "curves": curves, "edges": []}


def wall_faces(curves, low, high):
    """The faces Fusion lists for a wall with the closed outline `curves` between the heights `low` and `high` on the
    XY plane: per curve a flat face (a line) or a round one (an arc) at its middle, facing out, and both ends at the
    middle of the last curve (the square start of the wall)."""
    footprint = Footprint({"loops": [{"outer": True, "curves": curves}]})
    out = []
    for n, curve in enumerate(curves):
        middle = curve["mid"] if curve["kind"] == "arc" else [(curve["start"][i] + curve["end"][i]) / 2.0
                                                               for i in range(2)]
        normal = footprint.outward(n, middle)
        out.append({"surface": "Cylinder" if curve["kind"] == "arc" else "Plane",
                    "point": list(middle) + [(low + high) / 2.0], "normal": list(normal) + [0.0]})
    cap = curves[-1]
    edge = [(cap["start"][i] + cap["end"][i]) / 2.0 for i in range(2)]
    out += [{"surface": "Plane", "point": edge + [low], "normal": [0.0, 0.0, -1.0]},
            {"surface": "Plane", "point": edge + [high], "normal": [0.0, 0.0, 1.0]}]
    return out


def box_of(curves, height):
    points = [p for curve in curves for p in (polyline(curve) if curve["kind"] == "line" else _dense(curve))]
    xs, ys = [round(p[0], 6) for p in points], [round(p[1], 6) for p in points]
    return (min(xs), min(ys), 0.0), (max(xs), max(ys), height)


def _dense(curve):
    start, turn = arc_span(curve)
    c, r = curve["center"], curve["radius"]
    return [[c[0] + r * math.cos(start + turn * k / 3600), c[1] + r * math.sin(start + turn * k / 3600)]
            for k in range(3601)]


def wall(pieces, location, thickness=THICKNESS, height=HEIGHT, design="Thin arc"):
    """A new body: the thin wall along `pieces`, `thickness` thick on the side Fusion's `location` gives, `height`
    up. Its faces, box and volume are those of the exact band."""
    side_name = facts.RULE.get(location, "middle")
    curves = thin_arc.band_curves(pieces, *facts.reaches(side_name, thickness))
    volume = thin_arc.band_area(curves) * height
    item = extrude(1, "Extrude1", [{"kind": "other", "type": "Path"}], side_one=side(height), end_offset=None,
                   target_box_before=None, path=path_record(pieces), wall_faces=wall_faces(curves, 0.0, height))
    data = item["data"]
    data["thin"] = True
    data["thin_wall"] = {"location": location, "thickness": thickness, "location_two": location,
                         "thickness_two": None, "profile_type": "Path"}
    data["params"]["thin.thickness"] = {"name": "d_wall", "expression": "wall_mm", "value": thickness}
    low, high = box_of(curves, height)
    item["target_before"] = None
    item["target_after"] = {"box": {"min": list(low), "max": list(high)}, "volume_mm3": round(volume, 6)}
    found = capture([sketch_item(0, "Sketch1"), item], (low, high), volume,
                    [user("wall_mm", "%g mm" % thickness, thickness)],
                    [model("d_wall", "wall_mm", thickness, kind="feature", token="tok_d_wall")])
    found["design"] = design
    return found


def ell_arc(location="side1"):
    return wall(ELL, location, design="Thin L with an arc")


def u_arc(location="center"):
    return wall(U, location, design="Thin U")


BUILDERS = {"thin_arc_ell": ell_arc, "thin_arc_u": u_arc}


if __name__ == "__main__":
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        json.dump(BUILDERS[sys.argv[1]](), out, indent=1)
