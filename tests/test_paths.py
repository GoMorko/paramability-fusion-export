"""The sweep path as the recipe holds it: ordering, orientation, classes, written forms and refusals."""
import math
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import close

from lib.translator import paths, vec
from lib.translator.result import Refusal

S2 = math.sqrt(0.5)
# The outline sits in the plane x = 0, so a path leaves it along x.
FRAME = {"origin": [0, 0, 0], "z": [1, 0, 0]}
SQUARE = [[0, y, z] for y in (-1, 1) for z in (-1, 1)]
XY_SKETCH = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


def line(a, b):
    return {"kind": "line", "start": list(a), "end": list(b)}


def arc(start, end, mid, center):
    radius = math.dist(start, center)
    return {"kind": "arc", "start": list(start), "end": list(end), "mid": list(mid), "center": list(center),
            "radius": radius}


def quarter(center, start_dir, end_dir, radius):
    """A quarter arc about `center` from direction `start_dir` to `end_dir` (unit, in one plane)."""
    def at(d):
        return [center[i] + radius * d[i] for i in range(3)]

    half = [(start_dir[i] + end_dir[i]) / math.hypot(*[start_dir[j] + end_dir[j] for j in range(3)]) for i in range(3)]
    return arc(at(start_dir), at(end_dir), at(half), center)


def path_of(curves, **extra):
    return dict({"closed": False, "kind": "sketch", "curves": curves}, **extra)


def plan(curves, points=SQUARE, outline=FRAME, **extra):
    """The plan of a path record; `extra` are more keys of that record (`closed`, `frame`)."""
    return paths.plan(path_of(curves, **extra), outline, points)


def pipe_with_bend():
    """Along +x, a quarter turn to +y, along +y: all in the plane z = 0."""
    return [line((0, 0, 0), (10, 0, 0)), quarter([10, 5, 0], [0, -1, 0], [1, 0, 0], 5), line((15, 5, 0), (15, 20, 0))]


def pipe_in_3d():
    """Along +x, a quarter turn to +y, along +y, a quarter turn to +z, along +z."""
    return [line((0, 0, 0), (10, 0, 0)), quarter([10, 5, 0], [0, -1, 0], [1, 0, 0], 5),
            line((15, 5, 0), (15, 15, 0)), quarter([15, 15, 5], [0, 0, -1], [0, 1, 0], 5),
            line((15, 20, 5), (15, 20, 20))]


def sweep_with(recipe_path):
    sketch = {"on": {"origin": [0, 0, 0], "normal": [1, 0, 0], "xDir": [0, 1, 0]},
              "outer": {"kind": "circle", "center": [0, 0], "radius": 1}}
    return {"schema": "paramability.recipe", "version": 15, "features": [
        {"id": "sweep_1", "kind": "sweep", "sketch": sketch, "path": recipe_path, "combine": "new"}]}


