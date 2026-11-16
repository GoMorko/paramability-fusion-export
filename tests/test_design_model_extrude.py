"""The shared extrude reader (`design_model/steps/extrude.py`): where an extrude starts, how each side ends, which way
it goes and how long it is, and the checks against what Fusion measured."""
import unittest

from tests import context  # noqa: F401

from lib.design_model.problem import is_problem
from lib.design_model.steps import extrude as dm

FRAME = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}


def plane_at(height, normal=(0.0, 0.0, 1.0), **more):
    return dict({"kind": "toEntity", "entity_type": "ConstructionPlane", "offset": 0.0,
                 "plane": {"point": [5.0, 5.0, height], "normal": list(normal)}}, **more)


def distance(value, **more):
    return dict({"kind": "distance", "distance": value, "taper_deg": 0.0}, **more)


def through(positive=True):
    return {"kind": "throughAll", "positive": positive, "taper_deg": 0.0}


def one(side, **data):
    return dict({"extent_type": "one", "side_one": side}, **data)


def two(first, second, **data):
    return dict({"extent_type": "two", "side_one": first, "side_two": second}, **data)


def sides(data, shift=0.0):
    return dm.read_sides(data, FRAME, shift)


def ways(found):
    return [(s.kind, s.sign, None if s.length is None else s.length.n) for s in found]


class StartTest(unittest.TestCase):
    def test_each_start(self):
        face = {"kind": "fromEntity", "entity_type": "BRepFace", "plane": {"point": [0, 0, 4.0], "normal": [0, 0, -1]}}
        self.assertEqual(dm.start_of({}, FRAME).kind, dm.SKETCH_PLANE)
        self.assertEqual(dm.start_of({"start": {"kind": "profilePlane"}}, FRAME).shift, 0.0)
        found = dm.start_of({"start": {"kind": "offset", "offset": -2.5}}, FRAME)
        self.assertEqual((found.kind, found.shift), (dm.OFFSET, -2.5))
        found = dm.start_of({"start": face}, FRAME)
        self.assertEqual((found.kind, found.shift, found.target.record), (dm.FACE, 4.0, face))

    def test_starts_that_cannot_be_read_or_placed(self):
        flat = {"kind": "fromEntity", "plane": {"point": [0, 0, 4.0], "normal": [0, 0, 1]}}
        cases = {
            dm.UNREADABLE: {"start": {"kind": "offset", "offset": None}},
            dm.START_KIND: {"start": {"kind": "other"}},
            dm.NOT_FLAT: {"start": {"kind": "fromEntity"}},
            dm.TILTED: {"start": dict(flat, plane={"point": [0, 0, 4.0], "normal": [0, 1, 1]})},
            dm.FOREIGN: {"start": dict(flat, foreign=True)},
            # Which way Fusion measures an offset from a face is not read.
            dm.START_OFFSET: {"start": flat, "params": {"start.offset": {"name": "d1", "expression": "1 mm",
                                                                            "value": 1.0}}},
        }
        for code, data in cases.items():
            with self.subTest(code=code):
                found = dm.start_of(data, FRAME)
                self.assertTrue(is_problem(found))
                self.assertEqual(found.code, code)


