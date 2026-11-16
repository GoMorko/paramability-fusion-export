"""The shared readers of holes and threads (`design_model/steps/hole.py` and `thread.py`): the facts both outputs use."""
import unittest

from tests import context  # noqa: F401

from lib.capture_model import gap_hints
from lib.design_model.problem import Problem
from lib.design_model.steps import hole, thread

INFO = {"thread_type": "ISO Metric profile", "internal": False, "right_hand": True, "pitch": 1.25,
        "major_diameter": 8.0, "minor_diameter": 6.5, "angle_deg": None}


def face(radius=4.0, span=(0.0, 10.0), origin=(20, 10, 0), axis=(0, 0, 1), outward=True, **more):
    return dict({"surface": "Cylinder", "origin": list(origin), "axis": list(axis), "radius": radius,
                 "span": list(span), "outward": outward}, **more)


def feature_data(**more):
    data = dict(INFO, modeled=True, full_length=True, length=10.0, offset=0.0, faces=[face()], made_span=None)
    data.update(more)
    return data


class ThreadSpecTest(unittest.TestCase):
    def test_a_metric_thread_gives_its_numbers(self):
        self.assertEqual(thread.spec_of(INFO, "t"), thread.Spec(1.25, 8.0, 6.5, True))

    def test_a_profile_that_is_not_the_60_degree_form_has_the_profile_cause(self):
        for change in ({"thread_type": "Acme"}, {"thread_type": "Trapezoidal"}, {"angle_deg": 29.0},
                       {"thread_type": "ISO Metric Taper"}):
            problem = thread.spec_of(dict(INFO, **change), "t")
            self.assertIsInstance(problem, Problem, change)
            self.assertEqual(problem.cause, gap_hints.THREAD_PROFILE, change)

    def test_a_number_that_is_missing_is_a_problem_and_never_a_guess(self):
        for key in ("pitch", "major_diameter", "minor_diameter", "right_hand", "thread_type"):
            self.assertIsInstance(thread.spec_of(dict(INFO, **{key: None}), "t"), Problem, key)

    def test_a_pitch_outside_the_range_a_destination_gives_has_the_limits_cause(self):
        problem = thread.spec_of(dict(INFO, pitch=0.1), "t", pitches=(0.2, 10.0))
        self.assertEqual(problem.cause, gap_hints.THREAD_LIMITS)
        self.assertIsInstance(thread.spec_of(dict(INFO, pitch=0.1), "t"), thread.Spec)

    def test_a_thread_with_no_depth_is_a_problem(self):
        self.assertIsInstance(thread.spec_of(dict(INFO, minor_diameter=8.0), "t"), Problem)
        self.assertIsInstance(thread.spec_of(dict(INFO, minor_diameter=7.99), "t"), Problem)

    def test_the_diameters_of_a_tapped_hole_come_from_the_hole_when_the_info_lacks_them(self):
        info = dict(INFO, major_diameter=None, minor_diameter=None)
        spec = thread.hole_spec({"thread": info, "diameter": 8.0}, "h", 6.6)
        self.assertEqual((spec.major, spec.minor), (8.0, 6.6))

    def test_a_thread_that_does_not_fit_the_measured_bore_is_a_problem(self):
        self.assertIsInstance(thread.hole_spec({"thread": INFO, "diameter": 8.0}, "h", 5.0), Problem)


class ThreadCylinderTest(unittest.TestCase):
    def test_two_halves_of_a_split_cylinder_make_one_span(self):
        found = thread.cylinder({"faces": [face(span=(0, 4)), face(span=(4, 10))]})
        self.assertEqual(found.span, (0, 10))

    def test_a_face_turned_the_other_way_is_measured_along_the_first_axis(self):
        found = thread.cylinder({"faces": [face(span=(0, 4)), face(span=(0, 6), origin=(20, 10, 10), axis=(0, 0, -1))]})
        self.assertEqual(found.span, (0, 10))

    def test_faces_that_leave_a_gap_are_a_problem(self):
        self.assertEqual(thread.cylinder({"faces": [face(span=(0, 3)), face(span=(5, 10))]}).code, "facesApart")

    def test_faces_of_two_cylinders_are_a_problem(self):
        self.assertEqual(thread.cylinder({"faces": [face(), face(radius=5.0)]}).code, "notOneCylinder")

    def test_a_face_that_is_not_a_cylinder_is_a_problem_before_one_of_another_component(self):
        data = {"faces": [dict(face(), surface="Plane", foreign=True)]}
        self.assertEqual(thread.cylinder(data).code, "notCylinder")

    def test_a_face_of_another_component_has_its_own_cause(self):
        problem = thread.cylinder({"faces": [dict(face(), foreign=True)]})
        self.assertEqual(problem.cause, gap_hints.OTHER_COMPONENT)