class ClassTest(unittest.TestCase):
    def test_a_straight_line(self):
        found = plan([line((0, 0, 0), (30, 0, 0))])
        self.assertEqual((found.kind, found.length, found.direction), ("line", 30.0, [1.0, 0.0, 0.0]))
        self.assertIsNone(found.recipe)

    def test_lines_that_continue_straight_are_one_line(self):
        found = plan([line((10, 0, 0), (30, 0, 0)), line((0, 0, 0), (10, 0, 0))])
        self.assertEqual((found.kind, found.length, len(found.curves)), ("line", 30.0, 1))

    def test_a_single_arc_carries_its_axis_and_angle(self):
        found = plan([quarter([0, 5, 0], [0, -1, 0], [1, 0, 0], 5)])
        self.assertEqual((found.kind, found.radius, found.angle_deg), ("arc", 5.0, 90.0))
        self.assertTrue(close(found.axis["point"], [0, 5, 0]) and close(found.axis["dir"], [0, 0, 1]))

    def test_an_arc_given_the_other_way_still_turns_positively_about_its_axis(self):
        found = plan([quarter([0, 5, 0], [0, -1, 0], [-1, 0, 0], 5)])
        self.assertEqual(found.angle_deg, 90.0)
        self.assertTrue(close(found.axis["dir"], [0, 0, -1]))

    def test_a_full_circle_starts_on_the_outline_nearest_to_it(self):
        ring = {"kind": "circle", "center": [0, 0, 0], "normal": [0, 0, 1], "radius": 10}
        plane = {"origin": [0, 0, 0], "z": [0, 1, 0]}
        east = plan([ring], points=[[x, 0, z] for x in (9, 11) for z in (-1, 1)], outline=plane)
        self.assertEqual((east.kind, east.angle_deg, east.radius), ("circle", 360.0, 10.0))
        self.assertTrue(close(east.start, [10, 0, 0]) and close(east.direction, [0, 1, 0]))
        west = plan([ring], points=[[-10, 0, 1]], outline=plane)
        self.assertTrue(close(west.start, [-10, 0, 0]) and close(west.direction, [0, -1, 0]))

    def test_two_half_arcs_of_one_circle_are_a_circle(self):
        halves = [arc((10, 0, 0), (-10, 0, 0), (0, 10, 0), (0, 0, 0)), arc((-10, 0, 0), (10, 0, 0), (0, -10, 0), (0, 0, 0))]
        found = plan(halves, points=[[10, 0, 0]], outline={"origin": [0, 0, 0], "z": [0, 1, 0]})
        self.assertEqual((found.kind, found.radius), ("circle", 10.0))

    def test_a_flat_chain_is_written_in_the_sketch_plane(self):
        found = plan(pipe_with_bend(), frame=XY_SKETCH)
        self.assertEqual(found.kind, "flat")
        recipe = found.recipe
        self.assertEqual(recipe["kind"], "flat")
        self.assertTrue(close(recipe["on"]["normal"], [0, 0, 1]) and close(recipe["on"]["origin"], [0, 0, 0]))
        self.assertTrue(close(recipe["start"], [0, 0]))
        self.assertEqual([s["kind"] for s in recipe["segments"]], ["line", "arc", "line"])
        self.assertTrue(close(recipe["segments"][0]["to"], [10, 0]))
        self.assertTrue(close(recipe["segments"][1]["through"], [10 + 5 * S2, 5 - 5 * S2], 1e-8))
        self.assertTrue(close(recipe["segments"][1]["to"], [15, 5]))
        self.assertTrue(close(recipe["segments"][2]["to"], [15, 20]))
        self.assertEqual(check_recipe(sweep_with(recipe)), [])

    def test_the_sketch_frame_gives_the_flat_coordinates(self):
        moved = {"origin": [0, 0, 0], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}
        found = plan(pipe_with_bend(), frame=moved)
        self.assertTrue(close(found.recipe["start"], [0, 0]))
        self.assertTrue(close(found.recipe["segments"][0]["to"], [0, -10]))

    def test_a_path_without_a_sketch_frame_gets_the_plane_it_lies_in(self):
        found = plan(pipe_with_bend())
        recipe = found.recipe
        self.assertTrue(close(abs(recipe["on"]["normal"][2]), 1.0))
        self.assertAlmostEqual(math.hypot(*recipe["segments"][0]["to"]), 10.0, places=6)
        self.assertEqual(check_recipe(sweep_with(recipe)), [])

    def test_a_free_curve_becomes_spline_segments_ending_on_the_curve_ends(self):
        samples = [[x, 0.02 * x * x, 0] for x in [i * 0.1 for i in range(201)]]
        curve = {"kind": "other", "type": "NurbsCurve3D", "start": samples[0], "end": samples[-1], "mid": samples[100],
                 "samples": samples, "tangent_start": [1, 0, 0], "tangent_end": [0.9285, 0.3714, 0]}
        found = plan([curve], frame=XY_SKETCH)
        self.assertEqual(found.kind, "flat")
        segments = found.recipe["segments"]
        self.assertTrue(all(s["kind"] == "spline" for s in segments))
        self.assertTrue(close(segments[-1]["to"], [20, 8]))
        self.assertEqual(check_recipe(sweep_with(found.recipe)), [])

    def test_a_chain_in_3d_is_written_as_corner_points(self):
        found = plan(pipe_in_3d())
        self.assertEqual(found.kind, "corners")
        recipe = found.recipe
        self.assertEqual(recipe["kind"], "corners")
        self.assertTrue(close(recipe["points"], [[0, 0, 0], [15, 0, 0], [15, 20, 0], [15, 20, 20]]))
        self.assertEqual(recipe["bendRadius"], 5.0)
        self.assertEqual(check_recipe(sweep_with(recipe)), [])

    def test_bends_of_different_radii_give_a_radius_per_corner(self):
        chain = [line((0, 0, 0), (10, 0, 0)), quarter([10, 5, 0], [0, -1, 0], [1, 0, 0], 5),
                 line((15, 5, 0), (15, 20, 0)), quarter([15, 20, 2], [0, 0, -1], [0, 1, 0], 2),
                 line((15, 22, 2), (15, 22, 20))]
        self.assertEqual(plan(chain).recipe["bendRadius"], [5.0, 2.0])


