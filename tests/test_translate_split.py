"""Split Body: the piece the part comes from stays, the other side is removed by a box or by the tool body."""

import unittest

from tests import context  # noqa: F401
from tests.test_translate_sized import table_of
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of, stopped, verdict_of

from lib.export_plan.body_scope import body_items
from lib.sketch_values.motion import Motion
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

    def test_pieces_of_a_curved_body_may_add_up_to_a_little_more_than_it(self):
        pieces = [piece(PLATE, LEFT, 2000.1), piece(OTHER, RIGHT, 6000.2)]
        self.assertEqual(verdict_of(translate(plate_split(OTHER, pieces=pieces)), 2)["verdict"], "translated")

    def test_the_body_that_keeps_its_name_removes_the_other_side(self):
        result = translate(plate_split(PLATE))
        self.assertEqual(box_cut(result)[1]["normal"], [1.0, 0.0, 0.0])

    def test_the_box_reaches_well_past_the_part(self):
        tool = steps_of(translate(plate_split(OTHER)).recipe, "toolBody")[0]["features"][0]
        self.assertGreater(tool["distance"], 4 * 40)
        self.assertGreater(tool["sketch"]["outer"]["width"], 4 * 40)

    def test_the_box_grows_with_the_size_ranges(self):
        capture = plate_split(OTHER)
        capture["parameters"] = load_capture("filter_tray_sized")["parameters"]
        table = table_of(capture, ["wall_mm"])
        size = table.sizes[table.size_name("wall_mm")]
        plain, sized = (steps_of(r.recipe, "toolBody")[0]["features"][0]["distance"]
                        for r in (translate(capture), translate(capture, size_table=table)))
        self.assertAlmostEqual(sized / plain, size["max"] / size["value"], places=3)

    def test_a_split_along_a_plane_offset_by_a_size_follows_that_size(self):
        plane = {"entity_type": "ConstructionPlane", "token": "cp1", "made_by": 1, "point": [10, 0, 0],
                 "normal": [1, 0, 0], "definition": "ConstructionPlaneOffsetDefinition",
                 "built_on": [{"entity_type": "ConstructionPlane", "token": "yz", "origin": True, "normal": [1, 0, 0]}]}
        capture = plate_split(OTHER, tool={"kind": "plane", "plane": plane})
        made = {"kind": "constructionPlane", "token": "cp1", "name": "Plane1"}
        capture["parameters"] = {
            "user": [{"name": "cut_mm", "expression": "10 mm", "value": 1.0, "unit": "mm", "kind": "length",
                      "comment": "", "dependency_parameters": [], "dependent_parameters": ["d9"]}],
            # Fusion also gives an offset plane a fixed extra offset.
            "model": [{"name": "d9", "expression": "cut_mm", "value": 1.0, "unit": "mm", "role": "AlongDistance",
                       "dependency_parameters": ["cut_mm"], "created_by": made},
                      {"name": "d10", "expression": "0.00 mm", "value": 0.0, "unit": "mm", "role": "ExtraOffset",
                       "dependency_parameters": [], "created_by": made}]}
        result = translate(capture, size_table=table_of(capture, ["cut_mm"]), motion=Motion())
        self.assertEqual(box_cut(result)[1]["origin"][0], {"expr": "cut_mm"})
        self.assertEqual((result.loose, result.fixed, result.dropped), ([], [], []))

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

    def test_steps_before_the_split_read_the_measures_of_the_body_they_build(self):
        capture = plate_split(OTHER)
        wall = {"token": "f1", "point": [0, 10, 5], "box": {"min": [0, 0, 0], "max": [0, 20, 10]}}
        draft = {"index": 2, "name": "Draft1", "type": "DraftFeature", "suppressed": False, "health": "ok",
                 "message": "", "in_target_component": True, "bodies_after": [PLATE], "target_changed": None,
                 "body_states": {"t1": {"box_before": WHOLE, "volume_before": 8000.0, "volume_after": 7950.0}},
                 "data": {"faces": [wall], "plane": {"point": [0, 0, 0], "normal": [0, 0, 1]}, "two_angles": False,
                          "angle_deg": 3.0, "volume_before": None, "volume_after": None}}
        capture["items"][2:2] = [draft]
        capture["items"][3]["index"] = 3
        result = translate(capture)
        self.assertEqual(result.gaps, [])
        self.assertEqual(len(steps_of(result.recipe, "draft")), 1)

    def test_the_steps_of_the_body_it_came_from_are_in_the_export_scope_up_to_the_split(self):
        later = {"index": 3, "name": "Extrude9", "type": "ExtrudeFeature", "suppressed": False, "health": "ok",
                 "message": "", "in_target_component": True, "bodies_after": [PLATE], "data": {"operation": "join"}}
        self.assertEqual([item["index"] for item in body_items(plate_split(OTHER, after=[later]))], [1, 2])


class SplitStopTest(unittest.TestCase):
    def test_each_split_the_copy_cannot_show_stops_it(self):
        straddles = [piece(PLATE, box((0, 0, 0), (12, 20, 10)), 2000.0), piece(OTHER, RIGHT, 6000.0)]
        three = [piece(PLATE, LEFT, 2000.0), piece(OTHER, box((10, 0, 0), (40, 10, 10)), 3000.0),
                 piece({"token": "t4", "name": "Body4"}, box((10, 10, 0), (40, 20, 10)), 3000.0)]
        short = [piece(PLATE, LEFT, 2000.0), piece(OTHER, RIGHT, 5000.0)]
        curved = {"kind": "surface", "type": "Cylinder"}
        fillet = {"index": 3, "name": "Fillet1", "type": "FilletFeature", "suppressed": False, "health": "ok",
                  "message": "", "in_target_component": True, "bodies_after": [PLATE, OTHER], "data": {}}
        cases = {
            "a piece on both sides": (plate_split(OTHER, pieces=straddles), "both sides"),
            "pieces that do not add up": (plate_split(OTHER, pieces=short), "add up"),
            "two pieces on the part's side": (plate_split(OTHER, pieces=three), "more than one piece"),
            "a curved tool": (plate_split(OTHER, tool=curved), "curved"),
            "the other piece used later": (plate_split(PLATE, after=[fillet]), "Fillet1"),
            "the piece that kept the name used later": (plate_split(OTHER, after=[fillet]), "Fillet1"),
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


class SplitToolTest(unittest.TestCase):
    def test_a_combine_tool_that_a_split_made_is_built_from_the_body_it_came_from(self):
        capture = load_capture("combine_cut")
        combine = capture["items"][4]
        cylinder, top = {"token": "t2", "name": "Body2"}, {"token": "t5", "name": "Body5"}
        split = split_item(4, {"kind": "plane", "plane": {"point": [0, 0, 5], "normal": [0, 0, 1]}},
                           [piece(cylinder, box((15, 5, -2), (25, 15, 5)), 549.8),
                            piece(top, box((15, 5, 5), (25, 15, 12)), 549.8)],
                           bodies=[piece(cylinder, box((15, 5, -2), (25, 15, 12)), 1099.6)])
        combine = dict(combine, index=5, data=dict(combine["data"], tools=[top]))
        capture["items"][4:] = [split, combine]
        result = translate(capture)
        self.assertEqual(result.gaps, [])
        tool = steps_of(result.recipe, "toolBody")[0]
        self.assertEqual([step["kind"] for step in tool["features"]], ["extrude", "toolBody"])
        self.assertEqual(tool["features"][1]["features"][0]["sketch"]["on"]["normal"], [0.0, 0.0, -1.0])


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


