"""Planes, axes and faces of the part that an Orca step writes as numbers: every size that may move one is marked,
never unused or following (`orca_translate/kept_refs.py`, `design_model.reach.reference_sizes`)."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture, placed_hole_pattern, second_extrude, sized, split_by_plane, table_of
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


def tapped(capture):
    """`capture` with its hole tapped M12 through all, the thread modeled over the whole hole."""
    capture["items"][-1]["data"].update(
        tap_type="tapped", thread_modeled=True,
        side_cylinders=[{"origin": [-20, 0, 0], "axis": [0, 0, 1], "radius": 10.106 / 2}],
        thread={"thread_type": "ISO Metric profile", "designation": "M12x1.75", "internal": True,
                "right_hand": True, "pitch": 1.75, "major_diameter": 12.0, "minor_diameter": 10.106,
                "angle_deg": None, "full_length": True, "depth": None})
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

    def test_a_pattern_along_an_edge_of_a_plain_box_leaves_the_box_sizes_as_they_were_in_both_outputs(self):
        def outcomes(capture):
            table = table_of(capture, BOX_TICKED)
            orca = {p["name"]: (p["outcome"], p["reasons"]) for p in translate(capture, table).parameters}
            recipe = translator.translate(capture, size_table=table)
            return orca, recipe.loose, recipe.fixed
        plain = placed_hole_pattern()
        # The hole's sketch sits on the XY plane, so no size moves its plane.
        next(i for i in plain["items"] if i["type"] == "HoleFeature")["data"]["reference"] = {
            "kind": "constructionPlane", "origin": True}
        along = copy.deepcopy(plain)
        # The pattern runs along y, as the box's bottom edge at x = 40 does.
        along["items"][-1]["data"]["direction_one_place"] = {"own": True, "entity_type": "BRepEdge",
                                                             "edge_points": [[40, 0, 0]]}
        found = outcomes(along)
        self.assertEqual(found, outcomes(plain))
        self.assertEqual({found[0][n][0] for n in ("cube_mm", "depth_mm", "height_mm")}, {VARIABLE})

    def test_a_tapped_hole_through_all_marks_what_moves_its_ends_but_not_its_own_place(self):
        plain = {p["name"]: p for p in run(box_hole(), BOX_TICKED).parameters}
        found = {p["name"]: p for p in run(tapped(box_hole()), BOX_TICKED).parameters}
        self.assertEqual(found["pipe_offset_mm"]["outcome"], VARIABLE)
        # The plate's height moves the face the hole comes out at: one reason more than for a plain hole.
        self.assertEqual(len(found["height_mm"]["reasons"]), len(plain["height_mm"]["reasons"]) + 1)
        self.assertEqual(found["height_mm"]["outcome"], PARTLY)
        # The hole runs from one end face of the box to the other: the box's width moves neither.
        self.assertEqual(found["cube_mm"]["reasons"], plain["cube_mm"]["reasons"])

    def test_a_tapped_hole_through_a_stepped_part_marks_what_places_it(self):
        # A boss on top over x 0..20: `pipe_offset_mm` can move the hole under it, where the part is thicker than the
        # thread Orca keeps.
        capture = second_extrude(tapped(box_hole()), (0, -10, 20, 10), 32, 42)
        found = {p["name"]: p for p in run(capture, BOX_TICKED).parameters}
        self.assertEqual(found["pipe_offset_mm"]["outcome"], PARTLY)


if __name__ == "__main__":
    unittest.main()
