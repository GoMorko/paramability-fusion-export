"""Holes in the Orca copy: centres that follow sizes through the frame and graph of their sketch, centres that keep
their place, and tapped holes (a cosmetic thread drills the drill size; a modeled one adds an Orca thread and a
lead-in at each open end)."""
import copy
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.derived_fixtures import box_capture, dimension, plate_graph, plate_profile, MODEL, PARAMS
from tests.sketch_solve_helpers import P, Sketch
from tests.test_capture_reader import Obj
from tests.test_capture_reader_tokens import FeatureTokensTest, read_item, sketch
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import FeatureType
from lib.orca_translate import FIXED, PARTLY, VARIABLE, causes, outline_cuts, translate
from lib.orca_translate.formulas import orca_value
from lib.orca_translate.place import Placement, plane_point
from lib.params import size_table

UP = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
BOX_TICKED = ["box_count", "cube_mm", "depth_mm", "height_mm", "pipe_offset_mm"]


class ReaderTest(unittest.TestCase):
    def test_holes_on_one_sketch_record_its_frame(self):
        points = FeatureTokensTest()
        sk = sketch()
        data = read_item(points.hole([points.point("p1", sk, (1, 2, 3)), points.point("p2", sk, (4, 5, 6))]))
        self.assertEqual(set(data["sketch_frame"]), {"origin", "x", "y", "z"})
        data = read_item(points.hole([points.point("p1", sketch("a"), (1, 2, 3)),
                                      points.point("p2", sketch("b"), (4, 5, 6))]))
        self.assertNotIn("sketch_frame", data)

    def test_holes_on_a_sketch_record_what_it_sits_on(self):
        points = FeatureTokensTest()
        face = Obj("fusion::BRepFace", entityToken="f1")
        data = read_item(points.hole([points.point("p1", sketch(reference=face), (1, 2, 3))]))
        self.assertEqual((data["reference"]["kind"], data["reference"]["token"]), ("face", "f1"))
        self.assertNotIn("reference", read_item(points.hole([points.point("p1", sketch(), (1, 2, 3))])))


def holes(result):
    return [f for f in result.recipe.features if f.type == FeatureType.HOLE]


def centre(feature, env):
    """Where Orca puts a hole's centre at the variable values `env`."""
    def value(field):
        return orca_value(feature.expr[field], env) if field in feature.expr else getattr(feature, field)
    return plane_point(feature.plane, (value("hole_x"), value("hole_y")))


def box_hole(frame=UP, projected=None):
    """The centred box with its hole on Sketch2 placed `pipe_offset_mm` left of the sketch origin, drilled up. With
    `projected` (the `reference` of a projected point at the origin), the hole is dimensioned from that point."""
    capture = box_capture()
    capture["items"] = [it for it in capture["items"] if it["type"] not in ("ShellFeature", "FilletFeature")]
    s = Sketch()
    point = s.point(-20.0, 0.0)
    start = 0 if projected is None else s.point(0.0, 0.0, reference=projected)
    dimension(s, "linear", [P(point), P(start)], 20.0, "d7", "pipe_offset_mm", "horizontal")
    s.con("horizontal_points", P(start), P(point))
    record = s.record()
    record.update(sketch="Sketch2", token="s2")
    capture["sketch_graphs"].append(record)
    data = [it for it in capture["items"] if it["type"] == "HoleFeature"][0]["data"]
    data.update(sketch_token="s2", sketch="Sketch2", end_points=[[-20, 0, 32]])
    if frame is not None:
        data["sketch_frame"] = frame
    return capture


def run(capture, ticked):
    table = size_table.build(capture["parameters"]["user"], ticked, capture["parameters"]["model"])
    return translate(capture, table)


def outcome(result, name):
    return next(p for p in result.parameters if p["name"] == name)