class ThreadFeatureTest(unittest.TestCase):
    def test_a_full_length_outside_thread_starts_at_the_low_end(self):
        found = thread.read_feature(feature_data(), "t")
        self.assertEqual((found.internal, found.full, found.start), (False, True, 0))

    def test_the_side_is_told_from_the_faces_when_the_info_does_not_say(self):
        found = thread.read_feature(feature_data(internal=None, faces=[face(radius=3.25, outward=False)]), "t")
        self.assertTrue(found.internal)

    def test_a_side_that_the_faces_contradict_is_a_problem(self):
        self.assertIsInstance(thread.read_feature(feature_data(internal=True), "t"), Problem)

    def test_a_cylinder_that_is_not_the_thread_size_is_a_problem(self):
        self.assertEqual(thread.read_feature(feature_data(faces=[face(radius=6.0)]), "t").code, "cylinderSize")

    def test_a_thread_that_starts_away_from_the_end_is_a_problem(self):
        self.assertEqual(thread.read_feature(feature_data(offset=1.0), "t").code, "offset")
        self.assertEqual(thread.read_feature(feature_data(offset=None), "t").code, "offset")

    def test_a_partial_thread_starts_at_the_end_its_made_faces_touch(self):
        low = thread.read_feature(feature_data(full_length=False, length=5.0, made_span=[0.0, 5.0]), "t")
        high = thread.read_feature(feature_data(full_length=False, length=5.0, made_span=[5.0, 10.0]), "t")
        self.assertEqual((low.start, high.start), (0, 1))

    def test_a_partial_thread_that_touches_neither_end_is_a_problem(self):
        found = thread.read_feature(feature_data(full_length=False, length=2.0, made_span=[4.0, 6.0]), "t")
        self.assertEqual(found.code, "startUnclear")

    def test_the_set_length_tells_a_full_thread_when_the_flag_is_missing(self):
        self.assertTrue(thread.is_full({}, (0, 10), 10.0))
        self.assertFalse(thread.is_full({}, (0, 10), 4.0))
        self.assertIsNone(thread.is_full({}, (0, 10), None))


class ThreadOfAHoleTest(unittest.TestCase):
    def test_the_depth_is_the_whole_hole_or_a_length_and_never_a_guess(self):
        self.assertEqual(thread.hole_depth({"thread": {"full_length": True}}), thread.Depth(True, None))
        self.assertEqual(thread.hole_depth({"thread": {"full_length": False, "depth": 6}}), thread.Depth(False, 6.0))
        self.assertIsInstance(thread.hole_depth({"thread": {"full_length": False}}), Problem)
        self.assertIsInstance(thread.hole_depth({"thread": {}}), Problem)

    def test_each_position_needs_a_measured_end(self):
        self.assertEqual(thread.measured_ends({"end_points": [[0, 0, 1], [1, 0, 1]]}, 2), [[0, 0, 1], [1, 0, 1]])
        self.assertIsInstance(thread.measured_ends({"end_points": [[0, 0, 1]]}, 2), Problem)


def hole_data(**more):
    data = {"hole_type": "simple", "tap_type": "simple", "diameter": 5.0, "positions": [[0, 0, 10], [10, 0, 10]],
            "direction": [0, 0, -1], "extent": {"kind": "distance", "depth": 8.0}}
    data.update(more)
    return data


class HoleKindTest(unittest.TestCase):
    def test_a_recess_comes_with_its_record(self):
        record = {"diameter": 9.0, "depth": 3.0}
        self.assertEqual(hole.kind_of(hole_data(hole_type="counterbore", counterbore=record)),
                         hole.Kind(hole.COUNTERBORE, record))
        self.assertEqual(hole.kind_of(hole_data()), hole.Kind(hole.SIMPLE, None))

    def test_a_kind_that_is_unknown_or_has_no_record_is_a_problem(self):
        self.assertIsInstance(hole.kind_of(hole_data(hole_type="counterdrill")), Problem)
        self.assertIsInstance(hole.kind_of(hole_data(hole_type="countersink")), Problem)

    def test_a_clearance_hole_is_plain_and_a_tapered_one_is_its_own_kind(self):
        self.assertEqual(hole.tap_of({"tap_type": "clearance"}), hole.PLAIN)
        self.assertEqual(hole.tap_of({"tap_type": "tapped"}), hole.TAPPED)
        self.assertEqual(hole.tap_of({"tap_type": "taperTapped"}), hole.TAPERED)
        self.assertIsInstance(hole.tap_of({"tap_type": "other"}), Problem)

    def test_the_depth_is_a_distance_above_zero_through_all_or_up_to_a_face(self):
        self.assertEqual(hole.extent_of(hole_data()), hole.Extent(hole.DISTANCE, 8.0))
        self.assertEqual(hole.extent_of(hole_data(extent={"kind": "throughAll"})), hole.Extent(hole.THROUGH_ALL, None))
        self.assertEqual(hole.extent_of(hole_data(extent={"kind": "toEntity"})).kind, hole.TO_ENTITY)
        self.assertIsInstance(hole.extent_of(hole_data(extent={"kind": "distance", "depth": 0})), Problem)
        self.assertIsInstance(hole.extent_of(hole_data(extent={"kind": "toOffset"})), Problem)

    def test_a_hole_with_no_position_direction_or_size_is_a_problem(self):
        self.assertIsNone(hole.placed(hole_data()))
        for change in ({"positions": []}, {"direction": None}, {"diameter": 0}, {"diameter": None}):
            self.assertIsInstance(hole.placed(hole_data(**change)), Problem, change)