class RoundedCoordinatesTest(unittest.TestCase):
    """The reader rounds coordinates to 6 decimals, so directions of short legs carry an error near 1e-6."""

    def rounded(self, curves, frame):
        turn = lambda p: [round(c, 6) for c in vec.rotate(vec.rotate(p, [0, 0, 1], 17.0), [1, 0, 0], 23.0)]  # noqa: E731
        out = []
        for c in curves:
            moved = dict(c)
            for key in ("start", "end", "mid", "center"):
                if key in c:
                    moved[key] = turn(c[key])
            out.append(moved)
        return out, {"origin": [0, 0, 0], "z": vec.rotate(frame["z"], [0, 0, 1], 17.0)}

    def test_short_legs_and_bends_still_count_as_tangent(self):
        chain = [line((0, 0, 0), (1, 0, 0)), quarter([1, 1, 0], [0, -1, 0], [1, 0, 0], 1), line((2, 1, 0), (2, 2, 0)),
                 quarter([2, 2, 1], [0, 0, -1], [0, 1, 0], 1), line((2, 3, 1), (2, 3, 2))]
        curves, outline = self.rounded(chain, FRAME)
        outline["z"] = vec.rotate(vec.rotate([1, 0, 0], [0, 0, 1], 17.0), [1, 0, 0], 23.0)
        found = plan(curves, outline=outline, points=[[0, 0, 0]])
        self.assertEqual(found.kind, "corners")
        self.assertAlmostEqual(found.recipe["bendRadius"], 1.0, places=5)

    def test_a_join_next_to_a_curve_counts_as_smooth_up_to_two_degrees(self):
        def with_kink(degrees):
            """A line into a quarter arc whose start direction is turned by `degrees` from the line."""
            s = math.radians(degrees)
            centre = [10, 5, 0]
            start = [10 + 5 * math.sin(s), 5 - 5 * math.cos(s), 0]
            mid_dir = (math.sin(s) + 1, -math.cos(s))
            size = math.hypot(*mid_dir)
            mid = [10 + 5 * mid_dir[0] / size, 5 + 5 * mid_dir[1] / size, 0]
            return [line((0, 0, 0), start), arc(start, (15, 5, 0), mid, centre)]

        self.assertIsInstance(plan(with_kink(1.5), points=[[0, 0, 0]], frame=XY_SKETCH), paths.PathPlan)
        self.assertEqual(plan(with_kink(2.5), points=[[0, 0, 0]], frame=XY_SKETCH).reason, paths.SHARP_CORNER)


