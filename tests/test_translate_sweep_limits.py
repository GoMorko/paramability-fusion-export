"""Sweep options the app refuses are left out of the copy with a reason: a taper that closes the outline, a volume that
fits no taper, a parallel outline with the wrong volume, a rise below the app's tangent limit, sizes that carry a twist
or taper past the recipe limits, the travel direction of a closed twist, and the version of a sweep in a tool body."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sized import TICKED, TRAY, param, table_of
from tests import test_translate_sweep as base
from tests.test_translate_sweep import (PIPE, PIPE_ITEM, arc_xy, edited, edited_after, only_sweep, pipe_along,
                                        sweep_of, with_options)
from tests.translator_helpers import load_capture, stopped

from lib.translator.sweep import sweep_limits, sweep_taper
from lib.translator import translate

NO_FIT_VOLUME = 1.1


class TaperClosesTest(unittest.TestCase):
    """The 20 by 4 rectangle closes from a shift of 2 mm: 20 mm at 6 degrees moves each wall by 2.1 mm."""

    def setUp(self):
        self.taper = base.TaperTest("offset")
        self.straight, self.offset, self.scaled, self.SLOPE = (
            self.taper.straight, self.taper.offset, self.taper.scaled, self.taper.SLOPE)

    def test_a_taper_that_closes_the_outline_is_left_out_when_the_volume_cannot_say(self):
        result = translate(self.straight(None, fusion_deg=-6.0))
        self.assertEqual(stopped(result)["reason"], sweep_limits.TAPER_CLOSES)

    def test_a_scaled_taper_that_the_offset_cannot_hold_is_left_out_as_scaled(self):
        rectangle = [[-5, -3], [5, -3], [5, 3], [-5, 3]]
        terms = sweep_taper.section_terms([(rectangle, True)])
        capture = edited("sweep_straight", 2, lambda d: d.update(taper_deg=-6.0))
        capture["items"][2]["target_after"]["volume_mm3"] = sweep_taper._scaled_volume(
            terms, 40.0, math.tan(math.radians(6.0)))
        self.assertEqual(stopped(translate(capture))["reason"], sweep_limits.SCALED_OUTLINE)

    def test_a_volume_that_fits_no_taper_model_is_left_out(self):
        result = translate(self.straight(self.offset(self.SLOPE) * NO_FIT_VOLUME))
        self.assertEqual(stopped(result)["reason"], sweep_limits.NOT_MATCHING)

    def test_a_taper_that_closes_a_bent_path_outline_is_left_out(self):
        result = translate(with_options(PIPE, PIPE_ITEM, taper_deg=-4.0))
        self.assertEqual(stopped(result)["reason"], sweep_limits.TAPER_CLOSES)


class ClosingShiftTest(unittest.TestCase):
    RECT = [[0, 0], [10, 0], [10, 6], [0, 6]]

    def test_a_shift_between_the_half_thickness_and_the_area_bound_closes_the_outline(self):
        self.assertTrue(sweep_taper.closes([(self.RECT, True)], 3.2, 1.0))
        self.assertFalse(sweep_taper.closes([(self.RECT, True)], 2.9, 1.0))

    def test_a_hole_growing_into_the_outline_closes_it(self):
        loops = [(self.RECT, True), ([[3, 2], [3, 4], [7, 4], [7, 2]], False)]
        self.assertTrue(sweep_taper.closes(loops, 1.1, 1.0))
        self.assertFalse(sweep_taper.closes(loops, 0.9, 1.0))


class ParallelVolumeTest(unittest.TestCase):
    def test_a_parallel_outline_along_a_line_keeps_its_volume_check(self):
        capture = edited("sweep_straight", 2, lambda d: d.update(orientation="parallel"))
        capture["items"][2]["target_after"]["volume_mm3"] *= 1.3
        self.assertEqual(stopped(translate(capture))["reason"], sweep_limits.NOT_MATCHING)

    def test_a_parallel_outline_along_a_bend_has_the_volume_of_its_rise(self):
        def made(factor):
            capture = edited_after(pipe_along([arc_xy((0, 10), 10, -90, -30)]), orientation="parallel")
            area = sweep_of(capture, 2)["areas"][0]
            capture["items"][2]["target_after"]["volume_mm3"] = area * 10 * math.cos(math.radians(30)) * factor
            return translate(capture)
        self.assertEqual(only_sweep(self, made(1.0))["orientation"], "fixed")
        self.assertEqual(stopped(made(1.3))["reason"], sweep_limits.NOT_MATCHING)


class RiseTest(unittest.TestCase):
    def test_a_rise_below_the_limit_at_the_end_tangent_is_left_out(self):
        def made(turn):
            return translate(edited_after(pipe_along([arc_xy((0, 10), 10, -90, -90 + turn)]), orientation="parallel"))
        self.assertEqual(only_sweep(self, made(87.0))["orientation"], "fixed")
        self.assertEqual(stopped(made(87.4))["reason"], sweep_limits.KEEPS_DIRECTION)


class SizedLimitsTest(unittest.TestCase):
    def sized_sweep(self, key, expression, value, **settings):
        capture = load_capture("sweep_straight")
        capture["capture"] = 3
        capture["parameters"] = load_capture(TRAY)["parameters"]
        data = sweep_of(capture, 2)
        data.update(**settings)
        data["params"] = {key: param("d9", expression, value)}
        capture["items"][2]["target_after"]["volume_mm3"] = None
        table = table_of(capture, TICKED + ["turn_deg"])
        result = translate(capture, size_table=table)
        return result

    def test_a_taper_that_follows_a_size_stops_the_range_before_45_degrees(self):
        result = self.sized_sweep("taper_deg", "turn_deg - 88", 2.0, taper_deg=2.0)
        self.assertIsNone(result.refusal)
        turn = result.recipe["sizes"]["turn_deg"]
        self.assertTrue(90.0 <= turn["max"] < 133.0, turn)

    def test_a_twist_that_follows_a_size_stops_the_range_before_3600_degrees(self):
        result = self.sized_sweep("twist_deg", "turn_deg * 30", 2700.0, twist_deg=2700.0)
        self.assertIsNone(result.refusal)
        turn = result.recipe["sizes"]["turn_deg"]
        self.assertTrue(90.0 <= turn["max"] <= 120.0, turn)


class ClosedTravelTest(unittest.TestCase):
    @staticmethod
    def turns(step):
        """1 when the written closed path runs counter clockwise, else -1 (shoelace over the segment ends)."""
        points = [step["path"]["start"]] + [s["to"] for s in step["path"]["segments"]]
        twice = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:]))
        return 1 if twice > 0 else -1

    def test_a_closed_twist_travels_the_way_fusion_walks_the_path(self):
        plain = only_sweep(self, translate(load_capture("sweep_closed_twist")))

        def opposed(data):
            for curve in data["path"]["curves"]:
                curve["opposed"] = True
        against = only_sweep(self, translate(edited("sweep_closed_twist", 2, opposed)))
        self.assertEqual(self.turns(against), -self.turns(plain))

    def test_a_twisted_full_circle_travels_the_way_fusion_walks_it(self):
        steps = []
        for flag in (False, True):
            capture = edited("sweep_ring", 2, lambda d: d.update(twist_deg=360.0))
            capture["items"][2]["data"]["path"]["curves"][0]["opposed"] = flag
            steps.append(only_sweep(self, translate(capture)))
        first, second = (s["path"]["segments"][0]["through"] for s in steps)
        self.assertEqual(first[1], -second[1])


class ToolBodyVersionTest(unittest.TestCase):
    def capture_with_sweep(self, **settings):
        capture = load_capture("combine_tool_cut_inside")
        data = copy.deepcopy(sweep_of(load_capture("sweep_straight"), 2))
        data.update(**settings)
        item = capture["items"][3]
        item.update(type="SweepFeature", data=dict(data, participants=[], target_box_before=None))
        return capture

    def test_a_twisted_sweep_inside_a_tool_body_raises_the_version(self):
        result = translate(self.capture_with_sweep(twist_deg=90.0))
        self.assertIsNone(result.refusal)
        self.assertEqual(result.recipe["version"], 16)

    def test_a_plain_sweep_inside_a_tool_body_keeps_the_tool_body_version(self):
        result = translate(self.capture_with_sweep())
        self.assertIsNone(result.refusal)
        self.assertEqual(result.recipe["version"], 15)