class OneSideTest(unittest.TestCase):
    def test_a_distance_goes_the_stored_way_until_the_end_face_says_otherwise(self):
        self.assertEqual(ways(sides(one(distance(-5.0)))), [(dm.DISTANCE, -1, 5.0)])
        turned = sides(one(distance(5.0), end_offset=-5.0))
        self.assertEqual(ways(turned), [(dm.DISTANCE, -1, 5.0)])
        self.assertTrue(turned[0].turned)
        # An end face on the start plane shows no direction.
        self.assertEqual(sides(one(distance(5.0), end_offset=-0.0005))[0].sign, 1)

    def test_a_set_direction_is_not_turned_by_the_end_face(self):
        found = sides(one(distance(5.0, direction=-1), end_offset=5.0))
        self.assertEqual(found[0].sign, -1)
        self.assertFalse(found[0].turned)

    def test_the_end_face_is_measured_from_where_the_extrude_starts(self):
        # A start 10 above the sketch with the end face at 7: the extrude goes 3 down.
        self.assertEqual(sides(one(distance(3.0), end_offset=7.0), shift=10.0)[0].sign, -1)

    def test_through_all_one_way(self):
        self.assertEqual(ways(sides(one(through(False)))), [(dm.THROUGH, -1, None)])
        self.assertEqual(sides(one(through(False), end_offset=12.0))[0].sign, 1)
        self.assertEqual(sides(one({"kind": "all"}, end_offset=-3.0))[0].sign, -1)

    def test_through_all_without_a_direction_is_not_read(self):
        for side in ({"kind": "all"}, through(None)):
            with self.subTest(side=side):
                self.assertEqual(sides(one(side)).code, dm.UNREADABLE)

    def test_a_side_to_a_plane_goes_toward_the_plane(self):
        found = sides(one(plane_at(-8.0, offset=1.0), end_offset=9.0))
        self.assertEqual(ways(found), [(dm.REACH, -1, 9.0)])
        self.assertEqual((found[0].reach.distance, found[0].offset), (-8.0, 1.0))
        # The end face on the other side does not turn it; the end check then finds it elsewhere.
        self.assertEqual(dm.end_check(found).fact, dm.ELSEWHERE)

    def test_a_side_to_a_plane_measures_from_the_start(self):
        self.assertEqual(ways(sides(one(plane_at(8.0)), shift=3.0)), [(dm.REACH, 1, 5.0)])

    def test_sides_that_cannot_be_read_or_placed(self):
        cases = {
            dm.NO_LENGTH: one(distance(0.0)),
            dm.UNREADABLE: one(distance(5.0, taper_deg=None)),
            dm.SIDE_KIND: one({"kind": "other"}),
            dm.EXTENT_KIND: {"extent_type": "other", "side_one": {"kind": "other"}},
            dm.ON_START: one(plane_at(0.0)),
            dm.TILTED: one(plane_at(8.0, normal=(1.0, 0.0, 1.0))),
            dm.NOT_FLAT: one({"kind": "toEntity", "offset": 0.0}),
        }
        for code, data in cases.items():
            with self.subTest(code=code):
                self.assertEqual(sides(data).code, code)
        self.assertEqual(sides(one(plane_at(2.0, offset=-3.0))).code, dm.NO_LENGTH)

    def test_the_taper_of_a_side_to_a_plane_comes_from_its_parameter_or_the_walls(self):
        held = {"side_one.taper_deg": {"name": "a", "expression": "3 deg", "value": 3.0}}
        self.assertEqual(sides(one(plane_at(8.0), params=held))[0].taper, 3.0)
        self.assertEqual(sides(one(plane_at(8.0), side_leans=[0.0, 0.0]))[0].taper, 0.0)
        # Straight walls show no taper even when the end face has another area (it merged with a face of the part).
        self.assertEqual(sides(one(plane_at(8.0), side_leans=[0.0], profile_area=4.0, end_area=9.0))[0].taper, 0.0)
        self.assertEqual(sides(one(plane_at(8.0), side_leans=[0.05])).code, dm.UNREADABLE)
        self.assertEqual(sides(one(plane_at(8.0), profile_area=4.0, end_area=3.0)).code, dm.UNREADABLE)


class SymmetricTest(unittest.TestCase):
    def test_half_and_full_lengths(self):
        half = {"extent_type": "symmetric", "symmetric": {"distance": 5.0, "full_length": False, "taper_deg": 0.0}}
        found = sides(half)
        self.assertEqual(ways(found), [(dm.SYMMETRIC, 1, 10.0)])
        self.assertEqual((found[0].path, found[0].value, found[0].scale), ("symmetric.distance", 5.0, 2.0))
        full = {"extent_type": "symmetric", "symmetric": {"distance": 5.0, "full_length": True, "taper_deg": 0.0}}
        self.assertEqual(sides(full)[0].length.n, 5.0)
        unread = {"extent_type": "symmetric", "symmetric": {"distance": 5.0, "full_length": None, "taper_deg": 0.0}}
        self.assertEqual(sides(unread).code, dm.UNREADABLE)

    def test_through_all_both_ways(self):
        found = sides({"extent_type": "symmetric", "side_one": dict(through(), taper_deg=2.0)})
        self.assertEqual([(s.kind, s.which, s.taper) for s in found], [(dm.THROUGH_BOTH, "symmetric", 2.0)])
        found = sides(two(through(), through(False)))
        self.assertEqual([s.kind for s in found], [dm.THROUGH_BOTH, dm.THROUGH_BOTH])