class PlaceTest(unittest.TestCase):
    def test_a_centre_placed_by_a_size_follows_it(self):
        capture = box_hole()
        result = run(capture, BOX_TICKED)
        (hole,) = holes(result)
        place = Placement(capture)
        for offset in (20.0, 30.0):
            found = centre(hole, {"pipe_offset_mm": offset})
            for a, b in zip(found, place.point([-offset, 0, 0])):
                self.assertAlmostEqual(a, b)
        self.assertEqual(outcome(result, "pipe_offset_mm")["outcome"], VARIABLE)

    def test_a_hole_drilled_against_its_sketch_normal_keeps_its_centre(self):
        capture = box_hole(dict(UP, origin=[0, 0, 32]))
        data = capture["items"][-1]["data"]
        data.update(direction=[0, 0, -1], positions=[[-20, 0, 32]], end_points=[[-20, 0, 0]])
        (hole,) = holes(run(capture, BOX_TICKED))
        self.assertEqual(hole.plane.normal, (0.0, 0.0, -1.0))
        for a, b in zip(centre(hole, {"pipe_offset_mm": 30.0}), Placement(capture).point([-30, 0, 32])):
            self.assertAlmostEqual(a, b)

    def test_a_centre_dimensioned_from_projected_geometry_follows_the_sketchs_own_size(self):
        # The projection may move with the sizes read before the sketch, never with the sketch's own dimensions.
        for reference in ({"source": "own", "component": "", "token": "o", "origin": True},
                          {"source": "own", "component": "", "token": "e"}):
            with self.subTest(reference):
                result = run(box_hole(projected=reference), BOX_TICKED)
                (hole,) = holes(result)
                self.assertEqual(hole.expr["hole_x"], "-pipe_offset_mm")
                self.assertEqual(outcome(result, "pipe_offset_mm")["outcome"], VARIABLE)

    def test_without_the_sketch_frame_the_centre_keeps_its_place(self):
        capture = box_hole(frame=None)
        result = run(capture, BOX_TICKED)
        (hole,) = holes(result)
        self.assertNotIn("hole_x", hole.expr)
        self.assertEqual(hole.plane.origin, Placement(capture).point([-20, 0, 0]))
        self.assertEqual(outcome(result, "pipe_offset_mm")["outcome"], FIXED)

    def test_a_size_the_part_does_not_follow_is_held_in_the_hole(self):
        # The plate as a plain rectangle, which grows about its centre in Orca, so width is held in the hole.
        with mock.patch.object(outline_cuts, "plan", return_value=None):
            result = run(self._plate_and_hole(), ["width", "height", "margin"])
        (made,) = holes(result)
        self.assertNotIn("hole_x", made.expr)
        self.assertEqual(outcome(result, "width")["outcome"], PARTLY)

    def test_a_hole_follows_a_plate_built_from_cuts(self):
        result = run(self._plate_and_hole(), ["width", "height", "margin"])
        (made,) = holes(result)
        self.assertEqual(made.expr["hole_x"], "width - 5")

    @staticmethod
    def _plate_and_hole():
        """The plate drawn from the origin (it grows to one side in Fusion) and a hole `margin` from its right edge,
        on a second sketch with the same graph."""
        capture = copy.deepcopy(load_capture("extrude_plate"))
        outer = plate_profile()
        outer["loops"] = outer["loops"][:1]
        capture["items"][1]["data"]["profiles"] = [outer]
        capture["parameters"] = {"user": PARAMS, "model": MODEL}
        graph = plate_graph()[0]
        capture["sketch_graphs"] = [graph, dict(copy.deepcopy(graph), sketch="Sketch2", token="s2")]
        hole = copy.deepcopy(load_capture("hole_through")["items"][3])
        hole["data"].update(positions=[[35, 10, 10]], end_points=[[35, 10, 0]], sketch="Sketch2", sketch_token="s2",
                            sketch_frame=dict(UP, origin=[0, 0, 10]))
        capture["items"].append(hole)
        return capture


def plate_hole(**hole):
    """A 40 by 20 plate `thick` (10) tall and a hole drilled down from a point of Sketch2 at its top; `hole` sets the
    hole's sketch keys."""
    capture = copy.deepcopy(load_capture("hole_through"))
    capture["items"][1]["data"]["params"] = {"side_one.distance": {"name": "d1", "expression": "thick", "value": 10.0}}
    capture["parameters"] = {"user": [{"name": "thick", "expression": "10 mm", "value": 1.0, "unit": "mm",
                                       "kind": "length", "display_value": 10}],
                             "model": [{"name": "d1", "expression": "thick", "value": 1.0, "unit": "mm"}]}
    capture["items"][3]["data"].update(hole)
    return capture


