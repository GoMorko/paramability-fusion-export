"""Captures of patterns and mirrors of bodies whose copies one Combine joins to a plate or cuts from a block, for the
Orca tests and the live check:

    python3 -m tests.orca_body_patterns <name> <capture.json>
    python3 scripts/orca_live_check.py write <capture.json> <out.3mf>

Each peg is a 6 by 6 mm square body (Body2) standing on the plate's top face (z 4), `peg_h` high (6 mm, 216 mm3).
The plate is Body1, the exported body. `count` and `pitch` (or the circular count) are user parameters of the
pattern. `expected` gives the box and volume of a builder at other values of the parameters (the `--set` values of
the live check). The count keeps its number in Orca, so a new count leaves the body as it is.

- `peg_row`: a 60 by 20 by 4 plate and a peg at (8, 10), patterned 4 times 14 mm apart along X, then joined.
- `peg_ring`: a 60 by 60 by 4 plate round the origin and a peg at (20, 0), patterned 6 times round the Z axis.
- `mirrored_peg`: a 40 by 20 by 4 plate round the origin and a peg at (-12, 0), mirrored across the YZ plane.
- `cutter_row`: a 60 by 20 by 10 block and a 6 by 6 cutter from z 4 to 14 at (8, 10), patterned 4 times 14 mm
  apart, then cut from the block: each pocket is 6 deep (216 mm3).
"""
import json
import math
import sys

from tests import context  # noqa: F401
from tests.orca_extents import UP, at, capture, extrude, profile, rect, side, sketch_item
from tests.orca_sized import sized

PEG = 3.0
PLATE_H = 4.0
BLOCK_H = 10.0
CUTTER_H = 10.0
B1 = {"token": "t1", "name": "Body1"}
B2 = {"token": "t2", "name": "Body2"}


def _body(n):
    return {"token": "t%d" % n, "name": "Body%d" % n}


def _corners(x0, y0, z0, x1, y1, z1):
    return [[x, y, z] for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]


def _moved(points, rows, offset):
    return [[round(sum(rows[i][k] * p[k] for k in range(3)) + offset[i], 9) for i in range(3)] for p in points]


def _turn(degrees):
    a = math.radians(degrees)
    c, s = round(math.cos(a), 12), round(math.sin(a), 12)
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def _frame(rows, offset):
    return {"origin": list(offset), "x": [rows[i][0] for i in range(3)], "y": [rows[i][1] for i in range(3)],
            "z": [rows[i][2] for i in range(3)]}


IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def _items(plate, peg_centre, low, height, plate_h=PLATE_H):
    """The plate (Extrude1, Body1 from z 0 to `plate_h`) and the peg or cutter (Extrude2, Body2, a new
    body from z `low`, `height` high)."""
    x0, y0, x1, y1 = plate
    x, y = peg_centre
    peg = extrude(3, "Extrude2", [profile("Sketch2", at(low), rect(x - PEG, y - PEG, x + PEG, y + PEG))],
                  side_one=side(height), end_offset=height)
    peg["bodies_after"] = [dict(B2)]
    return [sketch_item(0, "Sketch1"),
            extrude(1, "Extrude1", [profile("Sketch1", UP, rect(x0, y0, x1, y1))], side_one=side(plate_h),
                    end_offset=plate_h),
            sketch_item(2, "Sketch2"), peg]


def _pattern_item(kind, source_points, moves, data):
    """A pattern or mirror of Body2 at index 4: `moves` are the `(rows, offset)` of the copies, the original left
    out; the copies are Body3, Body4 and so on."""
    copies = [dict(_body(n + 3), points=_moved(source_points, rows, offset)) for n, (rows, offset) in enumerate(moves)]
    found = {"entity_type": "bodies", "sources": [], "source_bodies": [dict(B2, points=source_points)],
             "result_bodies": copies, "suppressed_ids": []}
    found.update(data)
    return {"index": 4, "name": {"MirrorFeature": "Mirror1", "CircularPatternFeature": "CircularPattern1"}.get(
        kind, "RectangularPattern1"), "type": kind, "suppressed": False, "health": "ok", "in_target_component": True,
        "bodies_after": [_body(n + 3) for n in range(len(moves))], "data": found}


