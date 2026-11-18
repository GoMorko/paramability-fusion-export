"""Path patterns in the Orca copy (`orca_translate/repeat_path.py`): a line path as a linear Pattern, an arc path whose
copies turn as a circular Pattern whose angle follows the distance, an arc path whose copies keep their direction as
Orca's pattern along a sketch arc, and the cases left out."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests import orca_path_patterns as pegs
from tests.orca_sized import fixture, table_of
from tests.test_translate_path_pattern import turned_copies
from tests.translator_helpers import verdict_of

from lib.capture_model import gap_hints
from lib.geometry import vec
from lib.orca_recipe.enums import FeatureType
from lib.orca_translate import causes, limits, translate
from lib.orca_translate.formulas import orca_value
from lib.orca_translate.place import plane_point

PATTERN = 5


def patterns(result):
    return [f for f in result.recipe.features if f.type == FeatureType.PATTERN]


def run(capture, ticked=None):
    return translate(capture, table_of(capture, ticked))


def outcome(result, name):
    return next(p for p in result.parameters if p["name"] == name)


def limit_of(result, name):
    """The limit on the parameter's line of `name`."""
    return next(f for f in outcome(result, name)["follows"] if isinstance(f, limits.Limit))


def cause_of(result):
    return next(g for g in result.left_out if g["index"] == PATTERN)["cause"]


def edited(capture, edit):
    edit(capture["items"][-1]["data"])
    return capture


class LineTest(unittest.TestCase):
    def test_a_line_path_is_a_linear_pattern_whose_count_and_spacing_follow(self):
        result = run(pegs.pegs_line())
        (pattern,) = patterns(result)
        self.assertFalse(pattern.pattern_circular)
        self.assertEqual(pattern.plane.x_axis, (1.0, 0.0, 0.0))
        self.assertEqual(pattern.expr, {"pattern_count": "count", "pattern_spacing": "pitch"})
        self.assertEqual(verdict_of(result, PATTERN)["verdict"], "copied")

    def test_the_count_and_spacing_stop_where_the_copies_leave_the_line(self):
        # The line is 40 mm long: at a spacing of 10 the fifth peg sits on its end.
        result = run(pegs.pegs_line())
        count, pitch = limit_of(result, "count"), limit_of(result, "pitch")
        self.assertEqual((count.high, count.why[1]), (5.0, limits.PATH_ENDS))
        self.assertAlmostEqual(pitch.high, 40.0 / 3.0, places=1)

    def test_an_extent_spreads_the_copies_over_the_distance_whatever_the_count(self):
        def extent(data):
            data.update(distance_type="extent", distance=30.0)
        capture = edited(pegs.pegs_line(), extent)
        capture["items"][-1]["data"]["params"]["distance"]["value"] = 30.0
        capture["parameters"]["user"][1].update(expression="30 mm", value=3.0)
        (pattern,) = patterns(run(capture))
        self.assertEqual(orca_value(pattern.expr["pattern_spacing"], {"count": 7, "pitch": 30}), 5.0)

    def test_copies_past_the_end_of_the_line_leave_the_step_out(self):
        result = translate(edited(pegs.pegs_line(), lambda d: d.update(start_point=0.5)))
        self.assertEqual(cause_of(result), gap_hints.PATH_PATTERN)

    def test_copies_that_run_against_the_line_leave_the_step_out(self):
        result = translate(edited(pegs.pegs_line(), lambda d: d.update(flip=True)))
        self.assertEqual(cause_of(result), gap_hints.PATH_PATTERN)

    def test_a_size_that_moves_the_path_sketch_is_marked(self):
        capture = fixture("ppattern_arc")
        capture["parameters"]["model"].append(dict(capture["parameters"]["model"][3], name="d5",
                                                   expression="pitch * 2",
                                                   created_by={"kind": "sketchDimension", "sketch": "Sketch4"}))
        capture["parameters"]["user"][1]["dependent_parameters"].append("d5")
        result = run(capture)
        self.assertEqual(len(patterns(result)), 1)
        self.assertEqual(outcome(result, "pitch")["outcome"], "partly")