class TwoSidesTest(unittest.TestCase):
    def test_side_two_goes_against_side_one(self):
        self.assertEqual(ways(sides(two(distance(6.0), distance(4.0)))), [(dm.DISTANCE, 1, 6.0), (dm.DISTANCE, -1, 4.0)])

    def test_an_end_face_that_fits_the_stored_sides_keeps_them(self):
        # Side one goes 30 up, side two 10 down: a face 8 down lies in side two.
        self.assertEqual(sides(two(distance(30.0), distance(10.0), end_offset=-8.0))[0].sign, 1)

    def test_an_end_face_that_fits_only_the_turned_sides_turns_them(self):
        # A face 20 down cannot lie in side two (10 down), only in side one turned.
        found = sides(two(distance(30.0), distance(10.0), end_offset=-20.0))
        self.assertEqual([s.sign for s in found], [-1, 1])
        self.assertTrue(found[0].turned)

    def test_a_plane_of_either_side_sets_the_direction(self):
        self.assertEqual([s.sign for s in sides(two(distance(3.0), plane_at(5.0), end_offset=-3.0))], [-1, 1])
        self.assertEqual([s.sign for s in sides(two(plane_at(-5.0), distance(3.0)))], [-1, 1])

    def test_two_planes_on_one_side_are_not_read(self):
        found = sides(two(plane_at(5.0), plane_at(9.0)))
        self.assertEqual((found.code, found.cause), (dm.SAME_SIDE, dm.problem(dm.SAME_SIDE).cause))


def square(side):
    """A profile record of a square of `side` (mm), its four lines listed out of order and direction."""
    s = float(side)
    lines = [((0, 0), (s, 0)), ((0, s), (s, s)), ((s, 0), (s, s)), ((0, 0), (0, s))]
    return {"frame": FRAME, "loops": [{"outer": True, "curves": [
        {"kind": "line", "start": list(a), "end": list(b)} for a, b in lines]}]}


class EndCapTest(unittest.TestCase):
    def test_a_recorded_normal_decides(self):
        data = {"end_area": 1.0, "profiles": [square(10)]}
        self.assertTrue(dm.end_is_cap(dict(data, end_normal=[0, 0, -1]), [0, 0, 1]))
        self.assertFalse(dm.end_is_cap(dict(data, end_normal=[1, 0, 0]), [0, 0, 1]))

    def test_without_a_normal_the_area_must_be_an_outline_area(self):
        def cap(area, **more):
            return dm.end_is_cap(dict({"end_area": area, "profiles": [square(10), square(2)]}, **more), [0, 0, 1])
        self.assertTrue(cap(100.0))
        self.assertTrue(cap(4.0))
        self.assertTrue(cap(104.0))  # one face over both outlines
        self.assertFalse(cap(0.96))  # a wall the cut made
        # A taper or a thin wall gives a cap of another area; no area to compare is no answer.
        self.assertIsNone(cap(0.96, side_one=distance(5.0, taper_deg=3.0)))
        self.assertIsNone(cap(0.96, thin=True))
        self.assertIsNone(cap(None))
        self.assertIsNone(dm.end_is_cap({"end_area": 0.96, "profiles": [{"frame": FRAME, "text": True}]}, [0, 0, 1]))

    def test_a_face_that_is_not_a_cap_is_no_measure(self):
        wall = {"end_area": 0.96, "profiles": [square(10)]}
        # Two sides: the stored direction and lengths stand, and nothing is checked against the face.
        found = sides(two(distance(30.0), distance(10.0), end_offset=-4.0, **wall))
        self.assertEqual((ways(found), found[0].measured), ([(dm.DISTANCE, 1, 30.0), (dm.DISTANCE, -1, 10.0)], None))
        self.assertIsNone(dm.end_check(found))
        # One side: a face that would turn the stored direction cannot, so the direction is not known.
        self.assertEqual(sides(one(distance(5.0), end_offset=-3.0, **wall)).code, dm.WAY_UNSURE)
        self.assertEqual(ways(sides(one(distance(5.0), end_offset=3.0, **wall))), [(dm.DISTANCE, 1, 5.0)])


