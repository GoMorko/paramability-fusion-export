"""The shared extrude reader (`design_model/steps/extrude.py`): where an extrude starts, how each side ends, which way
it goes and how long it is, and the checks against what Fusion measured."""
import unittest

from tests import context  # noqa: F401

from lib.design_model.problem import is_problem
from lib.design_model.steps import extrude as dm
from lib.design_model.steps import extrude_checks as dmc

FRAME = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}


def plane_at(height, normal=(0.0, 0.0, 1.0), **more):
    return dict({"kind": "toEntity", "entity_type": "ConstructionPlane", "offset": 0.0,
                 "plane": {"point": [5.0, 5.0, height], "normal": list(normal)}}, **more)


def face_at(point, **more):
    """A face of the part that a side reaches to, flat when `plane` is given."""
    return dict({"kind": "toEntity", "entity_type": "BRepFace", "offset": 0.0, "face_point": list(point)}, **more)


def curved_at(point, **more):
    """A curved face of the part with Chain Faces off that every outline meets."""
    return face_at(point, **dict({"surface": "Cylinder", "chained": False, "outline_hits_face": True}, **more))


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

    def test_an_offset_from_a_face_takes_the_sign_the_measured_start_face_shows(self):
        flat = {"kind": "fromEntity", "plane": {"point": [0, 0, 4.0], "normal": [0, 0, 1]}}

        def start(offset, measured):
            data = {"start": flat, "start_offset": measured,
                    "params": {"start.offset": {"name": "d1", "expression": "%g mm" % offset, "value": offset}}}
            return dm.start_of(data, FRAME, offsets=True)

        found = start(2.0, 6.0)
        self.assertEqual((found.kind, found.shift, found.offset, found.way, found.target.distance),
                         (dm.FACE, 6.0, 2.0, 1, 4.0))
        found = start(2.0, 2.0)
        self.assertEqual((found.shift, found.offset, found.way), (2.0, -2.0, -1))
        # No sign puts the start there, nothing was measured, or both signs fit an offset of almost nothing.
        for offset, measured in ((2.0, 5.0), (2.0, None), (1e-4, 4.0)):
            with self.subTest(offset=offset, measured=measured):
                self.assertEqual(start(offset, measured).code, dm.START_OFFSET)


    def test_without_a_start_face_the_end_cap_of_a_join_places_the_offset_start(self):
        flat = {"kind": "fromEntity", "plane": {"point": [0, 0, 10.0], "normal": [0, 0, 1]}}

        def start(end, side=None, **more):
            data = dict({"start": flat, "start_offset": None, "end_offset": end, "end_normal": [0.0, 0.0, 1.0],
                         "extent_type": "one", "side_one": side or distance(5.0),
                         "params": {"start.offset": {"name": "d1", "expression": "-2 mm", "value": -2.0}}}, **more)
            return dm.start_of(data, FRAME, offsets=True)

        # The start 2 mm into the part (z 8) and 5 mm up is the only start and way that end at 13.
        found = start(13.0)
        self.assertEqual((found.shift, found.offset, found.way), (8.0, -2.0, 1))
        self.assertEqual(start(7.0).shift, 12.0)
        cases = [
            start(10.0),  # no start and way end there
            start(13.0, end_normal=[1.0, 0.0, 0.0]),  # the measured face is no end cap
            start(13.0, side=plane_at(13.0)),  # a side up to a plane: its end does not tell where it starts
            start(13.0, extent_type="symmetric"),
        ]
        for found in cases:
            with self.subTest(found=found):
                self.assertEqual(found.code, dm.START_OFFSET)
        # An offset as long as the side: 12 - 2 and 8 + 2 both end at 10.
        self.assertEqual(start(10.0, side=distance(2.0)).code, dm.START_OFFSET)


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
        self.assertEqual(dmc.end_check(found).fact, dm.ELSEWHERE)

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

    def test_a_tilted_or_curved_face_of_the_part_is_an_up_to_side_only_when_asked(self):
        tilted = face_at([2.0, 0.0, 8.0], plane={"point": [0, 0, 8.0], "normal": [1.0, 0.0, 1.0]}, chained=False)
        self.assertEqual(sides(one(tilted)).code, dm.TILTED)
        (found,) = dm.read_sides(one(tilted), FRAME, faces=True)
        self.assertEqual((found.kind, found.sign, found.length, found.reach.distance), (dm.UP_TO, 1, None, 8.0))
        self.assertEqual(found.reach.plane, tilted["plane"])
        (found,) = dm.read_sides(one(curved_at([0.0, 0.0, -6.0]), end_offset=-5.0), FRAME, faces=True)
        self.assertEqual((found.kind, found.sign, found.reach.plane), (dm.UP_TO, -1, None))

    def test_a_face_fusion_may_chain_is_read_only_when_every_outline_lands_on_it(self):
        def ring(corners, outer=True):
            return {"outer": outer, "curves": [{"kind": "line", "start": a, "end": b}
                                               for a, b in zip(corners, corners[1:] + corners[:1])]}

        def rect(x0, y0, x1, y1, outer=True):
            return ring([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], outer)

        def face(*loops, chained=True):
            frame = {"origin": [0.0, 0.0, 8.0], "x": [1.0, 0.0, 0.0], "y": [0.0, -1.0, 0.0], "z": [0.0, 0.0, -1.0]}
            return dict(face_at([1.0, -1.0, 8.0], plane={"point": [0, 0, 8.0], "normal": [0, 0, -1.0]},
                                chained=chained), face_outline={"frame": frame, "loops": list(loops)})

        square = {"frame": FRAME, "loops": [rect(0.0, 0.0, 4.0, 4.0)]}
        cases = [
            (face(rect(-1.0, 1.0, 5.0, -5.0)), dm.REACH),
            # The face ends right at the outline's edge.
            (face(rect(0.0, 0.0, 4.0, -4.0)), dm.REACH),
            (face(rect(-1.0, 1.0, 3.0, -5.0)), dm.CHAINED),
            # A hole of the face under the outline.
            (face(rect(-1.0, 1.0, 5.0, -5.0), rect(1.0, -1.0, 2.0, -2.0, outer=False)), dm.CHAINED),
            # A slot of the face crosses the outline, its corners and the outline's corners all outside the other: one
            # open to the face's edge, one closed.
            (face(ring([[-1.0, 1.0], [1.5, 1.0], [1.5, -4.5], [2.5, -4.5], [2.5, 1.0], [5.0, 1.0], [5.0, -5.0],
                        [-1.0, -5.0]])), dm.CHAINED),
            (face(rect(-1.0, 1.0, 5.0, -5.0), rect(1.5, 0.5, 2.5, -4.5, outer=False)), dm.CHAINED),
            (dict(face_at([1.0, 1.0, 8.0], plane={"point": [0, 0, 8.0], "normal": [0, 0, 1.0]}, chained=None)),
             dm.CHAINED),
            # Fusion extends the face to its plane: no outline is needed.
            (face(rect(-1.0, 1.0, 3.0, -5.0), chained=False), dm.REACH),
        ]
        for side, kind in cases:
            with self.subTest(side=side):
                found = sides(one(side, profiles=[square]))
                self.assertEqual(found.code if is_problem(found) else found[0].kind, kind)

    def test_the_outline_of_a_tilted_face_is_moved_onto_the_sketch_along_the_sketch_normal(self):
        # The face leans 45 degrees: the 4 mm square sketch lands on it 5.66 mm long (u 0 to 5.66, v 0 to 4). A slot
        # of the face crosses it with no corner inside; a round hole beside it becomes an ellipse on the sketch.
        r = 2 ** 0.5 / 2
        frame = {"origin": [0.0, 0.0, 0.0], "x": [r, 0.0, -r], "y": [0.0, 1.0, 0.0], "z": [r, 0.0, r]}

        def ring(*corners):
            return [{"kind": "line", "start": a, "end": b} for a, b in zip(corners, corners[1:] + corners[:1])]

        square = ring([0, 0], [4, 0], [4, 4], [0, 4])
        data = {"profiles": [{"frame": FRAME, "loops": [{"outer": True, "curves": square}]}]}
        face = ring([-1, -1], [7, -1], [7, 5], [-1, 5])
        slot = ring([2.5, -0.5], [3, -0.5], [3, 4.5], [2.5, 4.5])
        beside = [{"kind": "circle", "center": [6.3, 2.0], "radius": 0.5}]
        for hole, lands in ((beside, True), (slot, False)):
            with self.subTest(lands=lands):
                record = {"face_outline": {"frame": frame, "loops": [{"outer": True, "curves": face},
                                                                     {"outer": False, "curves": hole}]}}
                self.assertIs(dm.outline_on_face(data, record, [0.0, 0.0, 1.0]), lands)

    def test_a_face_without_a_plane_is_read_only_when_it_is_curved_and_every_outline_meets_it(self):
        cases = [
            (curved_at([0.0, 0.0, 6.0]), dm.UP_TO),
            # A flat face whose plane did not read, or a face whose surface did not read.
            (curved_at([0.0, 0.0, 6.0], surface="Plane"), dm.FACE_UNREAD),
            (curved_at([0.0, 0.0, 6.0], surface=None), dm.FACE_UNREAD),
            # Fusion may also stop at the faces next to it, which no outline of a curved face shows.
            (curved_at([0.0, 0.0, 6.0], chained=True), dm.CHAINED),
            (curved_at([0.0, 0.0, 6.0], chained=None), dm.CHAINED),
            # Fusion extends the face where the outline reaches past it; the app takes the face as it is.
            (curved_at([0.0, 0.0, 6.0], outline_hits_face=False), dm.PAST_CURVED),
            (curved_at([0.0, 0.0, 6.0], outline_hits_face=None), dm.PAST_CURVED),
        ]
        for side, kind in cases:
            with self.subTest(side=side):
                found = dm.read_sides(one(side, end_offset=5.0), FRAME, faces=True)
                self.assertEqual(found.code if is_problem(found) else found[0].kind, kind)

    def test_the_body_a_join_grew_shows_the_way_when_no_end_face_does(self):
        def body(low, high, volume):
            return {"box": {"min": [0.0, 0.0, low], "max": [60.0, 40.0, high]}, "volume_mm3": volume}

        before = body(-20.0, 0.0, 1000.0)
        below = (before, body(-20.0, 0.0, 1100.0))
        wall = {"end_area": 0.96, "profiles": [square(10)]}
        cases = [
            # A join up to a curved face below the sketch: Fusion gives no end face, the body lies below the sketch.
            (one(curved_at([0.0, 0.0, -6.0]), operation="join"), below, (dm.UP_TO, -1)),
            # A distance whose measured face is no end cap and would turn the stored way.
            (one(distance(5.0), end_offset=-3.0, operation="join", **wall), below, (dm.DISTANCE, -1)),
            # The body lies on both sides of the sketch, it did not grow, or it is not a join.
            (one(curved_at([0.0, 0.0, -6.0]), operation="join"), (before, body(-20.0, 4.0, 1100.0)), dm.WAY_UNSURE),
            (one(curved_at([0.0, 0.0, -6.0]), operation="join"), (before, before), dm.WAY_UNSURE),
            (one(curved_at([0.0, 0.0, -6.0]), operation="cut"), below, dm.WAY_UNSURE),
            # The face lies above the sketch but the body only below it.
            (one(curved_at([0.0, 0.0, 6.0]), operation="join"), below, dm.WAY_UNSURE),
            (one(distance(5.0), end_offset=-3.0, operation="join", **wall), (None, None), dm.WAY_UNSURE),
            # A join whose end cap merged: the stored direction must agree with the body it grew.
            (one(distance(-5.0), operation="join"), below, (dm.DISTANCE, -1)),
            (one(distance(5.0), operation="join"), below, dm.WAY_UNSURE),
        ]
        for data, bodies, expected in cases:
            with self.subTest(data=data, bodies=bodies):
                found = dm.read_sides(data, FRAME, faces=True, bodies=bodies)
                self.assertEqual(found.code if is_problem(found) else (found[0].kind, found[0].sign), expected)

    def test_up_to_sides_that_stay_problems(self):
        tilted = {"point": [0, 0, 8.0], "normal": [1.0, 0.0, 1.0]}
        cases = [
            # A curved face can lie on both sides of the sketch: the measured end face must show the way.
            (dm.WAY_UNSURE, one(curved_at([0.0, 0.0, 6.0]), end_offset=-5.0)),
            (dm.WAY_UNSURE, one(curved_at([0.0, 0.0, 6.0]))),
            (dm.ON_START, one(face_at([3.0, 0.0, 0.0], plane=tilted))),
            (dm.TILTED, one(plane_at(8.0, normal=(1.0, 0.0, 1.0)))),
            (dm.TILTED, two(face_at([0.0, 0.0, 8.0], plane=tilted), distance(2.0))),
            (dm.FOREIGN, one(face_at([0.0, 0.0, 8.0], plane=tilted, foreign=True))),
        ]
        for code, data in cases:
            with self.subTest(code=code, data=data):
                self.assertEqual(dm.read_sides(data, FRAME, faces=True).code, code)

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
        self.assertIsNone(dmc.end_check(found))
        # One side: a face that would turn the stored direction cannot, so the direction is not known.
        self.assertEqual(sides(one(distance(5.0), end_offset=-3.0, **wall)).code, dm.WAY_UNSURE)
        self.assertEqual(ways(sides(one(distance(5.0), end_offset=3.0, **wall))), [(dm.DISTANCE, 1, 5.0)])