class OrderTest(unittest.TestCase):
    def test_shuffled_and_flipped_curves_come_out_in_path_order(self):
        a, b, c = pipe_with_bend()
        found = plan([dict(c, start=c["end"], end=c["start"]), b, a])
        self.assertEqual([k["kind"] for k in found.curves], ["line", "arc", "line"])
        self.assertTrue(close(found.curves[0]["start"], [0, 0, 0]) and close(found.curves[-1]["end"], [15, 20, 0]))

    def test_a_path_listed_from_its_far_end_is_turned_round(self):
        a, b, c = pipe_with_bend()
        found = plan(paths.turned_round([a, b, c]))
        self.assertTrue(found.reversed)
        self.assertTrue(close(found.start, [0, 0, 0]) and close(found.end, [15, 20, 0]))
        self.assertTrue(close(found.curves[1]["end"], [15, 5, 0]))

    def test_when_both_ends_touch_the_outline_plane_the_square_one_starts_the_path(self):
        hook = [line((0, 0, 0), (0, 2, 0)),
                arc((0, 2, 0), (3, -1, 0), (3 + 3 * S2, 2 + 3 * S2, 0), (3, 2, 0)),
                line((3, -1, 0), (0, -1, 0))]
        found = plan(hook, points=[[0, -1.5, 0], [0, -0.5, 0]])
        self.assertTrue(found.reversed)
        self.assertTrue(close(found.start, [0, -1, 0]) and close(found.end, [0, 0, 0]))

    def test_when_both_ends_leave_square_the_one_nearest_the_outline_starts_the_path(self):
        hook = [line((0, 0, 0), (10, 0, 0)), arc((10, 0, 0), (10, 6, 0), (13, 3, 0), (10, 3, 0)),
                line((10, 6, 0), (0, 6, 0))]
        points = [[0, y, z] for y in (5.5, 6.5) for z in (-0.5, 0.5)]
        found = plan(hook, points=points)
        self.assertTrue(found.reversed)
        self.assertTrue(close(found.start, [0, 6, 0]) and close(found.end, [0, 0, 0]))
        self.assertFalse(plan(hook, points=[[0, y, z] for y in (-0.5, 0.5) for z in (-0.5, 0.5)]).reversed)

    def test_a_curve_run_backwards_keeps_its_middle_and_swaps_its_ends(self):
        flipped = paths.turned_round([quarter([0, 5, 0], [0, -1, 0], [1, 0, 0], 5)])[0]
        self.assertTrue(close(flipped["start"], [5, 5, 0]) and close(flipped["end"], [0, 0, 0]))
        self.assertTrue(close(flipped["mid"], [5 * S2, 5 - 5 * S2, 0]))


class OptionsTest(unittest.TestCase):
    """Paths asked for a sweep step (twist, taper, parallel): a line and an arc get a recipe path too."""

    def planned(self, curves, **options):
        return paths.plan(path_of(curves), FRAME, SQUARE, paths.PathOptions(**options))

    def test_a_line_becomes_a_corners_path_of_its_two_ends(self):
        found = self.planned([line((0, 0, 0), (30, 0, 0))], as_step=True)
        self.assertEqual((found.kind, found.recipe["points"]), ("line", [[0, 0, 0], [30, 0, 0]]))
        self.assertIsNone(self.planned([line((0, 0, 0), (30, 0, 0))]).recipe)

    def test_an_arc_becomes_a_flat_path(self):
        found = self.planned([quarter([0, 5, 0], [0, -1, 0], [1, 0, 0], 5)], as_step=True)
        self.assertEqual((found.kind, [s["kind"] for s in found.recipe["segments"]]), ("flat", ["arc"]))

    def test_a_circle_stays_a_closed_path_for_any_option(self):
        ring = {"kind": "circle", "center": [0, 5, 0], "normal": [0, 0, 1], "radius": 5}
        for option in ("as_step", "twisted", "fixed"):
            with self.subTest(option):
                self.assertEqual(self.planned([ring], **{option: True}).reason, paths.CLOSED)

    def test_a_kept_direction_needs_the_path_to_keep_moving_away_from_the_outline_plane(self):
        self.assertEqual(self.planned(pipe_with_bend(), fixed=True, as_step=True).reason, paths.TURNS_BACK)
        eased = [line((0, 0, 0), (10, 0, 0)), quarter([10, 10, 0], [0, -1, 0], [0.5, -S2 * 1.2247, 0], 10)]
        self.assertIsNone(getattr(self.planned(eased, fixed=True, as_step=True), "reason", None))

    def test_a_kept_direction_skips_the_bend_checks(self):
        eased = [line((0, 0, 0), (10, 0, 0)), quarter([10, 10, 0], [0, -1, 0], [0.5, -S2 * 1.2247, 0], 10)]
        wide = [[0, y, 0] for y in (-14, 14)]
        self.assertIsInstance(paths.plan(path_of(eased), FRAME, wide, paths.PathOptions(as_step=True)), Refusal)
        kept = paths.plan(path_of(eased), FRAME, wide, paths.PathOptions(as_step=True, fixed=True))
        self.assertNotIsInstance(kept, Refusal)

    def test_a_twist_counts_the_outline_across_the_path_plane_at_a_bend(self):
        tall = [[0, 0, z] for z in (-9, 9)]
        flat_only = paths.plan(path_of(pipe_with_bend()), FRAME, tall, paths.PathOptions())
        self.assertNotIsInstance(flat_only, Refusal)
        twisted = paths.plan(path_of(pipe_with_bend()), FRAME, tall, paths.PathOptions(as_step=True, twisted=True))
        self.assertIsInstance(twisted, Refusal)


