"""Captures of path patterns of square pegs on a plate, for the Orca tests and the live check:

    python3 -m tests.orca_path_patterns <name> <capture.json>
    python3 scripts/orca_live_check.py write <capture.json> <out.3mf>

Each peg is a 6 by 6 mm square joined on the plate's top face (z 4) and 6 mm high (216 mm3), so a volume is the
plate's plus 216 per peg. `count` and `pitch` are user parameters of the pattern's count and distance. `expected`
gives the box and volume of a builder at other values of the parameters (the `--set` values of the live check).

- `pegs_line`: a 40 by 20 plate, 4 pegs 10 mm apart along a sketch line from (5, 10) to (45, 10).
- `pegs_arc`: a 50 by 40 plate, 5 pegs 12 mm apart along an arc of radius 35 about (5, 5) from (40, 5) to (5, 40),
  turning with the arc.
- `pegs_arc_slide`: the same plate and arc, 5 pegs over 48 mm of the arc (an extent), keeping their direction.
"""
import json
import math
import sys

from tests import context  # noqa: F401
from tests.orca_extents import UP, at, capture, extrude, profile, rect, side, sketch_item
from tests.orca_sized import sized

from lib.geometry import vec

PEG = 3.0
PEG_HEIGHT = 6.0
PLATE_HEIGHT = 4.0
CENTRE = [5.0, 5.0, PLATE_HEIGHT]
RADIUS = 35.0
LINE_PLATE = (40.0, 20.0)
ARC_PLATE = (50.0, 40.0)