class HoleDirectionTest(unittest.TestCase):
    def test_the_stored_direction_stands_when_the_measured_ends_lie_ahead(self):
        found = hole.direction_of(hole_data(end_points=[[0, 0, 2], [10, 0, 2]]))
        self.assertEqual((found.unit, found.flipped), ([0.0, 0.0, -1.0], False))

    def test_the_stored_direction_is_turned_when_a_measured_end_lies_behind(self):
        found = hole.direction_of(hole_data(end_points=[[0, 0, 18], [10, 0, 18]]))
        self.assertEqual((found.unit, found.flipped), ([0.0, 0.0, 1.0], True))

    def test_a_hole_with_no_measured_end_keeps_its_direction(self):
        self.assertFalse(hole.direction_of(hole_data()).flipped)

    def test_the_depth_to_a_face_is_the_measured_flat_end_distance(self):
        data = hole_data(end_points=[[0, 0, 2], [10, 0, 2]], end_face_types=["plane", "plane"])
        self.assertAlmostEqual(hole.reach_depth(data, [0.0, 0.0, -1.0]), 8.0)

    def test_the_depth_to_a_face_needs_flat_ends_of_one_depth(self):
        pointed = hole_data(end_points=[[0, 0, 2], [10, 0, 2]], end_face_types=["cone"])
        uneven = hole_data(end_points=[[0, 0, 2], [10, 0, 4]], end_face_types=["plane"])
        missing = hole_data(end_points=[[0, 0, 2]], end_face_types=["plane"])
        for data in (pointed, uneven, missing):
            self.assertIsInstance(hole.reach_depth(data, [0.0, 0.0, -1.0]), Problem)


class HoleMeasureTest(unittest.TestCase):
    def test_the_drill_size_is_the_widest_cylinder_not_wider_than_the_stored_size(self):
        data = hole_data(diameter=6.0, side_cylinders=[{"radius": 2.5}, {"radius": 5.0}, {"radius": 3.0}])
        self.assertEqual(hole.drill_diameter(data), 6.0)
        self.assertIsNone(hole.drill_diameter(hole_data()))
        self.assertIsNone(hole.drill_diameter(hole_data(side_cylinders=[{"radius": 9.0}])))

    def test_a_measured_size_that_differs_from_the_stored_one_is_a_fact(self):
        self.assertFalse(hole.size_differs(hole_data(side_cylinders=[{"radius": 2.5}, {"radius": 2.5}]), 2, 5.0))
        self.assertTrue(hole.size_differs(hole_data(side_cylinders=[{"radius": 3.0}, {"radius": 3.0}]), 2, 5.0))
        self.assertTrue(hole.size_differs(hole_data(side_cylinders=[{"radius": 2.5}]), 2, 5.0))
        self.assertFalse(hole.size_differs(hole_data(), 2, 5.0))

    def test_the_end_shape_is_the_measured_one(self):
        self.assertIsNone(hole.end_shape({}))
        self.assertEqual(hole.end_shape({"end_face_types": ["cone", "cone"]}), hole.CONE)
        self.assertEqual(hole.end_shape({"end_face_types": ["plane"]}), hole.PLANE)
        self.assertEqual(hole.end_shape({"end_face_types": ["plane", "cone"]}), hole.MIXED)


class TappedBoreTest(unittest.TestCase):
    def test_a_cosmetic_thread_is_drilled_at_the_measured_size_with_no_spec(self):
        data = hole_data(tap_type="tapped", thread_modeled=False, diameter=6.0, side_cylinders=[{"radius": 2.5}])
        self.assertEqual(hole.tapped_bore(data, "h"), (5.0, None))

    def test_a_modeled_thread_is_cut_at_its_minor_diameter(self):
        data = hole_data(tap_type="tapped", thread_modeled=True, diameter=8.0, thread=INFO,
                         side_cylinders=[{"radius": 3.25}])
        bore, spec = hole.tapped_bore(data, "h")
        self.assertEqual((bore, spec.major), (6.5, 8.0))

    def test_a_tapered_thread_has_the_profile_cause(self):
        problem = hole.tapped_bore(hole_data(tap_type="taperTapped", thread_modeled=True), "h")
        self.assertEqual(problem.cause, gap_hints.THREAD_PROFILE)

    def test_a_thread_nobody_read_or_a_drill_nobody_measured_is_a_problem(self):
        self.assertIsInstance(hole.tapped_bore(hole_data(tap_type="tapped", thread_modeled=None), "h"), Problem)
        self.assertIsInstance(hole.tapped_bore(hole_data(tap_type="tapped", thread_modeled=False), "h"), Problem)


if __name__ == "__main__":
    unittest.main()