class PlaneTest(unittest.TestCase):
    def test_sizes_that_may_move_the_plane_of_the_holes_are_marked(self):
        on_sketch = dict(sketch="Sketch2", sketch_token="s2", sketch_frame=dict(UP, origin=[0, 0, 10]))
        cases = {"on the top face": (dict(on_sketch, reference={"kind": "face", "token": "top"}), PARTLY),
                 "reference not read": (on_sketch, PARTLY),
                 "on a face without a sketch": ({}, PARTLY),
                 "on the origin plane": (dict(on_sketch, sketch_frame=UP, direction=[0, 0, 1], positions=[[10, 10, 0]],
                                              end_points=[[10, 10, 10]],
                                              reference={"kind": "constructionPlane", "token": "",
                                                                "origin": True}), VARIABLE)}
        for name, (keys, state) in cases.items():
            with self.subTest(name):
                result = run(plate_hole(**keys), ["thick"])
                self.assertEqual(len(holes(result)), 1)
                self.assertEqual(outcome(result, "thick")["outcome"], state)


def tapped(modeled, **more):
    capture = copy.deepcopy(load_capture("hole_tapped_modeled" if modeled else "hole_tapped_cosmetic"))
    data = capture["items"][3]["data"]
    if modeled:
        data["thread"] = {"thread_type": "ISO Metric profile", "designation": "M6x1", "internal": True,
                          "right_hand": True, "pitch": 1.0, "major_diameter": 6.0, "minor_diameter": 4.917,
                          "angle_deg": None, "full_length": True, "depth": None, "made_span": [0.0, 10.0]}
        data["side_cylinders"] = [{"origin": [10, 10, 10], "axis": [0, 0, -1], "radius": 4.917 / 2,
                                   "span": [0.0, 10.0]}]
    data.update(more)
    return capture


def holes_and_threads(result):
    return [f for f in result.recipe.features if f.type in (FeatureType.HOLE, FeatureType.THREAD)]


