"""Thin extrudes of an open line: the wall along a chain of sketch lines is copied with square ends and sharp
corners on the side the faces Fusion made show; every case the copy cannot prove is refused."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sketch_motion import motion_of, run
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of

from lib.design_model.values import Quantity
from lib.translator import translate
from lib.translator.extrude import thin_line
from lib.translator.faces.placer import ADD
from lib.translator.faces.thin_wall import ThinWall

LINE = "thin_line_corner"
EXTRUDE = 1
SIZES = ["length_mm", "height_mm", "wall_mm"]
HEIGHT = 15.0
# The outline of the wall along (0, 0) to (30, 0) to (30, 20), 2 mm thick, for each side.
INSIDE = [[0, 2], [28, 2], [28, 20], [30, 20], [30, 0], [0, 0]]
OUTSIDE = [[0, 0], [30, 0], [30, 20], [32, 20], [32, -2], [0, -2]]
MIDDLE = [[0, 1], [29, 1], [29, 20], [31, 20], [31, -1], [0, -1]]


def faces_of(corners, low=0.0, high=HEIGHT):
    """Faces Fusion makes for a wall with this outline between the heights `low` and `high`: one per side at the
    middle of its edge, and both ends."""
    out = []
    ring = corners + corners[:1]
    for a, b in zip(ring, ring[1:]):
        d = [b[0] - a[0], b[1] - a[1]]
        size = (d[0] ** 2 + d[1] ** 2) ** 0.5
        out.append({"surface": "Plane", "point": [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (low + high) / 2],
                    "normal": [d[1] / size, -d[0] / size, 0.0]})
    inside = [(corners[0][0] + corners[-1][0]) / 2, (corners[0][1] + corners[-1][1]) / 2]
    out += [{"surface": "Plane", "point": inside + [low], "normal": [0, 0, -1]},
            {"surface": "Plane", "point": inside + [high], "normal": [0, 0, 1]}]
    return out


def data_of(capture):
    return capture["items"][EXTRUDE]["data"]


def with_edit(edit):
    capture = load_capture(LINE)
    edit(data_of(capture))
    return translate(capture)


def wall(location, corners, low=0.0, high=HEIGHT):
    def edit(data):
        data["thin_wall"]["location"] = location
        data["wall_faces"] = faces_of(corners, low, high)
    return edit


def only_step(result):
    assert result.recipe is not None, result.refusal
    (step,) = steps_of(result.recipe, "extrude")
    return step


def reason_of(result):
    assert result.recipe is None, "the thin extrude was copied"
    assert result.refusal["index"] == EXTRUDE
    return result.refusal["reason"]


class ThinLineCopyTest(unittest.TestCase):
    def test_the_wall_is_written_along_the_open_line_with_square_ends_and_sharp_corners(self):
        result = translate(load_capture(LINE))
        step = only_step(result)
        self.assertEqual(step["sketch"]["outer"], {"kind": "open", "start": [0.0, 0.0], "segments": [
            {"kind": "line", "to": [30.0, 0.0]}, {"kind": "line", "to": [30.0, 20.0]}]})
        self.assertEqual(step["thin"], {"thickness": 2.0, "side": "inside", "ends": "square", "corners": "sharp"})
        self.assertEqual((step["extent"], step["distance"], result.recipe["version"]), ("oneSide", 15.0, 17))
        assert_schema_ok(self, result.recipe)

    def test_each_location_gives_the_side_its_faces_show(self):
        for location, corners, side in (("side1", INSIDE, "inside"), ("side2", OUTSIDE, "outside"),
                                        ("center", MIDDLE, "middle")):
            with self.subTest(location):
                self.assertEqual(only_step(with_edit(wall(location, corners)))["thin"]["side"], side)

    def test_an_extrude_against_the_sketch_normal_mirrors_the_line_and_its_side(self):
        def down(data):
            wall("side1", INSIDE, -HEIGHT, 0.0)(data)
            data["side_one"]["distance"] = -HEIGHT
        step = only_step(with_edit(down))
        self.assertEqual(step["sketch"]["on"]["normal"], [0.0, 0.0, -1.0])
        self.assertEqual(step["sketch"]["outer"]["segments"][-1]["to"], [30.0, -20.0])
        self.assertEqual(step["thin"]["side"], "outside")

    def test_a_symmetric_extrude_is_copied(self):
        def symmetric(data):
            wall("center", MIDDLE, -HEIGHT / 2, HEIGHT / 2)(data)
            data.update(extent_type="symmetric", side_one=None,
                        symmetric={"distance": HEIGHT, "full_length": True, "taper_deg": 0.0})
            data["params"] = {"thin.thickness": data["params"]["thin.thickness"]}
        step = only_step(with_edit(symmetric))
        self.assertEqual((step["extent"], step["distance"], step["thin"]["side"]), ("symmetric", HEIGHT, "middle"))

    def test_the_placer_holds_material_only_in_the_wall(self):
        corners = thin_line.band([[0, 0], [30, 0], [30, 20]], 2.0, 0.0)
        profile = thin_line.band_profile(data_of(load_capture(LINE))["path"]["frame"], corners)
        on = {"origin": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0], "xDir": [1.0, 0.0, 0.0]}
        placed = ThinWall("e", on, "oneSide", Quantity(HEIGHT), profile, "inside", 2.0, "new")
        self.assertEqual([placed.material_at(p) for p in ([10, 1, 5], [29, 10, 5], [10, -1, 5], [20, 10, 5])],
                         [ADD, ADD, None, None])


class ThinLineRefusalTest(unittest.TestCase):
    def test_faces_on_the_other_side_than_side_one_gives_refuse(self):
        self.assertEqual(reason_of(with_edit(wall("side1", OUTSIDE))), thin_line.NOT_MATCHING)

    def test_faces_that_fit_both_sides_refuse(self):
        def on_the_line_only(data):
            data["wall_faces"] = [{"surface": "Plane", "point": [15, 0, 7.5], "normal": [0, 1, 0]},
                                  {"surface": "Plane", "point": [15, 0, HEIGHT], "normal": [0, 0, 1]}]
        self.assertEqual(reason_of(with_edit(on_the_line_only)), thin_line.UNSURE)

    def test_faces_on_the_other_way_than_the_stored_direction_refuse(self):
        self.assertEqual(reason_of(with_edit(wall("side1", INSIDE, -HEIGHT, 0.0))), thin_line.NOT_MATCHING)

    def test_a_round_face_refuses(self):
        def rounded(data):
            data["wall_faces"][2]["surface"] = "Cylinder"
        self.assertEqual(reason_of(with_edit(rounded)), thin_line.NOT_MATCHING)

    def test_a_line_the_copy_cannot_hold_refuses(self):
        def curves(data):
            return data["path"]["curves"]

        def arc(data):
            curves(data)[1]["kind"] = "arc"

        def against(data):
            curves(data)[1]["opposed"] = True

        def apart(data):
            curves(data)[1]["flat"]["start"] = [31.0, 0.0]

        def closed(data):
            data["path"]["closed"] = True

        def edges(data):
            data["path"]["kind"] = "edges"

        def unread(data):
            data["path"] = None

        def no_faces(data):
            data["wall_faces"] = None

        def sharp(data):
            curves(data)[1]["flat"]["end"] = [0.0, 1.0]

        def short(data):
            curves(data)[1]["flat"]["end"] = [30.0, 1.5]
            data["wall_faces"] = faces_of([[0, 2], [28, 2], [28, 1.5], [30, 1.5], [30, 0], [0, 0]])

        cases = {"arc": arc, "against the path": against, "not joined": apart, "closed": closed, "edges": edges,
                 "unread": unread, "no faces": no_faces, "too sharp": sharp, "shorter than its corner": short}
        for name, edit in cases.items():
            with self.subTest(name):
                self.assertTrue(reason_of(with_edit(edit)))


class ThinLineSizesTest(unittest.TestCase):
    def test_the_line_the_height_and_the_wall_follow_their_sizes(self):
        result = run(load_capture(LINE), SIZES, motion_of(LINE))
        step = only_step(result)
        self.assertEqual([s["to"][0] for s in step["sketch"]["outer"]["segments"]],
                         [{"expr": "length_mm"}, {"expr": "length_mm"}])
        self.assertEqual((step["distance"], step["thin"]["thickness"]), ({"expr": "height_mm"}, {"expr": "wall_mm"}))
        self.assertEqual((result.fixed, result.loose, result.cuts), ([], [], []))
        assert_schema_ok(self, result.recipe)

    def test_the_wall_range_stops_before_the_corner_takes_the_whole_short_line(self):
        capture = load_capture(LINE)

        def short_leg(data):
            data["path"]["curves"][1]["flat"]["end"] = [30.0, 3.0]
            data["wall_faces"] = faces_of([[0, 2], [28, 2], [28, 3], [30, 3], [30, 0], [0, 0]])
        short_leg(data_of(capture))
        result = run(capture, SIZES, motion_of(LINE))
        self.assertEqual(only_step(result)["thin"]["thickness"], {"expr": "wall_mm"})
        self.assertEqual([(c["name"], c["min"]) for c in result.cuts], [("wall_mm", 1.0)])
        self.assertTrue(2.0 <= result.cuts[0]["max"] < 3.0)

    def test_a_line_the_probe_did_not_follow_keeps_its_numbers_and_its_size_is_dropped(self):
        motion = motion_of(LINE)
        motion.curves = set()
        result = run(load_capture(LINE), SIZES, motion)
        self.assertEqual(only_step(result)["sketch"]["outer"]["segments"][0]["to"], [30.0, 0.0])
        self.assertEqual([f["name"] for f in result.dropped], ["length_mm"])


if __name__ == "__main__":
    unittest.main()