def turn_frame(degrees):
    """The frame of a turn by `degrees` about the vertical axis through `CENTRE`."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    x, y = CENTRE[0], CENTRE[1]
    return {"origin": [x - (c * x - s * y), y - (s * x + c * y), 0.0], "x": [c, s, 0.0], "y": [-s, c, 0.0],
            "z": [0.0, 0.0, 1.0]}


def _shift_frame(offset):
    return dict(UP, origin=[float(v) for v in offset])


def _arc_point(degrees):
    a = math.radians(degrees)
    return [CENTRE[0] + RADIUS * math.cos(a), CENTRE[1] + RADIUS * math.sin(a), PLATE_HEIGHT]


def _path(curve):
    flat = {k: (v[:2] if isinstance(v, list) and len(v) == 3 and k != "normal" else v) for k, v in curve.items()}
    flat.pop("normal", None)
    return {"closed": False, "kind": "sketch", "curves": [dict(curve, flat=flat, entity="c1", opposed=False,
                                                              check=None)],
            "edges": [], "sketch": "Sketch4", "sketch_token": "s4", "frame": at(PLATE_HEIGHT),
            "reference": {"kind": "constructionPlane", "origin": True}, "projected": False}


def _pattern(path, count, distance, kind, frames, along=True):
    elements = [{"id": n, "suppressed": False, "frame": frame} for n, frame in enumerate(frames)]
    return {"index": 5, "name": "PathPattern1", "type": "PathPatternFeature", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}],
            "data": {"entity_type": "features", "sources": [3], "path": path, "quantity": count,
                     "distance": float(distance), "distance_type": kind, "start_point": 0.0, "flip": False,
                     "symmetric": False, "along_path": along, "elements": elements, "suppressed_ids": []}}


def _plate_and_peg(width, depth, peg_centre):
    x, y = peg_centre
    return [sketch_item(0, "Sketch1"),
            extrude(1, "Extrude1", [profile("Sketch1", UP, rect(0, 0, width, depth))], side_one=side(PLATE_HEIGHT),
                    end_offset=PLATE_HEIGHT),
            sketch_item(2, "Sketch2"),
            extrude(3, "Extrude2", [profile("Sketch2", at(PLATE_HEIGHT), rect(x - PEG, y - PEG, x + PEG, y + PEG))],
                    operation="join", side_one=side(PEG_HEIGHT), end_offset=PEG_HEIGHT),
            sketch_item(4, "Sketch4")]


def _peg_box(centre, degrees):
    """The (min, max) corners of a peg centred at `centre` (x, y) turned `degrees`."""
    a = math.radians(degrees)
    half = PEG * (abs(math.cos(a)) + abs(math.sin(a)))
    return ([centre[0] - half, centre[1] - half, PLATE_HEIGHT],
            [centre[0] + half, centre[1] + half, PLATE_HEIGHT + PEG_HEIGHT])


def _box(plate, pegs):
    """The box of the plate and of the pegs `(centre, degrees)`."""
    low, high = [0.0, 0.0, 0.0], [plate[0], plate[1], PLATE_HEIGHT]
    for centre, degrees in pegs:
        a, b = _peg_box(centre, degrees)
        low, high = [min(p, q) for p, q in zip(low, a)], [max(p, q) for p, q in zip(high, b)]
    return [round(v, 4) for v in low], [round(v, 4) for v in high]


def _line_pegs(count, pitch):
    return [((5.0 + k * pitch, 10.0), 0.0) for k in range(count)]


def _arc_pegs(count, pitch, turns=True, extent=None):
    """The pegs along the arc: `pitch` mm apart, or `count` pegs over `extent` mm."""
    gap = extent / (count - 1) if extent is not None else pitch
    out = []
    for k in range(count):
        degrees = math.degrees(k * gap / RADIUS)
        out.append((_arc_point(degrees)[:2], degrees if turns else 0.0))
    return out


def _expected(plate, pegs):
    box = _box(plate, pegs)
    return {"box": {"min": box[0], "max": box[1]},
            "volume_mm3": round(plate[0] * plate[1] * PLATE_HEIGHT + len(pegs) * (2 * PEG) ** 2 * PEG_HEIGHT, 4)}


def _sized(found, count, distance):
    sized(found, 5, "quantity", "count", count, unit="")
    return sized(found, 5, "distance", "pitch", distance)


def pegs_line(count=4, pitch=10.0):
    """4 pegs 10 mm apart along a 40 mm sketch line on a 40 by 20 plate: 3200 + 4 x 216 = 4064 mm3."""
    line = {"kind": "line", "start": [5.0, 10.0, PLATE_HEIGHT], "end": [45.0, 10.0, PLATE_HEIGHT]}
    frames = [_shift_frame([k * pitch, 0.0, 0.0]) for k in range(count)]
    items = _plate_and_peg(*LINE_PLATE, (5.0, 10.0)) + [_pattern(_path(line), count, pitch, "spacing", frames)]
    found = _expected(LINE_PLATE, _line_pegs(count, pitch))
    made = capture(items, (found["box"]["min"], found["box"]["max"]), found["volume_mm3"])
    made["_comment"] = "A 40 by 20 by 4 plate with %d square pegs %g mm apart along a sketch line." % (count, pitch)
    return _sized(made, count, pitch)


def _arc_curve():
    return {"kind": "arc", "start": _arc_point(0.0), "end": _arc_point(90.0), "mid": _arc_point(45.0),
            "center": list(CENTRE), "normal": [0.0, 0.0, 1.0], "radius": RADIUS}


def pegs_arc(count=5, pitch=12.0):
    """5 pegs 12 mm apart along a quarter arc of radius 35, turning with it: 8000 + 5 x 216 = 9080 mm3."""
    frames = [turn_frame(math.degrees(k * pitch / RADIUS)) for k in range(count)]
    items = _plate_and_peg(*ARC_PLATE, _arc_point(0.0)[:2]) + [
        _pattern(_path(_arc_curve()), count, pitch, "spacing", frames)]
    found = _expected(ARC_PLATE, _arc_pegs(count, pitch))
    made = capture(items, (found["box"]["min"], found["box"]["max"]), found["volume_mm3"])
    made["_comment"] = ("A 50 by 40 by 4 plate with %d square pegs %g mm apart along an arc of radius 35, turning "
                        "with it." % (count, pitch))
    return _sized(made, count, pitch)


def pegs_arc_slide(count=5, extent=48.0):
    """5 pegs over 48 mm of the quarter arc, keeping their direction: 8000 + 5 x 216 = 9080 mm3."""
    start = _arc_point(0.0)
    frames = [_shift_frame(vec.sub(_arc_point(math.degrees(k * extent / (count - 1) / RADIUS)), start))
              for k in range(count)]
    items = _plate_and_peg(*ARC_PLATE, start[:2]) + [
        _pattern(_path(_arc_curve()), count, extent, "extent", frames, along=False)]
    found = _expected(ARC_PLATE, _arc_pegs(count, None, turns=False, extent=extent))
    made = capture(items, (found["box"]["min"], found["box"]["max"]), found["volume_mm3"])
    made["_comment"] = ("A 50 by 40 by 4 plate with %d square pegs over %g mm of an arc of radius 35, keeping their "
                        "direction." % (count, extent))
    return _sized(made, count, extent)


def expected(name, count, pitch):
    """The box and volume of the builder `name` at `count` and `pitch` (the extent for `pegs_arc_slide`)."""
    if name == "pegs_line":
        return _expected(LINE_PLATE, _line_pegs(count, pitch))
    if name == "pegs_arc":
        return _expected(ARC_PLATE, _arc_pegs(count, pitch))
    return _expected(ARC_PLATE, _arc_pegs(count, None, turns=False, extent=pitch))


BUILDERS = {"pegs_line": pegs_line, "pegs_arc": pegs_arc, "pegs_arc_slide": pegs_arc_slide}


if __name__ == "__main__":
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        json.dump(BUILDERS[sys.argv[1]](), out, indent=1)
