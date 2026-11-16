"""Planes, axes and faces of the part that an Orca step writes as numbers: every size that may move one is marked,
never unused or following (`orca_translate/kept_refs.py`, `design_model.reach.reference_sizes`)."""
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture, sized, split_by_plane, table_of
from tests.probe_helpers import model, user
from tests.test_orca_threads import rod

from lib.orca_translate import FIXED, PARTLY, UNUSED, translate

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


if __name__ == "__main__":
    unittest.main()
