"""Ellipses in the Orca copy: a full ellipse is one Orca ellipse entity, an elliptical arc is one Orca elliptical arc
entity when its exact definition gives the ends Fusion measured, else it stays out."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests import orca_ellipse_arcs as ea
from tests.translator_helpers import load_capture

from lib.orca_recipe.enums import EntityType, FeatureType
from lib.orca_translate import translate
from lib.orca_translate.sketches import entities_of


def run(capture):
    return translate(capture, None)


class EllipseTest(unittest.TestCase):
    def test_a_turned_ellipse_keeps_its_centre_major_radius_and_direction(self):
        result = run(load_capture("extrude_ellipse_turned"))
        sketch = next(f for f in result.recipe.features if f.type == FeatureType.SKETCH)
        (entity,) = sketch.entities
        self.assertEqual(entity.type, EntityType.ELLIPSE)
        self.assertEqual(entity.center, (0.0, 0.0))
        self.assertAlmostEqual(entity.radius, 10.0)
        self.assertAlmostEqual(entity.rminor, 5.0)
        self.assertAlmostEqual(entity.rotation, math.radians(30), places=5)
        self.assertEqual(result.left_out, [])

    def test_an_ellipse_with_its_axes_the_wrong_way_round_is_not_written(self):
        curve = {"kind": "ellipse", "center": [0, 0], "major_dir": [1, 0], "major_radius": 4, "minor_radius": 6}
        self.assertIsNone(entities_of([[curve]]))

    def test_an_elliptical_arc_without_its_exact_definition_stays_left_out(self):
        capture = copy.deepcopy(load_capture("extrude_ellipse_turned"))
        loop = capture["items"][1]["data"]["profiles"][0]["loops"][0]
        loop["curves"] = [{"kind": "other", "type": "NurbsCurve3D", "start": [10, 0], "end": [0, 5],
                           "mid": [7.07, 3.54], "samples": [[10, 0], [7.07, 3.54], [0, 5]]}]
        result = run(capture)
        self.assertEqual([f for f in result.recipe.features if f.type == FeatureType.SKETCH], [])
        self.assertEqual(len(result.left_out), 1)


def drawn(entity, angle):
    """The point of an Orca ellipse entity at a parametric angle (Orca's own definition)."""
    c, s = entity.radius * math.cos(angle), entity.rminor * math.sin(angle)
    u, v = math.cos(entity.rotation), math.sin(entity.rotation)
    return entity.center[0] + c * u - s * v, entity.center[1] + c * v + s * u


def gap(entity, point):
    """How far a point lies from the arc an elliptical arc entity draws (the nearest of a coarse walk, narrowed)."""
    steps, lo, hi = 400, entity.start_angle, entity.end_angle
    walk = [lo + (hi - lo) * i / steps for i in range(steps + 1)]
    best = min(range(steps + 1), key=lambda i: math.dist(point, drawn(entity, walk[i])))
    a, b = walk[max(best - 1, 0)], walk[min(best + 1, steps)]
    for _ in range(60):
        m1, m2 = a + (b - a) / 3, b - (b - a) / 3
        if math.dist(point, drawn(entity, m1)) < math.dist(point, drawn(entity, m2)):
            b = m2
        else:
            a = m1
    return math.dist(point, drawn(entity, (a + b) / 2))


class EllipticalArcTest(unittest.TestCase):
    def check_written(self, curve):
        (entity,) = entities_of([[curve]])
        self.assertEqual(entity.type, EntityType.ELLIPSE_ARC)
        self.assertGreaterEqual(entity.radius, entity.rminor)
        self.assertGreater(entity.end_angle, entity.start_angle)
        self.assertLess(entity.end_angle - entity.start_angle, 2 * math.pi)
        ends = {tuple(round(v, 6) for v in entity.p0), tuple(round(v, 6) for v in entity.p1)}
        self.assertEqual(ends, {tuple(round(v, 6) for v in curve["start"]), tuple(round(v, 6) for v in curve["end"])})
        for point in (drawn(entity, entity.start_angle), drawn(entity, entity.end_angle)):
            self.assertLess(min(math.dist(point, e) for e in (entity.p0, entity.p1)), 1e-6)
        for sample in curve["samples"]:
            self.assertLess(gap(entity, sample), 1e-6)
        return entity

    def test_arcs_of_every_turn_direction_and_span_count_are_written_as_they_are_drawn(self):
        for turn in (0.0, 0.5, 2.0, -0.7):
            for t0, t1 in ((0.3, 2.9), (2.9, 0.3), (-1.0, 4.5), (0.0, math.pi / 2), (5.0, 1.0)):
                for growth in (1.0, 1.7):
                    with self.subTest(turn=turn, t0=t0, t1=t1, growth=growth):
                        self.check_written(ea.arc_curve((3.0, -2.0), 10.0, 5.0, turn, t0, t1, growth))

    def test_a_circular_arc_given_as_a_conic_is_written_with_equal_radii(self):
        entity = self.check_written(ea.arc_curve((0.0, 0.0), 7.0, 7.0, 0.0, 0.2, 2.0))
        self.assertAlmostEqual(entity.radius, entity.rminor)

    def test_the_slot_writes_two_lines_and_two_elliptical_arcs_that_meet_at_the_corners(self):
        result = run(ea.slot())
        sketch = next(f for f in result.recipe.features if f.type == FeatureType.SKETCH)
        self.assertEqual(result.left_out, [])
        self.assertEqual([e.type for e in sketch.entities],
                         [EntityType.LINE, EntityType.ELLIPSE_ARC, EntityType.LINE, EntityType.ELLIPSE_ARC])
        ends = [tuple(round(v, 6) + 0.0 for v in p) for e in sketch.entities for p in (e.p0, e.p1)]
        for corner in ((15.0, -5.0), (15.0, 5.0), (-15.0, 5.0), (-15.0, -5.0)):
            self.assertEqual(ends.count(corner), 2)
        for entity in sketch.entities[1::2]:
            self.assertAlmostEqual(entity.end_angle - entity.start_angle, math.pi)

    def test_ends_that_the_entity_does_not_give_leave_the_outline_out(self):
        curve = ea.arc_curve((0.0, 0.0), 10.0, 5.0, 0.0, 0.0, 1.5)
        curve["end"] = [curve["end"][0] + 0.001, curve["end"][1]]
        self.assertIsNone(entities_of([[curve]]))
        capture = copy.deepcopy(ea.slot())
        loop = capture["items"][1]["data"]["profiles"][0]["loops"][0]
        loop["curves"][1]["end"][1] += 0.001
        result = run(capture)
        self.assertEqual([f for f in result.recipe.features if f.type == FeatureType.SKETCH], [])
        self.assertEqual(len(result.left_out), 1)

    def test_measured_points_on_the_other_side_of_the_ellipse_leave_the_outline_out(self):
        curve = ea.arc_curve((0.0, 0.0), 10.0, 5.0, 0.0, 0.0, 1.5)
        other = ea.arc_curve((0.0, 0.0), 10.0, 5.0, 0.0, 1.5, 2 * math.pi)
        curve["samples"] = [curve["samples"][0]] + other["samples"][1:-1] + [curve["samples"][-1]]
        self.assertIsNone(entities_of([[curve]]))

    def test_spans_of_different_ellipses_leave_the_outline_out(self):
        curve = ea.arc_curve((0.0, 0.0), 10.0, 5.0, 0.0, 0.0, 3.0)
        curve["nurbs"]["poles"][-1] = [curve["nurbs"]["poles"][-1][0], curve["nurbs"]["poles"][-1][1] + 0.5]
        curve["nurbs"]["poles"][-2] = [curve["nurbs"]["poles"][-2][0] + 0.5, curve["nurbs"]["poles"][-2][1]]
        self.assertIsNone(entities_of([[curve]]))

    def test_a_conic_that_is_not_an_ellipse_leaves_the_outline_out(self):
        curve = ea.arc_curve((0.0, 0.0), 10.0, 5.0, 0.0, 0.0, 1.0)
        curve["nurbs"]["weights"][1] = 1.5
        self.assertIsNone(entities_of([[curve]]))

    def test_a_closed_or_untrusted_curve_leaves_the_outline_out(self):
        for change in ({"periodic": True}, {"degree": 3}, {"rational": False}):
            curve = ea.arc_curve((0.0, 0.0), 10.0, 5.0, 0.0, 0.0, 1.0)
            curve["nurbs"].update(change)
            self.assertIsNone(entities_of([[curve]]), change)
        curve = ea.arc_curve((0.0, 0.0), 10.0, 5.0, 0.0, 0.0, 1.0)
        curve["truncated"] = True
        self.assertIsNone(entities_of([[curve]]))


if __name__ == "__main__":
    unittest.main()