class RefusalTest(unittest.TestCase):
    def refused(self, curves, reason, **kwargs):
        found = plan(curves, **kwargs)
        self.assertIsInstance(found, Refusal)
        self.assertEqual(found.reason, reason)

    def test_a_closed_chain_other_than_a_circle(self):
        square = [line((0, 0, 0), (10, 0, 0)), line((10, 0, 0), (10, 10, 0)), line((10, 10, 0), (0, 10, 0)),
                  line((0, 10, 0), (0, 0, 0))]
        self.refused(square, paths.CLOSED)

    def test_a_path_the_capture_calls_closed_is_not_taken_as_open(self):
        self.refused([line((0, 0, 0), (30, 0, 0))], paths.CLOSED, closed=True)

    def test_curves_that_do_not_join(self):
        self.refused([line((0, 0, 0), (10, 0, 0)), line((10, 1, 0), (20, 1, 0))], paths.NOT_ONE_CHAIN)

    def test_curves_that_branch(self):
        self.refused([line((0, 0, 0), (10, 0, 0)), line((10, 0, 0), (20, 0, 0)), line((10, 0, 0), (10, 10, 0))],
                     paths.NOT_ONE_CHAIN)

    def test_a_path_that_is_not_sketch_curves_or_edges(self):
        found = paths.plan({"kind": "other", "curves": []}, FRAME, SQUARE)
        self.assertEqual(found.reason, paths.NOT_SKETCH)

    def test_a_free_curve_without_samples(self):
        broken = {"kind": "other", "type": "NurbsCurve3D", "start": [0, 0, 0], "end": [9, 0, 0], "samples": []}
        self.refused([broken], paths.UNREADABLE)

    def test_a_zero_length_line(self):
        self.refused([line((0, 0, 0), (0, 0, 0))], paths.UNREADABLE)

    def test_an_ellipse(self):
        ellipse = {"kind": "ellipse", "center": [0, 0, 0], "major_dir": [1, 0, 0], "major_radius": 4, "minor_radius": 2}
        self.refused([ellipse], paths.UNKNOWN_CURVE)

    def test_a_path_through_the_middle_of_the_outline(self):
        self.refused([line((-10, 0, 0), (10, 0, 0))], paths.BOTH_SIDES)

    def test_a_path_that_never_reaches_the_outline(self):
        self.refused([line((5, 0, 0), (20, 0, 0))], paths.OFF_PLANE)

    def test_a_path_that_leaves_the_outline_at_a_slant(self):
        self.refused([line((0, 0, 0), (10, 10, 0))], paths.NOT_SQUARE)

    def test_a_circle_whose_plane_lies_flat_on_the_outline(self):
        ring = {"kind": "circle", "center": [0, 0, 0], "normal": [1, 0, 0], "radius": 10}
        self.refused([ring], paths.NOT_SQUARE)

    def test_a_circle_the_outline_plane_misses(self):
        ring = {"kind": "circle", "center": [0, 20, 0], "normal": [0, 0, 1], "radius": 10}
        self.refused([ring], paths.OFF_PLANE, outline={"origin": [0, 0, 0], "z": [0, 1, 0]})

    def test_a_sharp_corner_between_two_lines(self):
        self.refused([line((0, 0, 0), (10, 0, 0)), line((10, 0, 0), (10, 10, 0))], paths.SHARP_CORNER)

    def test_a_sharp_corner_next_to_an_arc(self):
        across = quarter([15, 0, 0], [-1, 0, 0], [0, -1, 0], 5)
        self.refused([line((0, 0, 0), (10, 0, 0)), across], paths.SHARP_CORNER)

    def test_two_far_apart_parts_that_pass_closer_than_the_outline_allows(self):
        """A line, then an arc round almost a full turn that ends 0.67 mm from the line."""
        mid = [10 + 5 * math.cos(math.radians(75)), 5 + 5 * math.sin(math.radians(75)), 0]
        end = [10 + 5 * math.cos(math.radians(240)), 5 + 5 * math.sin(math.radians(240)), 0]
        loop = [line((0, 0, 0), (10, 0, 0)), arc((10, 0, 0), end, mid, (10, 5, 0))]
        found = plan(loop, frame=XY_SKETCH)
        self.assertIn("run into itself", found.reason)
        self.assertIn("reaches 1.00 mm", found.reason)
        self.assertIsInstance(plan(loop, frame=XY_SKETCH, points=[[0, 0.1, 0], [0, -0.1, 0]]), paths.PathPlan)

    def test_a_bend_in_3d_that_is_not_tangent(self):
        chain = pipe_in_3d()
        chain[4] = line((15, 20, 5), (16, 20, 20))
        self.refused(chain, paths.BENDS_3D)

    def test_a_free_curve_in_3d(self):
        samples = [[0, 0, 0], [5, 0, 1], [10, 1, 3]]
        curve = {"kind": "other", "type": "NurbsCurve3D", "start": samples[0], "end": samples[-1], "mid": samples[1],
                 "samples": samples, "tangent_start": [1, 0, 0]}
        self.refused([curve, line((10, 1, 3), (10, 1, 9))], paths.BENDS_3D)

    def test_too_many_parts(self):
        with mock.patch.object(paths, "MAX_SEGMENTS", 2):
            self.refused(pipe_with_bend(), paths.TOO_MANY)
        with mock.patch.object(paths, "MAX_POINTS", 3):
            self.refused(pipe_in_3d(), paths.TOO_MANY)

    def test_a_smooth_path_that_crosses_itself(self):
        samples = [[t * t - 1, t * (t * t - 1), 0] for t in [-1.5 + 3 * i / 399 for i in range(400)]]
        tangent = [-3 / math.hypot(-3, 5.75), 5.75 / math.hypot(-3, 5.75), 0]
        curve = {"kind": "other", "type": "NurbsCurve3D", "start": samples[0], "end": samples[-1], "mid": samples[200],
                 "samples": samples, "tangent_start": tangent}
        self.refused([curve], paths.CROSSES, outline={"origin": samples[0], "z": tangent})

    def test_an_outline_wider_than_the_bend_in_a_flat_path(self):
        wide = [[0, y, 0] for y in (-1, 6)]
        found = plan(pipe_with_bend(), points=wide)
        self.assertIn("reaches 6.00 mm", found.reason)
        self.assertIn("radius of 5.00 mm", found.reason)

    def test_the_outline_is_measured_across_the_path_plane_only(self):
        tall = [[0, 0, z] for z in (-50, 50)]
        self.assertIsInstance(plan(pipe_with_bend(), points=tall), paths.PathPlan)

    def test_an_outline_wider_than_a_bend_in_a_3d_path(self):
        found = plan(pipe_in_3d(), points=[[0, y, 0] for y in (-1, 6)])
        self.assertIn("radius of 5.00 mm", found.reason)

    def test_an_outline_wider_than_a_single_arc(self):
        found = plan([quarter([0, 5, 0], [0, -1, 0], [1, 0, 0], 5)], points=[[0, 7, 0]])
        self.assertIn("reaches 7.00 mm", found.reason)

    def test_an_outline_wider_than_the_circle(self):
        ring = {"kind": "circle", "center": [0, 0, 0], "normal": [0, 0, 1], "radius": 10}
        found = plan([ring], points=[[10, 0, 0], [0, 0, 0]], outline={"origin": [0, 0, 0], "z": [0, 1, 0]})
        self.assertIn("reaches 10.00 mm", found.reason)


if __name__ == "__main__":
    unittest.main()
