"""Captures of a body made by Copy and Paste, moved and taken by a Combine, for the Orca tests and the live check:

    python3 -m tests.orca_pastes <name> <capture.json>
    python3 scripts/orca_live_check.py write <capture.json> <out.3mf>

Body1 is the exported body. Body2 is a 6 by 6 mm square body (Extrude2) whose height is the user parameter of the
capture. CopyPaste1 pastes Body2 in place as Body3, Move1 carries Body3 20 mm along X, and Combine1 takes Body2 and
Body3. `expected` gives the box and volume at other values of the parameter (the `--set` values of the live check).

- `pasted_peg`: a 40 by 20 by 4 plate; a peg at (8, 10) on its top face (z 4), `peg_h` (6) high. Both pegs are
  joined to the plate: 3200 + 2 x 36 x `peg_h`.
- `pasted_cutter`: a 40 by 20 by 10 block; a cutter at (8, 10) from z -2, `cut_h` (8) high. Both cutters are cut from
  the block, each a pocket from the bottom face 6 deep: 8000 - 2 x 36 x (`cut_h` - 2).
"""
import json
import sys

from tests import context  # noqa: F401
from tests.orca_extents import UP, at, capture, extrude, profile, rect, side, sketch_item
from tests.orca_sized import sized

HALF = 3.0
SHIFT = 20.0
PEG_AT = (8.0, 10.0)
B1 = {"token": "t1", "name": "Body1"}
B2 = {"token": "t2", "name": "Body2"}
B3 = {"token": "t3", "name": "Body3"}
PLATE, PEG, PASTE, MOVE, COMBINE = 1, 3, 4, 5, 6


def corners(x0, y0, z0, x1, y1, z1):
    return [[x, y, z] for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]


def shifted(points, offset):
    return [[p[i] + offset[i] for i in range(3)] for p in points]


def body_items(size, height, low, tall):
    """The plate or block (Extrude1, Body1, from z 0 up `height`) and the square body (Extrude2, Body2, from z `low`
    up `tall`)."""
    x, y = PEG_AT
    peg = extrude(PEG, "Extrude2", [profile("Sketch2", at(low), rect(x - HALF, y - HALF, x + HALF, y + HALF))],
                  side_one=side(tall), end_offset=tall)
    peg["bodies_after"] = [dict(B2)]
    return [sketch_item(0, "Sketch1"),
            extrude(PLATE, "Extrude1", [profile("Sketch1", UP, rect(0.0, 0.0, size[0], size[1]))],
                    side_one=side(height), end_offset=height),
            sketch_item(2, "Sketch2"), peg]


def paste_item(points, result_points=None, source=B2, result=B3):
    """CopyPaste1: `source` pasted as `result`, in place unless `result_points` say otherwise."""
    return {"index": PASTE, "name": "CopyPaste1", "type": "CopyPasteBody", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [dict(result)],
            "data": {"sources": [dict(source, points=points)],
                     "result_bodies": [dict(result, points=result_points or points)]}}


def move_item(points, offset, body=B3, index=MOVE):
    """Move1: `body` carried by `offset` along the axes."""
    return {"index": index, "name": "Move1", "type": "MoveFeature", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [dict(body)],
            "data": {"input_kind": "bodies", "bodies": [dict(body)], "move_type": "translateXYZ",
                     "points_before": [points], "points_after": [shifted(points, offset)],
                     "translate": list(offset), "is_design_space": False, "params": {}}}


def combine_item(operation, tool_volume, before, after, tools=(B2, B3), index=COMBINE):
    return {"index": index, "name": "Combine1", "type": "CombineFeature", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [dict(B1)],
            "data": {"target": dict(B1), "tools": [dict(t, volume=tool_volume) for t in tools],
                     "operation": operation, "keep_tools": False, "volume_before": before, "volume_after": after}}


def expected(name, value=None):
    """`{box, volume_mm3}` of the builder `name` with its parameter at `value` (the builder's default when None)."""
    if name == "pasted_peg":
        peg_h = 6.0 if value is None else value
        return {"box": {"min": [0.0, 0.0, 0.0], "max": [40.0, 20.0, 4.0 + peg_h]},
                "volume_mm3": round(3200.0 + 2 * 36.0 * peg_h, 4)}
    cut_h = 8.0 if value is None else value
    depth = max(0.0, min(10.0, cut_h - 2.0))
    return {"box": {"min": [0.0, 0.0, 0.0], "max": [40.0, 20.0, 10.0]},
            "volume_mm3": round(8000.0 - 2 * 36.0 * depth, 4)}


def _made(items, name, comment):
    found = expected(name)
    made = capture(items, (found["box"]["min"], found["box"]["max"]), found["volume_mm3"])
    made["_comment"] = comment
    return made


def pasted_peg():
    """A peg pasted, moved 20 mm along X and joined to the plate with the original: 3200 + 2 x 216 = 3632 mm3."""
    x, y = PEG_AT
    points = corners(x - HALF, y - HALF, 4.0, x + HALF, y + HALF, 10.0)
    items = body_items((40.0, 20.0), 4.0, 4.0, 6.0)
    items += [paste_item(points), move_item(points, [SHIFT, 0.0, 0.0]),
              combine_item("join", 216.0, 3200.0, 3632.0)]
    made = _made(items, "pasted_peg", "A 40 by 20 by 4 plate; a 6 mm square peg body on its top face, copied and "
                 "pasted, the copy moved 20 mm along X, and both pegs joined to the plate by one Combine.")
    return sized(made, PEG, "side_one.distance", "peg_h", 6.0)


def pasted_cutter():
    """A cutter pasted, moved 20 mm along X and cut from the block with the original, two pockets 6 deep from the
    bottom face: 8000 - 2 x 216 = 7568 mm3."""
    x, y = PEG_AT
    points = corners(x - HALF, y - HALF, -2.0, x + HALF, y + HALF, 6.0)
    items = body_items((40.0, 20.0), 10.0, -2.0, 8.0)
    found = expected("pasted_cutter")
    items += [paste_item(points), move_item(points, [SHIFT, 0.0, 0.0]),
              combine_item("cut", 288.0, 8000.0, found["volume_mm3"])]
    made = _made(items, "pasted_cutter", "A 40 by 20 by 10 block; a 6 mm square cutter body from z -2, 8 high, copied "
                 "and pasted, the copy moved 20 mm along X, and both cutters cut from the block by one Combine.")
    return sized(made, PEG, "side_one.distance", "cut_h", 8.0)


BUILDERS = {"pasted_peg": pasted_peg, "pasted_cutter": pasted_cutter}


if __name__ == "__main__":
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        json.dump(BUILDERS[sys.argv[1]](), out, indent=1)