def _combine(operation, count, tool_volume, before, after):
    tools = [dict(_body(n + 2), volume=tool_volume) for n in range(count)]
    return {"index": 5, "name": "Combine1", "type": "CombineFeature", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [dict(B1)],
            "data": {"target": dict(B1), "tools": tools, "operation": operation, "keep_tools": False,
                     "volume_before": before, "volume_after": after}}


def _row_moves(count, pitch):
    return [(IDENTITY, [k * pitch, 0.0, 0.0]) for k in range(1, count)]


def _row(source_points, count, pitch):
    elements = [{"id": k, "suppressed": False, "frame": _frame(IDENTITY, [k * pitch, 0.0, 0.0])} for k in range(count)]
    return _pattern_item("RectangularPatternFeature", source_points, _row_moves(count, pitch), {
        "direction_one": [1.0, 0.0, 0.0], "quantity_one": count, "distance_one": float(pitch), "direction_two": None,
        "quantity_two": 1, "distance_two": 0.0, "distance_type": "spacing", "symmetric_one": False,
        "symmetric_two": False, "elements": elements, "direction_one_place": {"origin": True, "own": True}})


def _made(items, box, volume, comment):
    found = capture(items, box, volume)
    found["_comment"] = comment
    return found


def _box(low, high):
    return [round(v, 4) for v in low], [round(v, 4) for v in high]


# ---- the expected bodies ------------------------------------------------------------------------------------------

def _peg_volume(peg_h):
    return (2 * PEG) ** 2 * peg_h


def expected(name, count=None, pitch=None, peg_h=6.0):
    """`{box, volume_mm3}` of the builder `name` with the pattern at `count` and `pitch` and the pegs `peg_h` high
    (the defaults of the builder when None). The count keeps its number in Orca: give the builder's count."""
    if name == "peg_row":
        count, pitch = count or 4, 14.0 if pitch is None else pitch
        reach = max(60.0, 11.0 + (count - 1) * pitch)
        return {"box": {"min": [0.0, 0.0, 0.0], "max": [reach, 20.0, PLATE_H + peg_h]},
                "volume_mm3": round(60 * 20 * PLATE_H + count * _peg_volume(peg_h), 4)}
    if name == "peg_ring":
        count = count or 6
        return {"box": {"min": [-30.0, -30.0, 0.0], "max": [30.0, 30.0, PLATE_H + peg_h]},
                "volume_mm3": round(60 * 60 * PLATE_H + count * _peg_volume(peg_h), 4)}
    if name == "mirrored_peg":
        return {"box": {"min": [-20.0, -10.0, 0.0], "max": [20.0, 10.0, PLATE_H + peg_h]},
                "volume_mm3": round(40 * 20 * PLATE_H + 2 * _peg_volume(peg_h), 4)}
    count, pitch = count or 4, 14.0 if pitch is None else pitch
    removed = sum(max(0.0, min(60.0, 11.0 + k * pitch) - (5.0 + k * pitch)) * 6.0 * (BLOCK_H - 4.0)
                  for k in range(count))
    return {"box": {"min": [0.0, 0.0, 0.0], "max": [60.0, 20.0, BLOCK_H]},
            "volume_mm3": round(60 * 20 * BLOCK_H - removed, 4)}


# ---- the captures -------------------------------------------------------------------------------------------------

def peg_row(count=4, pitch=14.0):
    """4 pegs 14 mm apart joined to a 60 by 20 by 4 plate: 4800 + 4 x 216 = 5664 mm3, box to z 10."""
    items = _items((0.0, 0.0, 60.0, 20.0), (8.0, 10.0), PLATE_H, 6.0)
    source = _corners(5.0, 7.0, PLATE_H, 11.0, 13.0, PLATE_H + 6.0)
    items += [_row(source, count, pitch), _combine("join", count, 216.0, 4800.0, 4800.0 + 216.0 * count)]
    found = expected("peg_row", count, pitch)
    made = _made(items, (found["box"]["min"], found["box"]["max"]), found["volume_mm3"],
                 "A 60 by 20 by 4 plate; a 6 mm square peg body patterned %d times %g mm apart along X and joined to "
                 "the plate by one Combine." % (count, pitch))
    sized(made, 3, "side_one.distance", "peg_h", 6.0)
    sized(made, 4, "quantity_one", "count", count, unit="")
    return sized(made, 4, "distance_one", "pitch", pitch)