class TurningArcTest(unittest.TestCase):
    def test_an_arc_whose_copies_turn_is_a_circular_pattern_about_its_axis(self):
        result = run(pegs.pegs_arc())
        (pattern,) = patterns(result)
        self.assertTrue(pattern.pattern_circular)
        self.assertEqual(pattern.plane.normal, (0.0, 0.0, 1.0))
        self.assertAlmostEqual(pattern.pattern_angle, math.degrees(48.0 / 35.0), places=6)

    def test_the_angle_follows_the_distance_along_the_arc_and_the_count(self):
        (pattern,) = patterns(run(pegs.pegs_arc()))
        for count, pitch in ((5, 12.0), (4, 13.0), (3, 7.5)):
            got = orca_value(pattern.expr["pattern_angle"], {"count": count, "pitch": pitch})
            self.assertAlmostEqual(got, math.degrees((count - 1) * pitch / 35.0), places=4)

    def test_the_count_and_distance_stop_where_the_copies_leave_the_arc(self):
        result = run(pegs.pegs_arc())
        room = 35.0 * math.pi / 2.0
        self.assertAlmostEqual(limit_of(result, "pitch").high, room / 4.0, places=1)
        self.assertAlmostEqual(limit_of(result, "count").high, 1.0 + room / 12.0, places=1)

    def test_a_pattern_round_the_whole_circle_turns_evenly_and_keeps_its_distance(self):
        def full(data):
            data["path"]["curves"][0]["kind"] = "circle"
            data.update(distance_type="extent", distance=2 * math.pi * 35.0)
            data["elements"] = [dict(e, frame=pegs.turn_frame(72.0 * e["id"])) for e in data["elements"]]
        capture = edited(pegs.pegs_arc(), full)
        result = run(capture)
        (pattern,) = patterns(result)
        self.assertEqual((pattern.pattern_angle, pattern.expr), (360.0, {"pattern_count": "count"}))
        self.assertEqual(outcome(result, "pitch")["outcome"], "fixed")

    def test_copies_that_do_not_turn_by_the_distance_leave_the_step_out(self):
        result = translate(edited(pegs.pegs_arc(), lambda d: d.update(distance=d["distance"] * 1.01)))
        self.assertEqual(cause_of(result), causes.COPIES_UNEVEN)

    def test_copies_turned_against_the_arc_leave_the_step_out(self):
        # 30 degree steps backward are also whole steps forward (330 and 300 degrees), past the count.
        def against(data):
            for element, frame in zip(data["elements"], turned_copies(-30, -60)):
                element["frame"] = frame
        self.assertEqual(cause_of(translate(edited(fixture("ppattern_arc"), against))), gap_hints.PATH_PATTERN)

    def test_a_start_part_way_along_the_arc_leaves_the_step_out(self):
        result = translate(edited(pegs.pegs_arc(), lambda d: d.update(start_point=0.1)))
        self.assertEqual(cause_of(result), gap_hints.PATH_PATTERN)

    def test_suppressed_copies_leave_the_step_out(self):
        def suppress(data):
            data["elements"][2]["suppressed"] = True
            data["suppressed_ids"] = [2]
        self.assertEqual(cause_of(translate(edited(pegs.pegs_arc(), suppress))), causes.COPIES_SUPPRESSED)


def sampled_moves(result):
    """The moves Orca gives each copy of its pattern along a curve: the guide arc's point at i / (count - 1) of its
    sweep less its start, in capture coordinates (Orca's `apply_feature`, Pattern, `sample_entity_2d`)."""
    (pattern,) = patterns(result)
    guide = result.recipe.features[pattern.pattern_curve_sketch]
    arc = guide.entities[pattern.pattern_curve_entity]
    n = pattern.pattern_count

    def at(t):
        theta = arc.start_angle + (arc.end_angle - arc.start_angle) * t
        return plane_point(guide.plane, (arc.center[0] + arc.radius * math.cos(theta),
                                         arc.center[1] + arc.radius * math.sin(theta)))
    return [vec.sub(at(i / (n - 1)), at(0.0)) for i in range(n)]


class SlidingArcTest(unittest.TestCase):
    def test_orca_slides_each_copy_where_fusion_put_it(self):
        capture = pegs.pegs_arc_slide()
        result = run(capture)
        wanted = [e["frame"]["origin"] for e in capture["items"][-1]["data"]["elements"]]
        for got, place in zip(sampled_moves(result), wanted):
            self.assertTrue(vec.close(got, place, 1e-6), (got, place))

    def test_the_count_follows_over_an_extent_and_the_distance_keeps_its_number(self):
        result = run(pegs.pegs_arc_slide())
        (pattern,) = patterns(result)
        self.assertEqual(pattern.expr, {"pattern_count": "count"})
        self.assertEqual([outcome(result, n)["outcome"] for n in ("count", "pitch")], ["variable", "fixed"])

    def test_a_spacing_keeps_the_count_too(self):
        def spacing(data):
            data.update(distance_type="spacing", distance=12.0)
        result = run(edited(pegs.pegs_arc_slide(), spacing))
        self.assertEqual(patterns(result)[0].expr, {})
        self.assertEqual([outcome(result, n)["outcome"] for n in ("count", "pitch")], ["fixed", "fixed"])

    def test_copies_off_the_arc_leave_the_step_out(self):
        def moved(data):
            data["elements"][3]["frame"]["origin"][0] += 0.5
        self.assertEqual(cause_of(translate(edited(pegs.pegs_arc_slide(), moved))), causes.COPIES_UNEVEN)

    def test_copies_that_keep_their_direction_round_a_whole_circle_are_left_out(self):
        def circle(data):
            data["path"]["curves"][0]["kind"] = "circle"
        self.assertEqual(cause_of(translate(edited(pegs.pegs_arc_slide(), circle))), gap_hints.PATH_PATTERN)


class OtherPathsTest(unittest.TestCase):
    def test_paths_the_copy_cannot_follow_are_left_out_with_the_path_pattern_cause(self):
        def two_curves(data):
            data["path"]["curves"].append(copy.deepcopy(data["path"]["curves"][0]))
        for edit in (two_curves, lambda d: d.update(symmetric=True)):
            with self.subTest(edit):
                self.assertEqual(cause_of(translate(edited(pegs.pegs_line(), edit))), gap_hints.PATH_PATTERN)


class LiveCapturesTest(unittest.TestCase):
    def test_each_capture_holds_the_box_and_volume_of_its_pegs(self):
        for name, build in pegs.BUILDERS.items():
            with self.subTest(name):
                capture = build()
                self.assertEqual({k: capture["target"][k] for k in ("box", "volume_mm3")},
                                 pegs.expected(name, 5 if name != "pegs_line" else 4,
                                               {"pegs_line": 10.0, "pegs_arc": 12.0}.get(name, 48.0)))
                self.assertEqual(translate(capture).left_out, [])


if __name__ == "__main__":
    unittest.main()
