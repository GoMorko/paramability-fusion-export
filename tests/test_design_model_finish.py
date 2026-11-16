"""The shared reader of round and chamfer sets (`design_model/steps/finish.py`): what a set asks for, as facts."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture

from lib.design_model.steps import finish
from lib.design_model.values import Quantity


def edge(*points, **more):
    return dict({"token": "e", "closed": False, "points": list(points)}, **more)


def chamfer_set(**entry):
    return finish.ChamferSet(0, dict({"kind": "equal", "distance": 1.0, "edges": [edge([0, 0, 0])]}, **entry))


class RoundSetTest(unittest.TestCase):
    def test_radius_and_reach_are_known_only_for_a_readable_constant_round(self):
        cases = [({"kind": "constant", "radius": 2.0, "continuity": "tangent"}, 2.0, 2.0),
                 ({"kind": "constant", "radius": 2.0, "continuity": "curvature"}, 2.0, None),
                 ({"kind": "constant", "radius": 0}, None, None),
                 ({"kind": "variable"}, None, None)]
        for entry, radius, reach in cases:
            with self.subTest(entry):
                one = finish.RoundSet(0, entry)
                self.assertEqual((one.radius, one.reach), (radius, reach))

    def test_edges_say_whether_they_can_be_copied(self):
        whole = finish.RoundSet(0, {"edges": [edge([1, 2, 3])]})
        self.assertEqual((whole.unlocated, whole.foreign, whole.follows_step), (False, False, False))
        odd = finish.RoundSet(0, {"edges": [edge(), edge([1, 2, 3], foreign=True)], "input_kinds": ["feature"]})
        self.assertEqual((odd.unlocated, odd.foreign, odd.follows_step), (True, True, True))


def sampled(radius_at=None, sides_at=None):
    """An edge from (0, 0, 10) to (40, 0, 10) with samples at 0, 1/4, 1/2, 3/4 and 1: the radius `radius_at(at)`
    and the face normals `sides_at(at)` there, when given."""
    samples = []
    for at in (0.0, 0.25, 0.5, 0.75, 1.0):
        sample = {"at": at, "point": [40 * at, 0, 10], "tangent": [1, 0, 0]}
        if radius_at:
            sample["radius"] = radius_at(at)
        if sides_at:
            sample["sides"] = sides_at(at)
        samples.append(sample)
    return edge([20, 0, 10], samples=samples)


def square(at):
    return [[0, 0, 1], [0, -1, 0]]


class MeasuredRoundTest(unittest.TestCase):
    def test_the_face_angle_is_known_only_when_it_stays_the_same_along_the_edge(self):
        self.assertAlmostEqual(finish.face_angle(sampled(sides_at=square)), 90.0)
        leaning = sampled(sides_at=lambda at: [[0, 0, 1], [0, -math.cos(at), math.sin(at)]])
        self.assertIsNone(finish.face_angle(leaning))
        self.assertIsNone(finish.face_angle(sampled()))

    def test_the_radius_of_a_chord_needs_faces_that_meet_at_a_corner(self):
        self.assertAlmostEqual(finish.chord_radius(2.0, 90.0), math.sqrt(2))
        self.assertAlmostEqual(finish.chord_radius(2.0, 60.0), 2.0)
        self.assertIsNone(finish.chord_radius(2.0, 0.5))

    def test_the_measured_radius_may_skip_the_ends_of_the_edge(self):
        ends_differ = sampled(radius_at=lambda at: 1.5 if 0 < at < 1 else 3.0)
        self.assertFalse(finish.matches_radius(ends_differ, lambda at: 1.5))
        self.assertTrue(finish.matches_radius(ends_differ, lambda at: 1.5, ends=False))

    def test_the_law_of_a_changing_radius_is_read_from_the_measured_radii(self):
        cases = (("from the start", lambda at: 1 + 2 * at, finish.FROM_START),
                 ("from the end", lambda at: 3 - 2 * at, finish.FROM_END),
                 ("a smooth blend", lambda at: 1 + 2 * (3 * at ** 2 - 2 * at ** 3), None))
        for name, radius_at, law in cases:
            self.assertEqual(finish.law(sampled(radius_at=radius_at), 1.0, 3.0), law, name)
        self.assertEqual(finish.law(sampled(radius_at=lambda at: 2.0), 2.0, 2.0), finish.LEVEL)
        missing = sampled(radius_at=lambda at: 1 + 2 * at)
        missing["samples"][2]["radius"] = None
        self.assertIsNone(finish.law(missing, 1.0, 3.0))


class ChamferSetTest(unittest.TestCase):
    def test_even_when_both_sides_have_the_same_size(self):
        cases = [(dict(kind="equal"), True), (dict(kind="twoDistances", distance_two=1.0), True),
                 (dict(kind="twoDistances", distance_two=2.0), False),
                 (dict(kind="distanceAngle", angle_deg=45.0), True),
                 (dict(kind="distanceAngle", angle_deg=30.0), False)]
        for entry, even in cases:
            with self.subTest(entry):
                one = chamfer_set(**entry)
                self.assertEqual((one.problem, one.even), (None, even))

    def test_a_value_that_cannot_be_read_is_named(self):
        cases = [(dict(distance=0), finish.NO_SIZE), (dict(kind="twoDistances", distance_two=None), finish.NO_SIZE),
                 (dict(kind="distanceAngle", angle_deg=90.0), finish.NO_ANGLE),
                 (dict(kind="other"), finish.UNKNOWN_KIND)]
        for entry, problem in cases:
            with self.subTest(entry):
                one = chamfer_set(**entry)
                self.assertEqual((one.problem, one.even), (problem, False))

    def test_the_second_measure_is_second_when_uneven_and_held_when_even(self):
        uneven = chamfer_set(kind="twoDistances", distance_two=2.0)
        self.assertEqual((uneven.second.kind, uneven.second.number, uneven.second.path, uneven.held),
                         (finish.DISTANCE, 2.0, "sets.0.distance_two", None))
        self.assertAlmostEqual(uneven.ratio, 0.5)
        even = chamfer_set(kind="distanceAngle", angle_deg=45.0)
        self.assertEqual((even.second, even.held.kind, even.held.path, even.ratio),
                         (None, finish.ANGLE, "sets.0.angle_deg", None))
        angled = chamfer_set(kind="distanceAngle", angle_deg=30.0)
        self.assertAlmostEqual(angled.ratio, 1.0 / math.tan(math.radians(30.0)))
        self.assertIsNone(chamfer_set().held)

    def test_sizes_are_made_by_the_destination(self):
        asked = []

        def quantity(path, number, dim):
            asked.append((path, number, dim))
            return Quantity(number)
        one = chamfer_set(kind="distanceAngle", angle_deg=30.0)
        one.size(quantity)
        one.second.size(quantity)
        self.assertEqual(asked, [("sets.0.distance", 1.0, "length"), ("sets.0.angle_deg", 30.0, "angle")])

    def test_reach_is_the_largest_distance_along_a_face(self):
        cases = [(dict(kind="equal"), 1.0), (dict(kind="twoDistances", distance_two=2.0), 2.0),
                 (dict(kind="distanceAngle", angle_deg=60.0), math.tan(math.radians(60.0))),
                 (dict(kind="distanceAngle", angle_deg=89.5), None), (dict(kind="other"), None)]
        for entry, reach in cases:
            with self.subTest(entry):
                self.assertEqual(chamfer_set(**entry).reach, reach)


class SidesTest(unittest.TestCase):
    def two_sides(self):
        data = load_capture("chamfer_two_sides")["items"][-1]["data"]
        return finish.chamfer_sets(copy.deepcopy(data))[0]

    def test_an_even_chamfer_is_one_part_with_no_direction(self):
        one = chamfer_set()
        self.assertEqual(one.sides(), [(None, one.edges)])

    def test_an_uneven_chamfer_gives_the_direction_of_the_face_of_the_first_distance(self):
        one = self.two_sides()
        ((direction, edges),) = one.sides()
        self.assertEqual((direction, len(edges)), ([0, 0, 1], 4))

    def test_edges_that_no_one_direction_tells_apart_are_split(self):
        one = self.two_sides()
        for record in (one.edges[1], one.edges[3]):
            side = record["sides"][0][1]
            record["cut_normals"] = [[2 * side[0], 2 * side[1], 4]]
        sides = one.sides()
        self.assertEqual([len(edges) for _, edges in sides], [2, 2])

    def test_an_edge_that_was_not_measured_gives_none(self):
        one = self.two_sides()
        del one.edges[0]["cut_normals"]
        self.assertIsNone(one.sides())


class MergeTest(unittest.TestCase):
    def test_parts_of_one_size_side_and_second_measure_join_and_others_stay_apart(self):
        a, b, c = Quantity(1.0), Quantity(1.0), Quantity(2.0)
        parts = [finish.Part(a, None, {}, [1], ["x"]), finish.Part(c, None, {}, [2]), finish.Part(b, None, {}, [3], ["y"]),
                 finish.Part(a, [0, 0, 1], {}, [4]), finish.Part(a, None, {}, []), finish.Part(Quantity(5.0), None, {}, [])]
        merged = finish.merge(parts)
        self.assertEqual([(p.size.n, p.direction, p.edges, p.sets) for p in merged],
                         [(1.0, None, [1, 3], ["x", "y"]), (2.0, None, [2], []), (1.0, [0, 0, 1], [4], [])])

    def test_a_size_that_follows_a_formula_joins_only_the_same_formula(self):
        first, same, other = Quantity(1.0, "a", ("a",)), Quantity(1.0, "a", ("a",)), Quantity(1.0, "b", ("b",))
        merged = finish.merge([finish.Part(first, None, {}, [1]), finish.Part(same, None, {}, [2]),
                               finish.Part(other, None, {}, [3])])
        self.assertEqual([p.edges for p in merged], [[1, 2], [3]])

    def test_the_second_measures_must_match(self):
        a = finish.Part(Quantity(1.0), None, {finish.DISTANCE: Quantity(2.0)}, [1])
        b = finish.Part(Quantity(1.0), None, {finish.DISTANCE: Quantity(3.0)}, [2])
        c = finish.Part(Quantity(1.0), None, {finish.DISTANCE: Quantity(2.0)}, [3])
        self.assertEqual([p.edges for p in finish.merge([a, b, c])], [[1, 3], [2]])


if __name__ == "__main__":
    unittest.main()