class EndCheckTest(unittest.TestCase):
    def test_one_side(self):
        self.assertEqual(dmc.end_check(sides(one(distance(5.0), end_offset=5.0))).fact, dm.AT_END)
        short = dmc.end_check(sides(one(distance(5.0), end_offset=3.0)))
        self.assertEqual((short.fact, short.way, short.at, short.length), (dm.SHORT, 1, 3.0, 5.0))
        self.assertEqual(dmc.end_check(sides(one(distance(5.0), end_offset=6.0))).fact, dm.ELSEWHERE)
        self.assertIsNone(dmc.end_check(sides(one(distance(5.0)))))
        self.assertIsNone(dmc.end_check(sides(one(through(), end_offset=4.0))))

    def test_two_sides_check_the_side_the_face_lies_on(self):
        found = dmc.end_check(sides(two(distance(30.0), distance(10.0), end_offset=-10.0)))
        self.assertEqual((found.fact, found.side.which, found.way), (dm.AT_END, "side_two", -1))
        found = dmc.end_check(sides(two(distance(30.0), distance(10.0), end_offset=-4.0)))
        self.assertEqual((found.fact, found.side.which), (dm.SHORT, "side_two"))
        self.assertEqual(dmc.end_check(sides(two(distance(3.0), distance(1.0), end_offset=0.0))).fact, dm.ELSEWHERE)

    def test_symmetric_checks_half_the_length(self):
        data = {"extent_type": "symmetric", "end_offset": -5.0,
                "symmetric": {"distance": 5.0, "full_length": False, "taper_deg": 0.0}}
        found = dmc.end_check(sides(data))
        self.assertEqual((found.fact, found.way, found.length), (dm.AT_END, -1, 5.0))


