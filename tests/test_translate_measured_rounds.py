"""Rounds set by chord length and rounds whose radius changes along the edge (`translator/finishes/measured_rounds.py`).

The fixture is the 40 by 20 by 10 mm box of `fillet_four_edges`; its round step gets one set on the top edges here.
"""
import math
import unittest

from tests import context  # noqa: F401
from tests.derived_fixtures import dimension
from tests.sketch_solve_helpers import P, Sketch, rectangle
from tests.test_translate_sized import on_fixture, param, run
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of, variant, verdict_of

from lib.design_model.values import Quantity
from lib.translator import translate
from lib.translator.finishes import measured_rounds
from lib.translator.ranges.range_check import Span

SQUARE = [[0, 0, 1], [0, -1, 0]]
# Normals 60 degrees apart: a round of chord length c there has the radius c.
SIXTY = [[0, 0, 1], [0, math.sqrt(3) / 2, 0.5]]
FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)


def sampled(start, end, radius_at, sides=None, token="e0", curve="Line3D"):
    """An edge record from `start` to `end` with samples at FRACTIONS: the radius `radius_at(at)` and, when given,
    the same face normals `sides` at each."""
    direction = [b - a for a, b in zip(start, end)]
    samples = []
    for at in FRACTIONS:
        sample = {"at": at, "point": [a + d * at for a, d in zip(start, direction)], "tangent": direction,
                  "radius": radius_at(at)}
        if sides is not None:
            sample["sides"] = sides
        samples.append(sample)
    middle = [a + d / 2 for a, d in zip(start, direction)]
    found = {"token": token, "closed": False, "points": [middle], "curve": curve, "samples": samples}
    if sides is not None:
        found["side_faces"] = [{"face_point": middle, "surface": "Plane", "normal": normal} for normal in sides]
    return found


def front(radius_at, sides=SQUARE):
    """The top front edge, from x 0 to 40."""
    return sampled([0, 0, 10], [40, 0, 10], radius_at, sides)


def box_graph():
    """The sketch graph of the 40 by 20 mm outline of the box, from the origin, with fixed dimensions."""
    sketch = Sketch()
    corners = [0, sketch.point(40.0, 0.0), sketch.point(40.0, 20.0), sketch.point(0.0, 20.0)]
    rectangle(sketch, corners)
    dimension(sketch, "linear", [P(0), P(corners[1])], 40.0, "g1", "40 mm", "horizontal")
    dimension(sketch, "linear", [P(0), P(corners[3])], 20.0, "g2", "20 mm", "vertical")
    record = sketch.record()
    record["sketch"] = "Sketch1"
    return record


def chord_set(*edges, chord=2.0):
    return {"kind": "chordLength", "chord_length": chord, "continuity": "tangent", "input_kinds": ["edge"],
            "edges": list(edges)}


def changing_set(*edges, start=1.0, end=3.0, mid_count=0):
    return {"kind": "variable", "start_radius": start, "end_radius": end, "mid_count": mid_count,
            "continuity": "tangent", "input_kinds": ["edge"], "edges": list(edges)}


def with_sets(*sets):
    def edit(data):
        data["sets"] = list(sets)
    return edit


def even(first, last):
    return lambda at: first + (last - first) * at


