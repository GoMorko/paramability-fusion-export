"""Reader of free curves (splines, elliptical arcs) and of sketch text outlines."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, Obj, P, line, matrix, profile_of, rect_profile

from lib.fusion_reader import read_sketch


def curve_on(trace, extents=(0.0, 1.0), kind="NurbsCurve3D"):
    """A free curve whose evaluator follows `trace(t) -> (x, y)` in mm, with a tangent from a small step."""
    def tangent(t):
        a, b = trace(t - 1e-6), trace(t + 1e-6)
        return True, Obj(x=b[0] - a[0], y=b[1] - a[1], z=0.0)

    evaluator = Obj(getParameterExtents=lambda: (True,) + extents,
                    getPointAtParameter=lambda t: (True, P(*trace(t))), getTangent=tangent)
    return Obj("core::" + kind, evaluator=evaluator)


def half_circle(t):
    return 10 * math.cos(math.pi * t), 10 * math.sin(math.pi * t)


def read_curves(geometries, sketch=None):
    return read_sketch.read_profile(profile_of(geometries, sketch))["loops"][0]["curves"]


def chord_error(samples, radius=10.0):
    """Largest gap between the middle of a sample span and the circle the samples lie on."""
    return max(abs(math.hypot((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0) - radius) for a, b in zip(samples, samples[1:]))


class FreeCurveTest(unittest.TestCase):
    def test_a_bend_gets_more_samples_than_a_straight_run(self):
        bent = read_curves([curve_on(half_circle)])[0]
        straight = read_curves([curve_on(lambda t: (30 * t, 2 * t))])[0]
        self.assertGreater(len(bent["samples"]), 3 * len(straight["samples"]))
        self.assertEqual((bent["start"], bent["end"]), ([10.0, 0.0], [-10.0, 0.0]))
        self.assertLess(chord_error(bent["samples"]), 0.001)

    def test_the_middle_is_a_sample_and_the_end_directions_are_kept(self):
        got = read_curves([curve_on(half_circle)])[0]
        self.assertIn(got["mid"], got["samples"])
        self.assertAlmostEqual(got["tangent_start"][1], 1.0, places=4)
        self.assertAlmostEqual(got["tangent_end"][1], -1.0, places=4)

    def test_an_elliptical_arc_is_read_like_any_other_free_curve(self):
        got = read_curves([curve_on(half_circle, kind="EllipticalArc3D")])[0]
        self.assertEqual((got["kind"], got["type"]), ("other", "EllipticalArc3D"))

    def test_samples_stop_at_the_cap_and_the_curve_says_so(self):
        original = read_sketch._MAX_SAMPLES
        read_sketch._MAX_SAMPLES = 40
        try:
            got = read_curves([curve_on(half_circle)])[0]
        finally:
            read_sketch._MAX_SAMPLES = original
        self.assertTrue(got["truncated"])
        self.assertLessEqual(len(got["samples"]), 40 + 16)

    def test_a_curve_that_cannot_be_evaluated_has_no_samples(self):
        broken = Obj("core::NurbsCurve3D", evaluator=Obj(getParameterExtents=lambda: (False, 0.0, 1.0)))
        got = read_curves([broken])[0]
        self.assertEqual((got["samples"], got["start"], got["end"]), ([], None, None))

    def test_an_end_direction_that_cannot_be_read_is_left_out(self):
        geometry = curve_on(half_circle)
        geometry.evaluator.getTangent = lambda t: (False, None)
        got = read_curves([geometry])[0]
        self.assertNotIn("tangent_start", got)
        self.assertTrue(got["samples"])

    def test_the_space_of_a_spline_only_outline_comes_from_its_sketch_entity(self):
        flipped = matrix(y=(0, -1, 0), z=(0, 0, -1))
        sketch = Obj("fusion::Sketch", name="Bottom", transform=flipped,
                     modelToSketchSpace=lambda p: Obj(x=p.x, y=-p.y, z=-p.z))

        def profile(entity_geometry):
            curve = Obj(geometry=curve_on(half_circle), sketchEntity=Obj(geometry=entity_geometry))
            loop = Obj(isOuter=True, profileCurves=Coll([curve]))
            return read_sketch.read_profile(Obj("fusion::Profile", parentSketch=sketch, profileLoops=Coll([loop])))

        self.assertEqual(profile(curve_on(half_circle))["space"], "sketch")
        self.assertEqual(profile(curve_on(lambda t: (10 * math.cos(math.pi * t), -10 * math.sin(math.pi * t))))["space"],
                         "model")


class TextOutlinesTest(unittest.TestCase):
    def sketch(self, **kw):
        fields = dict(name="Sketch2", entityToken="sk2", transform=matrix(), modelToSketchSpace=lambda p: p)
        fields.update(kw)
        return Obj("fusion::Sketch", **fields)

    def text(self, curves, sketch=None, box=(0, 0, 30, 10), **kw):
        box_object = Obj(minPoint=P(box[0], box[1]), maxPoint=P(box[2], box[3]))
        return Obj("fusion::SketchText", parentSketch=sketch or self.sketch(), asCurves=lambda: list(curves),
                   boundingBox=box_object, **kw)

    def square(self, x, y, size):
        a, b, c, d = (x, y), (x + size, y), (x + size, y + size), (x, y + size)
        return [line(a, b), line(b, c), line(c, d), line(d, a)]

    def test_each_outer_outline_is_a_profile_and_a_hole_goes_with_its_outer(self):
        curves = self.square(0, 0, 10) + self.square(3, 3, 4) + self.square(20, 0, 5)
        profiles, areas = read_sketch.read_text_outlines(self.text(curves))
        self.assertEqual(len(profiles), 2)
        self.assertEqual([[loop["outer"] for loop in p["loops"]] for p in profiles], [[True, False], [True]])
        self.assertEqual(areas, [84.0, 25.0])
        self.assertEqual((profiles[0]["space"], profiles[0]["sketch_token"], profiles[0]["text"]), ("sketch", "sk2", True))

    def test_an_island_inside_a_hole_is_an_outer_outline_again(self):
        curves = self.square(0, 0, 20) + self.square(2, 2, 16) + self.square(6, 6, 8)
        profiles, areas = read_sketch.read_text_outlines(self.text(curves))
        self.assertEqual([len(p["loops"]) for p in profiles], [2, 1])
        self.assertEqual(areas, [400.0 - 256.0, 64.0])

    def test_outlines_that_do_not_close_are_a_marker_with_that_problem(self):
        profiles, areas = read_sketch.read_text_outlines(self.text(self.square(0, 0, 10)[:3]))
        self.assertEqual((len(profiles), profiles[0]["problem"], areas), (1, "open", [None]))
        self.assertNotIn("loops", profiles[0])

    def test_a_text_without_readable_curves_is_a_marker(self):
        broken = Obj("fusion::SketchText", parentSketch=self.sketch())
        self.assertEqual(read_sketch.read_text_outlines(broken)[0][0]["problem"], "unread")

    def test_more_curves_or_outlines_than_the_caps_allow_are_a_marker(self):
        many = [line((i, 0), (i + 0.5, 0)) for i in range(read_sketch._MAX_TEXT_CURVES + 1)]
        self.assertEqual(read_sketch.read_text_outlines(self.text(many))[0][0]["problem"], "too_many")
        original = read_sketch._MAX_TEXT_PROFILES
        read_sketch._MAX_TEXT_PROFILES = 2
        try:
            curves = self.square(0, 0, 5) + self.square(10, 0, 5) + self.square(20, 0, 5)
            self.assertEqual(read_sketch.read_text_outlines(self.text(curves))[0][0]["problem"], "too_many")
        finally:
            read_sketch._MAX_TEXT_PROFILES = original

    def test_the_space_of_the_points_is_decided_by_the_bounding_box(self):
        # A sketch turned a quarter about z: sketch (u, v) is model (-v, u). The box is in sketch space.
        turned = matrix(x=(0, 1, 0), y=(-1, 0, 0))
        sketch = self.sketch(transform=turned, modelToSketchSpace=lambda p: Obj(x=p.y, y=-p.x, z=p.z))
        in_sketch = self.square(2, 1, 5)
        model_points = [((-1, 2), (-1, 7)), ((-1, 7), (-6, 7)), ((-6, 7), (-6, 2)), ((-6, 2), (-1, 2))]
        in_model = [line(a, b) for a, b in model_points]
        got_sketch = read_sketch.read_text_outlines(self.text(in_sketch, sketch, box=(0, 0, 10, 10)))[0][0]
        got_model = read_sketch.read_text_outlines(self.text(in_model, sketch, box=(0, 0, 10, 10)))[0][0]
        self.assertEqual((got_sketch["space"], got_model["space"]), ("sketch", "model"))
        self.assertEqual(got_model["loops"][0]["curves"][0]["start"], [2.0, 1.0])

    def test_a_box_that_fits_both_readings_is_ambiguous(self):
        turned = matrix(x=(0, 1, 0), y=(-1, 0, 0))
        sketch = self.sketch(transform=turned, modelToSketchSpace=lambda p: Obj(x=p.y, y=-p.x, z=p.z))
        got = read_sketch.read_text_outlines(self.text(self.square(0, 0, 4), sketch, box=(-50, -50, 50, 50)))[0][0]
        self.assertEqual((got["problem"], "loops" in got), ("space", False))

    def test_a_text_of_another_component_is_a_marker(self):
        text = self.text(self.square(0, 0, 10), assemblyContext=Obj("fusion::Occurrence"))
        ctx = Obj(component=Obj(entityToken="root"))
        profiles, _ = read_sketch.read_text_outlines(text, ctx)
        self.assertEqual((profiles[0]["problem"], profiles[0]["foreign"]), ("foreign", True))

    def test_a_text_among_profiles_gives_one_area_per_record(self):
        raw = Coll([rect_profile(), self.text(self.square(0, 0, 10) + self.square(20, 0, 5))])
        profiles, areas = read_sketch.read_outlines(raw)
        self.assertEqual(len(profiles), 3)
        self.assertEqual(areas, [None, 100.0, 25.0])
        self.assertEqual(len(read_sketch.read_profiles(raw)), 3)
