"""Planes, axes and faces of the part that an Orca step writes as numbers: every size that may move one is marked,
never unused or following (`orca_translate/kept_refs.py`, `design_model.reach.reference_sizes`)."""
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture, sized, split_by_plane, table_of
from tests.probe_helpers import model, user
from tests.test_orca_holes import BOX_TICKED, box_hole, run
from tests.test_orca_threads import rod

from lib import translator
from lib.orca_translate import FIXED, PARTLY, UNUSED, VARIABLE, translate

ORIGIN = {"origin": True}


def driven_by(capture, name, kind, token="", sketch=""):
    """`capture` with a user parameter `name` that only a construction plane or axis (`kind`, `token`) or a sketch
    dimension (`sketch`) reads."""
    params = capture.setdefault("parameters", {})
    params.setdefault("user", []).append(user(name, "5 mm", 5))
    params.setdefault("model", []).append(model("d_" + name, name, 5, kind=kind, token=token, sketch=sketch))
    return capture


def construction(record, kind, token="c1"):
    """`record` (a plane or an axis) as construction geometry made from parameters on an origin plane."""
    return dict(record, entity_type=kind, token=token, definition="Offset", built_on=[ORIGIN])


def outcome(capture, name):
    result = translate(capture, table_of(capture))
    found = next(p for p in result.parameters if p["name"] == name)
    return found["outcome"], result


class KeptPlaceTest(unittest.TestCase):
    def test_a_split_plane_offset_by_a_size_marks_that_size(self):
        capture = split_by_plane()
        tool = capture["items"][2]["data"]["tool"]
        tool["plane"] = construction(tool["plane"], "ConstructionPlane")
        found, result = outcome(driven_by(capture, "cut_at", "constructionPlane", "c1"), "cut_at")
        self.assertEqual(found, FIXED)
        self.assertEqual(next(i for i in result.items if i["name"] == "Split1")["verdict"], "copied")

    def test_a_split_on_an_origin_plane_marks_nothing(self):
        capture = split_by_plane()
        capture["items"][2]["data"]["tool"]["plane"].update(ORIGIN)
        self.assertEqual(outcome(driven_by(capture, "cut_at", "constructionPlane", "c1"), "cut_at")[0], UNUSED)

    def test_a_mirror_plane_offset_by_a_size_marks_that_size(self):
        capture = fixture("mirror_features")
        data = capture["items"][4]["data"]
        data["plane"] = construction(data["plane"], "ConstructionPlane")
        self.assertEqual(outcome(driven_by(capture, "gap", "constructionPlane", "c1"), "gap")[0], FIXED)

    def test_an_axis_a_pattern_a_revolve_or_a_move_turns_about_marks_its_sizes(self):
        for name, index in (("cpattern_part", 4), ("revolve_quarter", 1), ("move_rotate_sized", 4)):
            with self.subTest(name):
                capture = fixture(name)
                data = capture["items"][index]["data"]
                data["axis"] = construction({k: v for k, v in data["axis"].items() if k != "origin"},
                                            "ConstructionAxis")
                found, result = outcome(driven_by(capture, "axis_at", "constructionAxis", "c1"), "axis_at")
                self.assertEqual(found, FIXED)
                self.assertEqual(result.items[index]["verdict"], "copied")

    def test_a_pattern_along_a_sketch_line_marks_the_sizes_of_that_sketch(self):
        capture = fixture("rpattern_row")
        capture["items"][4]["data"]["direction_one_sketch"] = {"sketch": "Guide", "sketch_token": "g1"}
        self.assertEqual(outcome(driven_by(capture, "slope", "sketchDimension", sketch="Guide"), "slope")[0], FIXED)

    def test_a_thread_marks_the_sizes_that_may_move_or_change_its_face(self):
        capture = sized(rod(), 1, "side_one.distance", "rod_len", 12)
        found, result = outcome(capture, "rod_len")
        self.assertEqual(found, PARTLY)
        self.assertEqual(next(i for i in result.items if i["name"] == "Thread1")["verdict"], "copied")

    def test_a_pattern_along_an_edge_of_the_part_marks_the_sizes_read_before_in_both_outputs(self):
        capture = sized(fixture("rpattern_row"), 1, "side_one.distance", "plate_h", 10)
        capture["items"][4]["data"]["direction_one_place"] = {"own": True, "entity_type": "BRepEdge"}
        self.assertEqual(outcome(capture, "plate_h")[0], PARTLY)
        recipe = translator.translate(capture, size_table=table_of(capture))
        self.assertEqual([size["name"] for size in recipe.loose], ["plate_h"])

    def test_a_tapped_hole_through_all_marks_what_moves_its_ends_but_not_its_own_place(self):
        plain = {p["name"]: p for p in run(box_hole(), BOX_TICKED).parameters}
        capture = box_hole()
        capture["items"][-1]["data"].update(
            tap_type="tapped", thread_modeled=True,
            side_cylinders=[{"origin": [-20, 0, 0], "axis": [0, 0, 1], "radius": 10.106 / 2}],
            thread={"thread_type": "ISO Metric profile", "designation": "M12x1.75", "internal": True,
                    "right_hand": True, "pitch": 1.75, "major_diameter": 12.0, "minor_diameter": 10.106,
                    "angle_deg": None, "full_length": True, "depth": None})
        result = run(capture, BOX_TICKED)
        found = {p["name"]: p for p in result.parameters}
        self.assertEqual(found["pipe_offset_mm"]["outcome"], VARIABLE)
        # The plate's height moves the face the hole comes out at: one reason more than for a plain hole.
        self.assertEqual(len(found["height_mm"]["reasons"]), len(plain["height_mm"]["reasons"]) + 1)
        self.assertEqual(found["height_mm"]["outcome"], PARTLY)


if __name__ == "__main__":
    unittest.main()
