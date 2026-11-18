"""Captures of sketch text on a plate, extruded or embossed, for the Orca tests and the live check
(`scripts/orca_live_check.py write <file>` with a capture these write, or the saved ones in
tests/fixtures/captures: `orca_text_raised`, `orca_text_cut`, `orca_text_emboss`, `orca_text_emboss_sunk`).

The plate is 60 by 20 by 2 from (-30, -10, 0). The text is two letters on the plate's top (z 2): an "L" drawn as a
six sided outline (area 28) and an "O" drawn as a square ring (area 100 less a hole of 36). The depth is the user
parameter `text_depth`; each volume is the plate's 2400 plus or less the letters' 92 times the depth."""
from tests.orca_extents import B1, UP, at, capture, extrude, model, param, profile, rect, side, sketch_item
from tests.orca_outline import lines
from tests.probe_helpers import user

PLATE = 60.0 * 20.0 * 2.0
L_OUTLINE = [(-20, -5), (-14, -5), (-14, -3), (-18, -3), (-18, 5), (-20, 5)]
O_OUTER = [(-5, -5), (5, -5), (5, 5), (-5, 5)]
O_HOLE = [(-3, -3), (3, -3), (3, 3), (-3, 3)]
AREAS = [28.0, 64.0]
TEXT_AREA = sum(AREAS)
PLATE_BOX = {"min": [-30.0, -10.0, 0.0], "max": [30.0, 10.0, 2.0]}


def text_profile(outer, holes=(), frame=None):
    """A text profile record as the reader writes one per letter."""
    found = profile("Sketch2", frame or at(2.0), lines(outer), [lines(h) for h in holes])
    found.update(text=True, sketch_token="s2", space="sketch", text_params=["d9"])
    return found


def letters(frame=None):
    return [text_profile(L_OUTLINE, frame=frame), text_profile(O_OUTER, [O_HOLE], frame=frame)]


def _plate_items():
    return [sketch_item(0, "Sketch1"),
            extrude(1, "Plate", [profile("Sketch1", UP, rect(-30, -10, 30, 10))], side_one=side(2.0), end_offset=2.0,
                    target_box_before=None),
            sketch_item(2, "Sketch2")]


def _depth_parameters(depth):
    users = [user("text_depth", "%g mm" % abs(depth), abs(depth))]
    models = [model("d2", "text_depth" if depth > 0 else "-text_depth", depth),
              model("d9", "5 mm", 5.0, kind="sketchText")]
    return users, models


def _box(top):
    return (-30.0, -10.0, 0.0), (30.0, 10.0, top)


def text_extrude(depth=1.0, operation="join", profiles=None, **extra):
    """The plate, then the letters extruded `depth` from the top (down for a negative depth) with `operation`."""
    users, models = _depth_parameters(depth)
    data = dict(side_one=side(depth), end_offset=depth, target_box_before=PLATE_BOX,
                params={"side_one.distance": param("d2", models[0]["expression"], depth)})
    data.update(extra)
    items = _plate_items() + [extrude(3, "Text", profiles if profiles is not None else letters(),
                                      operation=operation, **data)]
    raised = depth > 0
    volume = PLATE + TEXT_AREA * depth if operation == "join" else PLATE - TEXT_AREA * abs(depth)
    return capture(items, _box(2.0 + depth if raised else 2.0), volume, users, models)


def text_emboss(depth=1.0, **extra):
    """The plate, then the letters embossed on its top face by `depth` (raised, or sunk for a negative depth)."""
    users, models = _depth_parameters(depth)
    data = {"profiles": letters(), "areas": list(AREAS),
            "faces": [{"entity_type": "BRepFace", "surface": "Plane",
                       "plane": {"point": [0.0, 0.0, 2.0], "normal": [0.0, 0.0, 1.0]}, "outward": [0.0, 0.0, 1.0],
                       "face_point": [0.0, 8.0, 2.0]}],
            "tangent_chain": False, "depth": depth, "offset_x": 0.0, "offset_y": 0.0, "rotation_deg": 0.0,
            "participants": [dict(B1)], "target_box_before": PLATE_BOX, "volume_before": PLATE,
            "volume_after": PLATE + TEXT_AREA * depth, "end_offset": depth, "end_area": TEXT_AREA,
            "params": {"depth": param("d2", models[0]["expression"], depth)}}
    data.update(extra)
    item = {"index": 3, "name": "Emboss1", "type": "EmbossFeature", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [dict(B1)], "data": data}
    return capture(_plate_items() + [item], _box(2.0 + max(depth, 0.0)), PLATE + TEXT_AREA * depth, users, models)


SAVED = {
    "orca_text_raised": (lambda: text_extrude(1.0), "raised 1 mm by an extrude (join)"),
    "orca_text_cut": (lambda: text_extrude(-0.6, operation="cut"), "cut 0.6 mm deep by an extrude"),
    "orca_text_emboss": (lambda: text_emboss(1.0), "raised 1 mm by an emboss"),
    "orca_text_emboss_sunk": (lambda: text_emboss(-0.6), "sunk 0.6 mm by an emboss"),
}


def save(folder):
    """Write the captures of `SAVED` into `folder` (`python3 -m tests.orca_text` writes tests/fixtures/captures)."""
    import json
    import os
    for name, (make, what) in SAVED.items():
        found = make()
        comment = ("Synthetic, written by tests/orca_text.py: a 60 x 20 x 2 plate with the letters L (six sided) and O "
                   "(a square ring) of sketch text on its top, %s. Volume %g mm3."
                   % (what, found["target"]["volume_mm3"]))
        with open(os.path.join(folder, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(dict({"_comment": comment}, **found), f, indent=1)
            f.write("\n")


if __name__ == "__main__":
    import os
    save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "captures"))