def peg_ring(count=6):
    """6 pegs round the Z axis at radius 20 joined to a 60 by 60 by 4 plate: 14400 + 6 x 216 = 15696 mm3."""
    items = _items((-30.0, -30.0, 30.0, 30.0), (20.0, 0.0), PLATE_H, 6.0)
    source = _corners(17.0, -3.0, PLATE_H, 23.0, 3.0, PLATE_H + 6.0)
    moves = [(_turn(k * 360.0 / count), [0.0, 0.0, 0.0]) for k in range(1, count)]
    elements = [{"id": k, "suppressed": False, "frame": _frame(_turn(k * 360.0 / count), [0.0, 0.0, 0.0])}
                for k in range(count)]
    items += [_pattern_item("CircularPatternFeature", source, moves, {
        "axis": {"point": [0.0, 0.0, 0.0], "dir": [0.0, 0.0, 1.0], "origin": True}, "quantity": count,
        "total_angle_deg": 360.0, "symmetric": False, "elements": elements}),
        _combine("join", count, 216.0, 14400.0, 14400.0 + 216.0 * count)]
    found = expected("peg_ring", count)
    made = _made(items, (found["box"]["min"], found["box"]["max"]), found["volume_mm3"],
                 "A 60 by 60 by 4 plate round the origin; a 6 mm square peg body at radius 20 patterned %d times "
                 "round the Z axis and joined to the plate by one Combine." % count)
    sized(made, 3, "side_one.distance", "peg_h", 6.0)
    return sized(made, 4, "quantity", "count", count, unit="")


def mirrored_peg():
    """A peg at (-12, 0) and its mirror image across the YZ plane joined to a 40 by 20 by 4 plate: 3200 + 2 x 216 =
    3632 mm3."""
    items = _items((-20.0, -10.0, 20.0, 10.0), (-12.0, 0.0), PLATE_H, 6.0)
    source = _corners(-15.0, -3.0, PLATE_H, -9.0, 3.0, PLATE_H + 6.0)
    image = [[-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    items += [_pattern_item("MirrorFeature", source, [(image, [0.0, 0.0, 0.0])], {
        "combine": False, "plane": {"point": [0.0, 0.0, 0.0], "normal": [1.0, 0.0, 0.0], "origin": True}}),
        _combine("join", 2, 216.0, 3200.0, 3632.0)]
    found = expected("mirrored_peg")
    made = _made(items, (found["box"]["min"], found["box"]["max"]), found["volume_mm3"],
                 "A 40 by 20 by 4 plate round the origin; a 6 mm square peg body at (-12, 0), mirrored across the YZ "
                 "plane as a separate body, and both joined to the plate by one Combine.")
    return sized(made, 3, "side_one.distance", "peg_h", 6.0)


def cutter_row(count=4, pitch=14.0):
    """4 cutters 14 mm apart cut from a 60 by 20 by 10 block, each a pocket 6 by 6 by 6: 12000 - 4 x 216 = 11136
    mm3."""
    items = _items((0.0, 0.0, 60.0, 20.0), (8.0, 10.0), 4.0, CUTTER_H, BLOCK_H)
    source = _corners(5.0, 7.0, 4.0, 11.0, 13.0, 4.0 + CUTTER_H)
    found = expected("cutter_row", count, pitch)
    items += [_row(source, count, pitch), _combine("cut", count, 360.0, 12000.0, found["volume_mm3"])]
    made = _made(items, (found["box"]["min"], found["box"]["max"]), found["volume_mm3"],
                 "A 60 by 20 by 10 block; a 6 mm square cutter body from z 4 to 14 patterned %d times %g mm apart "
                 "along X and cut from the block by one Combine." % (count, pitch))
    sized(made, 4, "quantity_one", "count", count, unit="")
    return sized(made, 4, "distance_one", "pitch", pitch)


BUILDERS = {"peg_row": peg_row, "peg_ring": peg_ring, "mirrored_peg": mirrored_peg, "cutter_row": cutter_row}


if __name__ == "__main__":
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        json.dump(BUILDERS[sys.argv[1]](), out, indent=1)