class EndCheckTest(unittest.TestCase):
    def test_one_side(self):
        self.assertEqual(dm.end_check(sides(one(distance(5.0), end_offset=5.0))).fact, dm.AT_END)
        short = dm.end_check(sides(one(distance(5.0), end_offset=3.0)))
        self.assertEqual((short.fact, short.way, short.at, short.length), (dm.SHORT, 1, 3.0, 5.0))
        self.assertEqual(dm.end_check(sides(one(distance(5.0), end_offset=6.0))).fact, dm.ELSEWHERE)
        self.assertIsNone(dm.end_check(sides(one(distance(5.0)))))
        self.assertIsNone(dm.end_check(sides(one(through(), end_offset=4.0))))

    def test_two_sides_check_the_side_the_face_lies_on(self):
        found = dm.end_check(sides(two(distance(30.0), distance(10.0), end_offset=-10.0)))
        self.assertEqual((found.fact, found.side.which, found.way), (dm.AT_END, "side_two", -1))
        found = dm.end_check(sides(two(distance(30.0), distance(10.0), end_offset=-4.0)))
        self.assertEqual((found.fact, found.side.which), (dm.SHORT, "side_two"))
        self.assertEqual(dm.end_check(sides(two(distance(3.0), distance(1.0), end_offset=0.0))).fact, dm.ELSEWHERE)

    def test_symmetric_checks_half_the_length(self):
        data = {"extent_type": "symmetric", "end_offset": -5.0,
                "symmetric": {"distance": 5.0, "full_length": False, "taper_deg": 0.0}}
        found = dm.end_check(sides(data))
        self.assertEqual((found.fact, found.way, found.length), (dm.AT_END, -1, 5.0))


def plan(sign=1, taper=0.0, kind=dm.DISTANCE, length=5.0):
    return dm.SidePlan(kind, "side_one", sign, dm.Quantity(length), taper)


class MeasuredTest(unittest.TestCase):
    def test_walls_show_the_taper(self):
        # A positive Fusion taper widens the outline: the outward normal of a wall leans against the travel.
        lean = -0.05233595624294383  # sin(3 degrees), against the travel
        self.assertIsNone(dm.taper_problem([plan(taper=3.0)], {"side_leans": [lean]}, "join", 1))
        self.assertEqual(dm.taper_problem([plan(taper=-3.0)], {"side_leans": [lean]}, "join", 1).code, dm.TAPER_WAY)
        # A cut shows the part's walls, which face the other way.
        self.assertIsNone(dm.taper_problem([plan(taper=-3.0)], {"side_leans": [lean]}, "cut", 1))
        self.assertEqual(dm.taper_problem([plan(taper=3.0)], {"side_leans": [0.0]}, "join", 1).code,
                         dm.TAPER_WAY)
        self.assertIsNone(dm.taper_problem([plan()], {}, "join", 1))

    def test_the_end_face_area_shows_the_taper_of_one_outline(self):
        narrows = {"profile_area": 4.0, "end_area": 3.0}
        self.assertIsNone(dm.taper_problem([plan(taper=-3.0)], narrows, "join", 1))
        self.assertEqual(dm.taper_problem([plan(taper=3.0)], narrows, "join", 1).code, dm.TAPER_WAY)
        self.assertEqual(dm.taper_problem([plan(taper=3.0)], {"profile_area": 4.0, "end_area": 4.0}, "join", 1).code,
                         dm.TAPER_NO_CHANGE)
        self.assertEqual(dm.taper_problem([plan(taper=3.0)], narrows, "join", 2).code, dm.TAPER_UNMEASURED)

    def test_walls_confirm_the_direction_of_a_tapered_side(self):
        lean = -0.05233595624294383
        self.assertTrue(dm.walls_confirm(plan(taper=-3.0), [lean], "cut"))
        self.assertFalse(dm.walls_confirm(plan(sign=-1, taper=-3.0), [lean], "cut"))
        self.assertFalse(dm.walls_confirm(plan(), [0.0], "cut"))

    def test_the_volume_of_spline_outlines(self):
        spline = [{"loops": [{"curves": [{"kind": "other"}]}]}]
        data = {"areas": [10.0], "volume_before": 0.0, "volume_after": 50.0}
        self.assertIsNone(dm.volume_problem(data, [plan()], "newBody", spline, False))
        self.assertEqual(dm.volume_problem(dict(data, volume_after=40.0), [plan()], "newBody", spline, False).code,
                         dm.VOLUME_DIFFERS)
        # A join may lose volume to material it overlaps, but must not shrink the part.
        self.assertIsNone(dm.volume_problem(dict(data, volume_after=30.0), [plan()], "join", spline, False))
        self.assertEqual(dm.volume_problem(dict(data, volume_after=-1.0), [plan()], "join", spline, False).code,
                         dm.VOLUME_DIFFERS)
        self.assertEqual(dm.volume_problem(dict(data, volume_after=None), [plan()], "newBody", spline, False).code,
                         dm.VOLUME_UNMEASURED)
        self.assertIsNone(dm.volume_problem(data, [plan()], "newBody", [{"loops": []}], False))


if __name__ == "__main__":
    unittest.main()
