"""Split Body: the piece the part comes from stays, the other side is removed by a box or by the tool body."""

import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of, stopped, verdict_of

from lib.export_plan.body_scope import body_items
from lib.translator import translate

PLATE = {"token": "t1", "name": "Body1"}
OTHER = {"token": "t2", "name": "Body2"}
TOOL = {"token": "t3", "name": "Body3"}


def box(lo, hi):
    return {"min": list(lo), "max": list(hi)}


LEFT, RIGHT = box((0, 0, 0), (10, 20, 10)), box((10, 0, 0), (40, 20, 10))
WHOLE = box((0, 0, 0), (40, 20, 10))


def piece(body, at, volume, **more):
    return dict(body, box=at, volume=volume, **more)


def split_item(index, tool, pieces, bodies=None, name="Split1"):
    bodies = bodies or [piece(PLATE, WHOLE, 8000.0)]
    return {"index": index, "name": name, "type": "SplitBodyFeature", "suppressed": False, "health": "ok",
            "message": "", "in_target_component": True,
            "bodies_before": [{"token": b["token"], "name": b["name"]} for b in bodies],
            "bodies_after": [{"token": p["token"], "name": p["name"]} for p in pieces], "target_changed": True,
            "data": {"tool": tool, "extended": True, "bodies": bodies, "pieces": pieces}}


PLANE_X10 = {"kind": "plane", "plane": {"point": [10, 0, 0], "normal": [1, 0, 0]}}


def plate_split(target, tool=PLANE_X10, pieces=None, after=()):
    """The plate of combine_cut (40 x 20 x 10), split at x = 10 into Body1 (left) and Body2 (right)."""
    capture = load_capture("combine_cut")
    capture["items"] = capture["items"][:2]
    pieces = pieces or [piece(PLATE, LEFT, 2000.0), piece(OTHER, RIGHT, 6000.0)]
    capture["items"].append(split_item(2, tool, pieces))
    capture["items"] += list(after)
    capture["target"] = dict(target, box=next(p["box"] for p in pieces if p["token"] == target["token"]),
                             volume_mm3=next(p["volume"] for p in pieces if p["token"] == target["token"]))
    return capture


def box_cut(result):
    tool = steps_of(result.recipe, "toolBody")[0]
    return tool["combine"], tool["features"][0]["sketch"]["on"]


class SplitByPlaneTest(unittest.TestCase):
    def test_a_piece_split_off_carries_the_steps_of_the_body_it_came_from(self):
        result = translate(plate_split(OTHER))
        self.assertEqual(verdict_of(result, 1)["verdict"], "translated")
        combine, on = box_cut(result)
        self.assertEqual((combine, on["origin"], on["normal"]), ("cut", [10.0, 10.0, 5.0], [-1.0, 0.0, 0.0]))
        assert_schema_ok(self, result.recipe)

    def test_the_body_that_keeps_its_name_removes_the_other_side(self):
        result = translate(plate_split(PLATE))
        self.assertEqual(box_cut(result)[1]["normal"], [1.0, 0.0, 0.0])

    def test_the_box_reaches_well_past_the_part(self):
        tool = steps_of(translate(plate_split(OTHER)).recipe, "toolBody")[0]["features"][0]
        self.assertGreater(tool["distance"], 4 * 40)
        self.assertGreater(tool["sketch"]["outer"]["width"], 4 * 40)

    def test_a_split_of_a_split_off_piece_follows_both(self):
        quarter = {"token": "t4", "name": "Body4"}
        low, high = box((10, 0, 0), (40, 5, 10)), box((10, 5, 0), (40, 20, 10))
        second = split_item(3, {"kind": "plane", "plane": {"point": [0, 5, 0], "normal": [0, 1, 0]}},
                            [piece(OTHER, low, 1500.0), piece(quarter, high, 4500.0)],
                            bodies=[piece(OTHER, RIGHT, 6000.0)], name="Split2")
        capture = plate_split(OTHER, after=[second])
        capture["target"] = dict(quarter, box=high, volume_mm3=4500.0)
        result = translate(capture)
        normals = [t["features"][0]["sketch"]["on"]["normal"] for t in steps_of(result.recipe, "toolBody")]
        self.assertEqual(normals, [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])

    def test_the_steps_of_the_body_it_came_from_are_in_the_export_scope(self):
        self.assertEqual([item["index"] for item in body_items(plate_split(OTHER))], [1, 2])


class SplitStopTest(unittest.TestCase):
    def test_each_split_the_copy_cannot_show_stops_it(self):
        straddles = [piece(PLATE, box((0, 0, 0), (12, 20, 10)), 2000.0), piece(OTHER, RIGHT, 6000.0)]
        short = [piece(PLATE, LEFT, 2000.0), piece(OTHER, RIGHT, 5000.0)]
        curved = {"kind": "surface", "type": "Cylinder"}
        fillet = {"index": 3, "name": "Fillet1", "type": "FilletFeature", "suppressed": False, "health": "ok",
                  "message": "", "in_target_component": True, "bodies_after": [PLATE, OTHER], "data": {}}
        cases = {
            "a piece on both sides": (plate_split(OTHER, pieces=straddles), "both sides"),
            "pieces that do not add up": (plate_split(OTHER, pieces=short), "add up"),
            "a curved tool": (plate_split(OTHER, tool=curved), "curved"),
            "the other piece used later": (plate_split(PLATE, after=[fillet]), "Fillet1"),
        }
        for label, (capture, words) in cases.items():
            with self.subTest(label):
                result = translate(capture)
                self.assertEqual(stopped(result)["index"], 2)
                self.assertIn(words, stopped(result)["reason"])

    def test_a_split_read_by_an_older_export_names_what_is_missing(self):
        capture = plate_split(PLATE)
        capture["items"][2]["data"] = {}
        self.assertIn("was not read", stopped(translate(capture))["reason"])


class SplitByBodyTest(unittest.TestCase):
    def capture(self, kept_inside):
        """The plate split by the cylinder of combine_cut: the piece inside the cylinder and the plate around it."""
        capture = load_capture("combine_cut")
        capture["items"] = capture["items"][:4]
        hole, core = box((0, 0, 0), (40, 20, 10)), box((15, 5, 0), (25, 15, 10))
        pieces = [piece(PLATE, hole, 7214.6, inside=False), piece(OTHER, core, 785.4, inside=True)]
        tool = {"kind": "body", "body": dict(TOOL, token="t2", name="Body2", volume=1099.6), "solid": True}
        pieces[1] = dict(pieces[1], token="t5", name="Body5")
        capture["items"].append(split_item(4, tool, pieces))
        kept = pieces[1] if kept_inside else pieces[0]
        capture["target"] = {"token": kept["token"], "name": kept["name"], "box": kept["box"],
                             "volume_mm3": kept["volume"]}
        return capture

    def test_the_piece_outside_the_tool_is_a_cut_and_the_piece_inside_an_intersect(self):
        for inside, combine in ((False, "cut"), (True, "intersect")):
            with self.subTest(combine):
                result = translate(self.capture(inside))
                self.assertIsNone(stopped(result))
                self.assertEqual(steps_of(result.recipe, "extrude")[-1]["combine"], combine)

    def test_pieces_the_reader_could_not_place_stop_the_copy(self):
        capture = self.capture(False)
        capture["items"][4]["data"]["pieces"][1]["inside"] = None
        self.assertIn("inside its tool body", stopped(translate(capture))["reason"])


if __name__ == "__main__":
    unittest.main()