class ChordLengthTest(unittest.TestCase):
    def test_each_edge_gets_the_radius_its_chord_gives_at_the_angle_of_its_faces(self):
        back = sampled([0, 20, 10], [40, 20, 10], lambda at: 2.0, SIXTY, token="e1")
        result = variant("fillet_four_edges", with_sets(chord_set(front(lambda at: math.sqrt(2)), back)))
        (step,) = steps_of(result.recipe, "round")
        self.assertAlmostEqual(step["size"], math.sqrt(2))
        self.assertEqual([round(s, 6) for s in step["edgeSizes"]], [round(math.sqrt(2), 6), 2.0])
        self.assertEqual(verdict_of(result, 2)["verdict"], "translated")
        assert_schema_ok(self, result.recipe)

    def test_a_tangent_chain_is_picked_by_its_edges_since_a_longer_chain_could_meet_other_angles(self):
        edge = dict(front(lambda at: math.sqrt(2)), seed=True)
        result = variant("fillet_four_edges", with_sets(dict(chord_set(edge), tangent_chain=True)))
        (step,) = steps_of(result.recipe, "round")
        self.assertEqual(step["edges"], {"near": [[20, 0, 10]]})

    def test_a_round_whose_faces_turn_along_the_edge_or_whose_radius_differs_is_left_out(self):
        turning = front(lambda at: math.sqrt(2))
        turning["samples"][-1]["sides"] = SIXTY
        unmeasured = front(lambda at: math.sqrt(2))
        for sample in unmeasured["samples"]:
            del sample["sides"]
        cases = (("faces turn", turning), ("radius differs", front(lambda at: 1.0)), ("no normals", unmeasured),
                 ("no samples", {"token": "e0", "closed": False, "points": [[20, 0, 10]]}))
        for name, edge in cases:
            with self.subTest(name):
                result = variant("fillet_four_edges", with_sets(chord_set(edge)))
                self.assertEqual(left_out(result)["index"], 2)

    def test_the_radius_follows_the_chord_size_while_no_size_can_turn_the_faces(self):
        def edit(data):
            with_sets(chord_set(front(lambda at: 3 * math.sqrt(0.5)), chord=3.0))(data)
            data["params"] = {"sets.0.chord_length": param("d4", "corner_mm", 3.0)}
        result, _ = run(*on_fixture("fillet_four_edges", edit))
        (step,) = steps_of(result.recipe, "round")
        self.assertIn("corner_mm", step["size"]["expr"])
        self.assertEqual(result.loose, [])

    def test_faces_that_may_turn_keep_the_radius_and_mark_the_chord_and_the_sizes_that_turn_them(self):
        def edit(data):
            with_sets(chord_set(front(lambda at: 3 * math.sqrt(0.5)), chord=3.0))(data)
            data["params"] = {"sets.0.chord_length": param("d4", "corner_mm", 3.0)}
        capture, ticked = on_fixture("fillet_four_edges", edit)
        # The box height follows wall_mm, and the copy cannot prove that the box faces keep their angle.
        capture["items"][1]["data"]["params"] = {"side_one.distance": param("d1", "wall_mm * 5", 10.0)}
        result, _ = run(capture, ticked)
        (step,) = steps_of(result.recipe, "round")
        self.assertAlmostEqual(step["size"], 3 * math.sqrt(0.5))
        self.assertEqual([entry["name"] for entry in result.loose], ["wall_mm"])
        self.assertIn("corner_mm", [entry["name"] for entry in result.dropped if entry["used"]])


    def test_a_face_that_curves_across_the_edge_keeps_the_radius_and_pins_the_chord(self):
        def on(surface, axis=None):
            def edit(data):
                edge = front(lambda at: 3 * math.sqrt(0.5))
                edge["side_faces"][1].update(surface=surface, axis=axis)
                with_sets(chord_set(edge, chord=3.0))(data)
                data["params"] = {"sets.0.chord_length": param("d4", "corner_mm", 3.0)}
            result, _ = run(*on_fixture("fillet_four_edges", edit))
            (step,) = steps_of(result.recipe, "round")
            return step["size"]
        self.assertIn("corner_mm", on("Cylinder", [0, 0, 1])["expr"])
        for name, surface, axis in (("a sphere", "other", None), ("a cylinder along the edge", "Cylinder", [1, 0, 0]),
                                    ("a cylinder whose axis was not read", "Cylinder", None)):
            with self.subTest(name):
                self.assertAlmostEqual(on(surface, axis), 3 * math.sqrt(0.5))

    def test_a_chain_or_face_pick_marks_the_sizes_that_may_add_edges_to_it(self):
        def picked(chain):
            def edit(data):
                edge = dict(front(lambda at: 3 * math.sqrt(0.5)), seed=True)
                # Points inside the top and the front face of the box, which its extrude made.
                for face, point in zip(edge["side_faces"], ([20, 10, 10], [20, 0, 5])):
                    face["face_point"] = point
                with_sets(dict(chord_set(edge, chord=3.0), tangent_chain=chain))(data)
                data["params"] = {"sets.0.chord_length": param("d4", "corner_mm", 3.0)}
            capture, ticked = on_fixture("fillet_four_edges", edit)
            capture["items"][1]["data"]["params"] = {"side_one.distance": param("d1", "wall_mm * 5", 10.0)}
            capture["sketch_graphs"] = [box_graph()]
            result, _ = run(capture, ticked)
            return [entry["name"] for entry in result.loose]
        # The box height does not turn its faces, but it may add edges to a chain that Fusion picks itself.
        self.assertEqual((picked(False), picked(True)), ([], ["wall_mm"]))