def plan(sign=1, taper=0.0, kind=dm.DISTANCE, length=5.0):
    return dm.SidePlan(kind, "side_one", sign, dm.Quantity(length), taper)


class MeasuredTest(unittest.TestCase):
    def test_walls_show_the_taper(self):
        # A positive Fusion taper widens the outline: the outward normal of a wall leans against the travel.
        lean = -0.05233595624294383  # sin(3 degrees), against the travel
        self.assertIsNone(dmc.taper_problem([plan(taper=3.0)], {"side_leans": [lean]}, "join", 1))
        self.assertEqual(dmc.taper_problem([plan(taper=-3.0)], {"side_leans": [lean]}, "join", 1).code, dm.TAPER_WAY)
        # A cut shows the part's walls, which face the other way.
        self.assertIsNone(dmc.taper_problem([plan(taper=-3.0)], {"side_leans": [lean]}, "cut", 1))
        self.assertEqual(dmc.taper_problem([plan(taper=3.0)], {"side_leans": [0.0]}, "join", 1).code,
                         dm.TAPER_WAY)
        self.assertIsNone(dmc.taper_problem([plan()], {}, "join", 1))

    def test_the_end_face_area_shows_the_taper_of_one_outline(self):
        narrows = {"profile_area": 4.0, "end_area": 3.0}
        self.assertIsNone(dmc.taper_problem([plan(taper=-3.0)], narrows, "join", 1))
        self.assertEqual(dmc.taper_problem([plan(taper=3.0)], narrows, "join", 1).code, dm.TAPER_WAY)
        self.assertEqual(dmc.taper_problem([plan(taper=3.0)], {"profile_area": 4.0, "end_area": 4.0}, "join", 1).code,
                         dm.TAPER_NO_CHANGE)
        self.assertEqual(dmc.taper_problem([plan(taper=3.0)], narrows, "join", 2).code, dm.TAPER_UNMEASURED)

    def test_walls_confirm_the_direction_of_a_tapered_side(self):
        lean = -0.05233595624294383
        self.assertTrue(dmc.walls_confirm(plan(taper=-3.0), [lean], "cut"))
        self.assertFalse(dmc.walls_confirm(plan(sign=-1, taper=-3.0), [lean], "cut"))
        self.assertFalse(dmc.walls_confirm(plan(), [0.0], "cut"))

    def test_the_volume_of_spline_outlines(self):
        spline = [{"loops": [{"curves": [{"kind": "other"}]}]}]
        data = {"areas": [10.0], "volume_before": 0.0, "volume_after": 50.0}
        self.assertIsNone(dmc.volume_problem(data, [plan()], "newBody", spline, False))
        self.assertEqual(dmc.volume_problem(dict(data, volume_after=40.0), [plan()], "newBody", spline, False).code,
                         dm.VOLUME_DIFFERS)
        # A join may lose volume to material it overlaps, but must not shrink the part.
        self.assertIsNone(dmc.volume_problem(dict(data, volume_after=30.0), [plan()], "join", spline, False))
        self.assertEqual(dmc.volume_problem(dict(data, volume_after=-1.0), [plan()], "join", spline, False).code,
                         dm.VOLUME_DIFFERS)
        self.assertEqual(dmc.volume_problem(dict(data, volume_after=None), [plan()], "newBody", spline, False).code,
                         dm.VOLUME_UNMEASURED)
        self.assertIsNone(dmc.volume_problem(data, [plan()], "newBody", [{"loops": []}], False))


if __name__ == "__main__":
    unittest.main()