class TappedTest(unittest.TestCase):
    def test_a_cosmetic_thread_drills_the_drill_size(self):
        result = translate(tapped(False))
        (hole,) = holes(result)
        self.assertAlmostEqual(hole.hole_diameter, 5.1)
        self.assertEqual([f for f in result.recipe.features if f.type == FeatureType.THREAD], [])

    def test_a_modeled_thread_drills_the_minor_diameter_and_adds_a_thread_and_lead_ins(self):
        capture = tapped(True)
        result = translate(capture)
        hole, thread, entry, exit_ = holes_and_threads(result)
        self.assertAlmostEqual(hole.hole_diameter, 4.917)
        self.assertEqual((thread.type, thread.thread_internal, thread.thread_radius), (FeatureType.THREAD, True, 3.0))
        self.assertAlmostEqual(thread.thread_height, 10.0 - 1.0)
        self.assertEqual(thread.plane.normal, hole.plane.normal)
        place = Placement(capture)
        for a, b in zip(thread.plane.origin, place.point([10, 10, 9.5])):
            self.assertAlmostEqual(a, b)
        for lead, z in ((entry, 10), (exit_, 0)):
            self.assertEqual((lead.type, lead.hole_through), (FeatureType.HOLE, False))
            self.assertAlmostEqual(lead.hole_diameter, 6.1)
            self.assertAlmostEqual(lead.hole_depth, 0.45)
            for a, b in zip(plane_point(lead.plane, (lead.hole_x, lead.hole_y)), place.point([10, 10, z])):
                self.assertAlmostEqual(a, b)
        self.assertEqual(exit_.plane.normal, tuple(-c for c in hole.plane.normal))

    def test_a_blind_thread_follows_the_hole_depth_and_has_no_lead_in_at_the_bottom(self):
        capture = tapped(True, extent={"kind": "distance", "depth": 8.0}, end_points=[[10, 10, 2]],
                         params={"extent.depth": {"name": "d8", "expression": "bore", "value": 8.0}})
        capture["parameters"] = {"user": [{"name": "bore", "expression": "8 mm", "value": 0.8, "unit": "mm",
                                           "kind": "length", "display_value": 8}],
                                 "model": [{"name": "d8", "expression": "bore", "value": 0.8, "unit": "mm"}]}
        result = run(capture, ["bore"])
        hole, thread, entry = holes_and_threads(result)
        self.assertAlmostEqual(orca_value(thread.expr["thread_height"], {"bore": 5.0}), 4.0)
        self.assertEqual(entry.plane.normal, hole.plane.normal)

    def test_the_thread_and_lead_ins_of_a_hole_placed_by_a_size_follow_it(self):
        capture = box_hole()
        data = capture["items"][-1]["data"]
        data.update(tap_type="tapped", thread_modeled=True,
                    side_cylinders=[{"origin": [-20, 0, 0], "axis": [0, 0, 1], "radius": 10.106 / 2,
                                     "span": [0.0, 32.0]}],
                    thread={"thread_type": "ISO Metric profile", "designation": "M12x1.75", "internal": True,
                            "right_hand": True, "pitch": 1.75, "major_diameter": 12.0, "minor_diameter": 10.106,
                            "angle_deg": None, "full_length": True, "depth": None, "made_span": [0.0, 32.0]})
        made = holes_and_threads(run(capture, BOX_TICKED))
        self.assertEqual(len(made), 4)
        place = Placement(capture)
        for feature in made:
            x, y = ("thread_x", "thread_y") if feature.type == FeatureType.THREAD else ("hole_x", "hole_y")
            values = [orca_value(feature.expr[f], {"pipe_offset_mm": 30.0}) if f in feature.expr
                      else getattr(feature, f) for f in (x, y)]
            found = plane_point(feature.plane, values)
            for a, b in zip(found[:2], place.point([-30, 0, 0])[:2]):
                self.assertAlmostEqual(a, b)

    def test_tapped_holes_that_cannot_be_copied_are_left_out(self):
        cases = {"tapered": (tapped(True, tap_type="taperTapped"), gap_hints.THREAD_PROFILE),
                 "unread thread": (load_capture("hole_tapped_modeled"), gap_hints.REFUSED),
                 "unread kind": (tapped(True, thread_modeled=None), gap_hints.REFUSED),
                 "counterbore, thread faces not measured": (
                     tapped(True, hole_type="counterbore", counterbore={"diameter": 9.0, "depth": 3.0},
                            thread=dict(tapped(True)["items"][3]["data"]["thread"], made_span=None)),
                     causes.TAPPED_RECESS),
                 "countersink": (tapped(True, hole_type="countersink",
                                        countersink={"diameter": 9.0, "angle_deg": 90.0}), causes.TAPPED_RECESS)}
        for name, (capture, cause) in cases.items():
            with self.subTest(name):
                result = translate(capture)
                self.assertEqual(holes(result), [])
                self.assertEqual([g["cause"] for g in result.left_out], [cause])

    def test_a_modeled_thread_under_a_counterbore_starts_at_its_floor(self):
        # A counterbore 3 mm deep through the 10 mm part: Fusion's thread runs from the floor to the bottom face.
        capture = tapped(True, hole_type="counterbore", counterbore={"diameter": 9.0, "depth": 3.0})
        data = capture["items"][3]["data"]
        data["thread"]["made_span"] = [3.0, 10.0]
        data["params"] = {"counterbore.depth": {"name": "d9", "expression": "recess", "value": 3.0}}
        capture["parameters"] = {"user": [{"name": "recess", "expression": "3 mm", "value": 0.3, "unit": "mm",
                                           "kind": "length", "display_value": 3}],
                                 "model": [{"name": "d9", "expression": "recess", "value": 0.3, "unit": "mm"}]}
        result = run(capture, ["recess"])
        hole, thread, entry, exit_ = holes_and_threads(result)
        place = Placement(capture)
        self.assertEqual(hole.hole_style, 1)
        self.assertAlmostEqual(thread.thread_height, 7.0 - 1.0)
        for a, b in zip(thread.plane.origin, place.point([10, 10, 6.5])):
            self.assertAlmostEqual(a, b)
        for lead, z in ((entry, 7), (exit_, 0)):
            for a, b in zip(plane_point(lead.plane, (lead.hole_x, lead.hole_y)), place.point([10, 10, z])):
                self.assertAlmostEqual(a, b)
        # The thread start keeps its number, so the counterbore depth is followed only in part.
        self.assertEqual(outcome(result, "recess")["outcome"], PARTLY)

    def test_a_cosmetic_thread_in_a_counterbore_is_drilled(self):
        result = translate(load_capture("hole_tapped_counterbore"))
        (hole,) = holes(result)
        self.assertEqual(hole.hole_style, 1)

    def test_the_minor_diameter_must_match_the_measured_bore(self):
        capture = tapped(True, side_cylinders=[{"origin": [10, 10, 10], "axis": [0, 0, -1], "radius": 2.0}])
        self.assertEqual(holes(translate(capture)), [])


if __name__ == "__main__":
    unittest.main()