class ChangingRadiusTest(unittest.TestCase):
    def test_the_size_is_the_radius_at_the_end_lowest_along_x(self):
        cases = (("measured from the start", front(even(1, 3)), (1.0, 3.0)),
                 ("measured from the end", front(even(3, 1)), (3.0, 1.0)),
                 ("an edge that runs the other way", sampled([40, 0, 10], [0, 0, 10], even(1, 3)), (3.0, 1.0)))
        for name, edge, sizes in cases:
            with self.subTest(name):
                result = variant("fillet_four_edges", with_sets(changing_set(edge)))
                (step,) = steps_of(result.recipe, "round")
                self.assertEqual((step["size"], step["sizeEnd"]), sizes)
                assert_schema_ok(self, result.recipe)

    def test_the_ends_are_read_in_the_recipe_frame_of_a_y_up_design(self):
        # The recipe turns (x, y, z) to (x, -z, y): the top of a side edge lies lowest along the recipe's y.
        upright = sampled([0, 0, 0], [0, 0, 10], even(1, 3))
        capture = load_capture("fillet_four_edges")
        with_sets(changing_set(upright))(capture["items"][-1]["data"])
        (step,) = steps_of(translate(capture).recipe, "round")
        capture["up_axis"] = "y"
        (turned,) = steps_of(translate(capture).recipe, "round")
        self.assertEqual([(s["size"], s["sizeEnd"]) for s in (step, turned)], [(1.0, 3.0), (3.0, 1.0)])

    def test_the_ends_are_read_in_the_recipe_frame_of_a_turned_component(self):
        # The component is turned half round about z: the end at x 0 lies at x 0 and the end at x 40 at x -40.
        capture = load_capture("fillet_four_edges")
        with_sets(changing_set(front(even(1, 3))))(capture["items"][-1]["data"])
        (step,) = steps_of(translate(capture).recipe, "round")
        capture.setdefault("target", {})["placement"] = {
            "frame": {"origin": [5, 0, 0], "x": [-1, 0, 0], "y": [0, -1, 0], "z": [0, 0, 1]}}
        (turned,) = steps_of(translate(capture).recipe, "round")
        self.assertEqual([(s["size"], s["sizeEnd"]) for s in (step, turned)], [(1.0, 3.0), (3.0, 1.0)])

    def test_equal_radii_make_a_plain_round(self):
        result = variant("fillet_four_edges", with_sets(changing_set(front(lambda at: 2.0), start=2.0, end=2.0)))
        (step,) = steps_of(result.recipe, "round")
        self.assertEqual(step["size"], 2.0)
        self.assertNotIn("sizeEnd", step)

    def test_a_round_the_copy_cannot_make_evenly_is_left_out(self):
        smooth = front(lambda at: 1 + 2 * (3 * at ** 2 - 2 * at ** 3))
        close_ends = sampled([0, 0, 10], [0.0001, 20, 10], even(1, 3))
        spline = sampled([0, 0, 10], [40, 0, 10], even(1, 3), curve="NurbsCurve3D")
        unmeasured = front(even(1, 3))
        unmeasured["samples"][0]["radius"] = None
        cases = (("a smooth change", [changing_set(smooth)]),
                 ("radii between the ends", [changing_set(front(even(1, 3)), mid_count=1)]),
                 ("two edges", [changing_set(front(even(1, 3)), sampled([0, 20, 10], [40, 20, 10], even(1, 3)))]),
                 ("two sets", [changing_set(front(even(1, 3))), chord_set(front(lambda at: math.sqrt(2)))]),
                 ("a spline edge", [changing_set(spline)]),
                 ("ends too close along x", [changing_set(close_ends)]),
                 ("a radius not measured", [changing_set(unmeasured)]),
                 ("mid points not read", [changing_set(front(even(1, 3)), mid_count=None)]))
        for name, sets in cases:
            with self.subTest(name):
                result = variant("fillet_four_edges", with_sets(*sets))
                self.assertEqual(left_out(result)["index"], 2)

    def test_both_radii_follow_their_sizes(self):
        def edit(data):
            with_sets(changing_set(front(even(2, 3)), start=2.0, end=3.0))(data)
            data["params"] = {"sets.0.start_radius": param("d4", "wall_mm", 2.0),
                              "sets.0.end_radius": param("d5", "corner_mm", 3.0)}
        result, _ = run(*on_fixture("fillet_four_edges", edit))
        (step,) = steps_of(result.recipe, "round")
        self.assertEqual((step["size"], step["sizeEnd"]), ({"expr": "wall_mm"}, {"expr": "corner_mm"}))
        self.assertEqual(result.loose, [])


class EndOrderTest(unittest.TestCase):
    """Which end of an edge the app starts a changing radius from, and the sizes that may change it."""
    ROWS = ((1, 0, 0), (0, 1, 0), (0, 0, 1))

    @staticmethod
    def at(*coords):
        return [c if isinstance(c, Quantity) else Quantity(c) for c in coords]

    def test_a_gap_that_may_close_or_open_marks_its_sizes(self):
        moving = Quantity(5.0, "w", ("w",))
        crosses = lambda gap: Span(-5.0, 5.0) if gap.sized else None  # noqa: E731
        holds = lambda gap: Span(1.0, 10.0) if gap.sized else None  # noqa: E731
        start = self.at(0, 0, 0)
        self.assertEqual(measured_rounds.end_order(self.ROWS, start, self.at(moving, 0, 0), holds), (True, []))
        self.assertEqual(measured_rounds.end_order(self.ROWS, start, self.at(moving, 0, 0), crosses), (True, ["w"]))
        level = Quantity(0.0, "w - 5", ("w",))
        self.assertEqual(measured_rounds.end_order(self.ROWS, start, self.at(level, -3, 0), crosses), (False, ["w"]))


if __name__ == "__main__":
    unittest.main()
