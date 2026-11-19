"""Ribs and webs in the shared layer (`design_model/steps/rib_web.py`): the wall of each line is found from the
settings and from the faces Fusion made, on fixtures saved from Fusion exports of test designs; every case the faces
or the volume do not prove is a problem. Also the chains of curves and the area that bands cover together."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture

from lib.design_model.problem import is_problem
from lib.design_model.steps import rib_web
from lib.geometry.chains import open_chains
from lib.geometry.convex_union import union_area


def data_of(name):
    return copy.deepcopy(load_capture(name)["items"][-1]["data"])


def walls(data):
    return rib_web.walls(data, data.get("target_faces_before"))


class ChainsTest(unittest.TestCase):
    def test_curves_in_any_order_and_direction_make_one_chain_from_a_free_end(self):
        found = open_chains([((1, 0), (2, 0)), ((0, 0), (1, 0)), ((2, 0), (2, 1))])
        self.assertEqual(found, [[(1, False), (0, False), (2, False)]])

    def test_a_curve_against_the_chain_is_reversed_and_separate_chains_stay_apart(self):
        found = open_chains([((0, 0), (1, 0)), ((2, 0), (1, 0)), ((5, 5), (6, 5))])
        self.assertEqual(found, [[(0, False), (1, True)], [(2, False)]])

    def test_a_branch_or_a_closed_chain_gives_none(self):
        self.assertIsNone(open_chains([((0, 0), (1, 0)), ((1, 0), (1, 1)), ((1, 0), (2, 0))]))
        self.assertIsNone(open_chains([((0, 0), (1, 0)), ((1, 0), (1, 1)), ((1, 1), (0, 0))]))


class UnionAreaTest(unittest.TestCase):
    def test_crossing_bands_count_their_shared_square_once_and_touching_ones_add_up(self):
        def square(x0, y0, x1, y1):
            return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        self.assertAlmostEqual(union_area([square(0, 0, 54, 2), square(26, -17, 28, 17)]), 108 + 68 - 4)
        self.assertAlmostEqual(union_area([square(0, 0, 2, 2), square(2, 0, 4, 2)]), 8)


class WallsTest(unittest.TestCase):
    def test_a_web_on_a_plate_is_one_centred_wall_per_line_that_grows_clear_of_the_part(self):
        found = walls(data_of("web_on_plate"))
        self.assertEqual(len(found), 2)
        for wall in found:
            self.assertEqual((wall.side, wall.width, wall.way, wall.length), ("middle", 2.0, 1, 10.0))
            self.assertTrue(wall.clear)
            self.assertFalse(wall.measured)

    def test_a_clear_wall_marks_the_sizes_of_the_part_unless_it_stands_on_its_sketch_face(self):
        # The sketch of the fixture sits on a plane that is not a face of the part: the plate could move into the wall.
        data = data_of("web_on_plate")
        self.assertEqual([names for names, _ in rib_web.marks(data, walls(data)[0], "Web2")], [()])
        for path in data["paths"]:
            path["reference"] = {"kind": "face", "token": "top"}
        (first, _) = walls(data)
        self.assertTrue(first.stands)
        self.assertEqual(rib_web.marks(data, first, "Web2"), [])
        # A face of the part under the sketch that faces the other way does not hold the wall.
        for face in data["target_faces_before"]:
            face["normal"] = [-c for c in face["normal"]]
        self.assertFalse(walls(data)[0].stands)

    def test_a_rib_between_two_walls_is_the_band_of_its_depth_on_one_side_of_the_plane(self):
        (wall,) = walls(data_of("rib_distance_channel"))
        self.assertEqual((wall.width, wall.length), (8.0, 2.0))
        self.assertIn(wall.way, (1, -1))
        self.assertFalse(wall.clear)
        self.assertEqual([names for names, _ in rib_web.marks(data_of("rib_distance_channel"), wall, "Rib1")],
                         [("depth",)])

    def test_a_rib_to_next_in_a_channel_takes_the_depth_its_corners_reach(self):
        (wall,) = walls(data_of("rib_tonext_channel"))
        self.assertAlmostEqual(wall.width, 26.0, places=6)
        self.assertEqual((wall.way, wall.length, wall.measured), (0, 2.0, True))

    def test_a_web_to_next_over_a_flat_floor_is_one_wall_per_line_as_deep_as_the_floor(self):
        found = walls(data_of("web_tonext_grid"))
        self.assertEqual([(w.side, w.length, w.measured) for w in found], [("middle", 17.0, True)] * 3)

    def test_fusion_filling_a_gusset_up_to_the_part_is_not_a_band(self):
        self.assertEqual(walls(data_of("rib_tonext_gusset")), rib_web.NEXT_SHAPE)

    def test_a_band_that_runs_into_the_part_where_fusion_stops_it_is_refused(self):
        self.assertEqual(walls(data_of("rib_into_corner")), rib_web.MEETS_PART)

    def test_a_web_that_fusion_stretched_to_the_walls_is_refused(self):
        self.assertEqual(walls(data_of("web_extended")), rib_web.EXTENDED)

    def test_settings_the_copy_does_not_build_are_problems(self):
        for key, value, problem in (("draft_deg", 2.0, rib_web.DRAFT), ("fillet", 1.0, rib_web.FILLET),
                                    ("draft_deg", None, rib_web.UNREADABLE), ("extent", "other", rib_web.EXTENT),
                                    ("thickness", None, rib_web.UNREADABLE)):
            data = data_of("rib_distance_channel")
            data[key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(walls(data), problem)

    def test_an_arc_in_the_line_or_a_rib_of_two_chains_is_refused(self):
        data = data_of("rib_distance_channel")
        data["path"]["curves"][0]["kind"] = "arc"
        self.assertEqual(walls(data), rib_web.CURVES)
        data = data_of("rib_distance_channel")
        data["paths"] = [data.pop("path")] * 2
        self.assertEqual(walls(data), rib_web.LINES)

    def test_faces_without_corners_or_off_the_wall_give_no_wall(self):
        data = data_of("web_on_plate")
        data["wall_faces"][0]["vertices"] = None
        self.assertEqual(walls(data), rib_web.UNMEASURED)
        data = data_of("web_on_plate")
        for face in data["wall_faces"]:
            face["point"] = [face["point"][0], face["point"][1], face["point"][2] + 30.0]
        self.assertEqual(walls(data), rib_web.NOT_MATCHING)

    def test_a_to_next_wall_needs_its_end_on_a_face_of_the_part(self):
        data = data_of("web_tonext_grid")
        self.assertEqual(rib_web.walls(data, None), rib_web.NEXT_SHAPE)

    def test_a_wall_whose_body_was_not_measured_says_so(self):
        data = data_of("web_on_plate")
        data["volume_after"] = None
        self.assertEqual(walls(data), rib_web.BODY_UNMEASURED)

    def test_a_wall_flush_with_a_side_of_the_part_is_refused_as_flush(self):
        # A side face of the first wall (y = 21) that Fusion merged with a side of the part on that plane: its point
        # and corners lie on the part's face, past the end of the wall.
        data = data_of("web_on_plate")
        side = next(f for f in data["wall_faces"] if f["normal"] == [0.0, 1.0, 0.0] and f["point"][1] == 21.0)
        side["point"] = [2.0, 21.0, 9.0]
        side["vertices"] = [[0.0, 21.0, 4.0], [55.0, 21.0, 4.0], [55.0, 21.0, 14.0], [0.0, 21.0, 14.0]]
        data["target_faces_before"].append({"surface": "Plane", "point": [0.0, 21.0, 2.0], "normal": [0.0, 1.0, 0.0]})
        self.assertEqual(walls(data), rib_web.FLUSH)

    def test_a_to_next_depth_keeps_no_parameter(self):
        data = data_of("web_tonext_grid")
        data["params"]["depth"] = {"name": "d20", "expression": "wd", "value": 17.0}
        built = rib_web.as_extrude(data, walls(data)[0])
        self.assertEqual(set(built["params"]), {"thin.thickness"})

    def test_the_rib_values_go_to_the_paths_of_the_thin_extrude_they_are(self):
        data = data_of("rib_distance_channel")
        (wall,) = walls(data)
        built = rib_web.as_extrude(data, wall)
        self.assertEqual(built["params"]["thin.thickness"]["expression"], "rd")
        self.assertEqual(built["params"]["side_one.distance"]["expression"], "rt")
        self.assertEqual(built["thin_wall"]["decided"], wall.side)
        self.assertEqual(built["side_one"]["direction"], wall.way)
        web = data_of("web_on_plate")
        built = rib_web.as_extrude(web, walls(web)[0])
        self.assertEqual((built["params"]["thin.thickness"]["expression"],
                          built["params"]["side_one.distance"]["expression"]), ("wt", "wd"))


if __name__ == "__main__":
    unittest.main()
