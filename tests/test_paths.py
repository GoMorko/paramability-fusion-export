"""The sweep path as the recipe holds it: ordering, orientation, classes, written forms and refusals."""
import math
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import close

from lib.geometry import vec
from lib.design_model.paths import checks as path_checks, curves as path_curves, model as path_model, planner
from lib.design_model.paths import tolerances, words
from lib.design_model.problem import Problem
from lib.translator.paths import path_limits, path_rebuilt

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


def recipe_plan(path, frame, points, options=None):
    """The planner as the recipe output asks it: with the recipe's caps and spline fit."""
    return planner.plan(path, frame, points, options or path_limits.options())


def plan(curves, points=SQUARE, outline=FRAME, **extra):
    """The plan of a path record; `extra` are more keys of that record (`closed`, `frame`)."""
    return recipe_plan(path_of(curves, **extra), outline, points)


def pipe_with_bend():
    """Along +x, a quarter turn to +y, along +y: all in the plane z = 0."""
    return [line((0, 0, 0), (10, 0, 0)), quarter([10, 5, 0], [0, -1, 0], [1, 0, 0], 5), line((15, 5, 0), (15, 20, 0))]


def pipe_in_3d():
    """Along +x, a quarter turn to +y, along +y, a quarter turn to +z, along +z."""
    return [line((0, 0, 0), (10, 0, 0)), quarter([10, 5, 0], [0, -1, 0], [1, 0, 0], 5),
            line((15, 5, 0), (15, 15, 0)), quarter([15, 15, 5], [0, 0, -1], [0, 1, 0], 5),
            line((15, 20, 5), (15, 20, 20))]


def sweep_with(recipe_path, version=15):
    sketch = {"on": {"origin": [0, 0, 0], "normal": [1, 0, 0], "xDir": [0, 1, 0]},
              "outer": {"kind": "circle", "center": [0, 0], "radius": 1}}
    return {"schema": "paramability.recipe", "version": version, "features": [
        {"id": "sweep_1", "kind": "sweep", "sketch": sketch, "path": recipe_path, "combine": "new"}]}


class ClassTest(unittest.TestCase):
    def test_lines_that_continue_straight_are_one_line(self):
        found = plan([line((10, 0, 0), (30, 0, 0)), line((0, 0, 0), (10, 0, 0))])
        self.assertEqual((found.kind, found.length, found.direction, len(found.curves)),
                         ("line", 30.0, [1.0, 0.0, 0.0], 1))
        self.assertIsNone(found.recipe)

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

    def test_without_a_spline_fit_a_free_curve_is_too_complex(self):
        samples = [[x, 0.02 * x * x, 0] for x in [i * 0.1 for i in range(201)]]
        curve = {"kind": "other", "type": "NurbsCurve3D", "start": samples[0], "end": samples[-1], "mid": samples[100],
                 "samples": samples, "tangent_start": [1, 0, 0], "tangent_end": [0.9285, 0.3714, 0]}
        found = planner.plan(path_of([curve], frame=XY_SKETCH), FRAME, SQUARE, path_model.PathOptions())
        self.assertEqual((found.code, found.words), ("too_complex", words.TOO_COMPLEX))

    def test_the_caps_on_the_parts_of_a_path_are_the_destinations(self):
        def planned(**caps):
            return planner.plan(path_of(pipe_with_bend()), FRAME, SQUARE, path_model.PathOptions(**caps))
        self.assertEqual(planned().kind, "flat")
        self.assertEqual(planned(max_segments=2).code, "too_many")

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

        self.assertIsInstance(plan(with_kink(1.5), points=[[0, 0, 0]], frame=XY_SKETCH), path_model.PathPlan)
        self.assertEqual(plan(with_kink(2.5), points=[[0, 0, 0]], frame=XY_SKETCH).words, words.SHARP_CORNER)


class OrderTest(unittest.TestCase):
    def test_shuffled_and_flipped_curves_come_out_in_path_order(self):
        a, b, c = pipe_with_bend()
        found = plan([dict(c, start=c["end"], end=c["start"]), b, a])
        self.assertEqual([k["kind"] for k in found.curves], ["line", "arc", "line"])
        self.assertTrue(close(found.curves[0]["start"], [0, 0, 0]) and close(found.curves[-1]["end"], [15, 20, 0]))

    def test_a_path_listed_from_its_far_end_is_turned_round(self):
        a, b, c = pipe_with_bend()
        found = plan(path_curves.turned_round([a, b, c]))
        self.assertTrue(found.reversed)
        self.assertTrue(close(found.start, [0, 0, 0]) and close(found.end, [15, 20, 0]))
        self.assertTrue(close(found.curves[1]["end"], [15, 5, 0]))
        self.assertTrue(close(found.curves[1]["mid"], [10 + 5 * S2, 5 - 5 * S2, 0]))

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


class OptionsTest(unittest.TestCase):
    """Paths asked for a sweep step (twist, taper, parallel): a line and an arc get a recipe path too."""

    def planned(self, curves, **options):
        return recipe_plan(path_of(curves), FRAME, SQUARE, path_limits.options(**options))

    def test_a_line_becomes_a_corners_path_of_its_two_ends(self):
        found = self.planned([line((0, 0, 0), (30, 0, 0))], as_step=True)
        self.assertEqual((found.kind, found.recipe["points"]), ("line", [[0, 0, 0], [30, 0, 0]]))
        self.assertIsNone(self.planned([line((0, 0, 0), (30, 0, 0))]).recipe)

    def test_an_arc_becomes_a_flat_path(self):
        found = self.planned([quarter([0, 5, 0], [0, -1, 0], [1, 0, 0], 5)], as_step=True)
        self.assertEqual((found.kind, [s["kind"] for s in found.recipe["segments"]]), ("flat", ["arc"]))

    def test_a_circle_with_a_taper_or_a_kept_direction_is_refused(self):
        ring = {"kind": "circle", "center": [0, 5, 0], "normal": [0, 0, 1], "radius": 5}
        for option, reason in (("tapered", words.CLOSED_TAPER), ("fixed", words.CLOSED_PARALLEL)):
            with self.subTest(option):
                self.assertEqual(self.planned([ring], as_step=True, **{option: True}).words, reason)

    def test_a_twisted_circle_is_a_closed_flat_path_of_two_half_arcs(self):
        ring = {"kind": "circle", "center": [0, 5, 0], "normal": [0, 0, 1], "radius": 5}
        found = self.planned([ring], as_step=True, twisted=True)
        self.assertEqual((found.kind, found.closed), ("flat", True))
        self.assertEqual(found.winding * found.recipe["on"]["normal"][2], 1.0)
        self.assertTrue(close(found.start, [0, 0, 0]) and close(found.end, found.start))
        recipe = found.recipe
        self.assertEqual([s["kind"] for s in recipe["segments"]], ["arc", "arc"])
        self.assertEqual(recipe["segments"][-1]["to"], recipe["start"])
        self.assertTrue(recipe["closed"])
        self.assertEqual(check_recipe(sweep_with(recipe, 16)), [])

    def test_a_kept_direction_needs_the_path_to_keep_moving_away_from_the_outline_plane(self):
        self.assertEqual(self.planned(pipe_with_bend(), fixed=True, as_step=True).words, words.TURNS_BACK)
        eased = [line((0, 0, 0), (10, 0, 0)), quarter([10, 10, 0], [0, -1, 0], [0.5, -S2 * 1.2247, 0], 10)]
        self.assertIsNone(getattr(self.planned(eased, fixed=True, as_step=True), "reason", None))

    def test_a_kept_direction_skips_the_bend_checks(self):
        eased = [line((0, 0, 0), (10, 0, 0)), quarter([10, 10, 0], [0, -1, 0], [0.5, -S2 * 1.2247, 0], 10)]
        wide = [[0, y, 0] for y in (-14, 14)]
        self.assertIsInstance(recipe_plan(path_of(eased), FRAME, wide, path_limits.options(as_step=True)), Problem)
        kept = recipe_plan(path_of(eased), FRAME, wide, path_limits.options(as_step=True, fixed=True))
        self.assertNotIsInstance(kept, Problem)

    def test_a_twist_counts_the_outline_across_the_path_plane_at_a_bend(self):
        tall = [[0, 0, z] for z in (-9, 9)]
        flat_only = recipe_plan(path_of(pipe_with_bend()), FRAME, tall, path_limits.options())
        self.assertNotIsInstance(flat_only, Problem)
        twisted = recipe_plan(path_of(pipe_with_bend()), FRAME, tall, path_limits.options(as_step=True, twisted=True))
        self.assertIsInstance(twisted, Problem)


def rounded_rectangle():
    """A 40 by 20 rounded rectangle (corner radius 5) in the plane z = 0, counter clockwise, listed from its left side."""
    def corner(cx, cy, from_deg, to_deg):
        def at(deg):
            return (cx + 5 * math.cos(math.radians(deg)), cy + 5 * math.sin(math.radians(deg)), 0)
        return arc(at(from_deg), at(to_deg), at((from_deg + to_deg) / 2), (cx, cy, 0))

    return [line((0, 15, 0), (0, 5, 0)), corner(5, 5, 180, 270), line((5, 0, 0), (35, 0, 0)), corner(35, 5, 270, 360),
            line((40, 5, 0), (40, 15, 0)), corner(35, 15, 0, 90), line((35, 20, 0), (5, 20, 0)), corner(5, 15, 90, 180)]


def at_point(point, normal):
    """The outline's plane through `point` square to `normal`, and a small outline around the point."""
    plane = {"origin": list(point), "z": list(normal)}
    first = vec.unit(vec.cross(normal, [0, 0, 1]))
    return plane, [vec.add(point, vec.add(vec.scale(first, a), [0, 0, b])) for a in (-1, 1) for b in (-1, 1)]


class ClosedTest(unittest.TestCase):
    """A closed chain in one plane is cut open where it meets the outline's plane and written as a closed flat path."""

    def closed_at(self, point, normal, curves=None, **options):
        plane, points = at_point(point, normal)
        found = recipe_plan(path_of(curves or rounded_rectangle(), frame=XY_SKETCH), plane, points,
                           path_limits.options(**options))
        if not isinstance(found, Problem):
            self.assertTrue(found.closed)
            self.assertEqual(found.recipe["segments"][-1]["to"], found.recipe["start"])
            self.assertTrue(found.recipe["closed"])
            self.assertEqual(check_recipe(sweep_with(found.recipe, 16)), [])
        return found

    def kinds(self, found):
        return [s["kind"] for s in found.recipe["segments"]]

    def test_a_chain_met_inside_a_line_splits_the_line(self):
        found = self.closed_at((20, 0, 0), [1, 0, 0])
        self.assertEqual(self.kinds(found), ["line", "arc", "line", "arc", "line", "arc", "line", "arc", "line"])
        self.assertTrue(close(found.recipe["start"], [20, 0]) and close(found.recipe["segments"][0]["to"], [35, 0]))
        self.assertTrue(close(found.start, [20, 0, 0]) and close(found.end, found.start))
        self.assertTrue(close(found.direction, [1, 0, 0]))
        self.assertEqual((found.winding, found.kind), (1, "flat"))
        self.assertAlmostEqual(found.length, 80 + 10 * math.pi, places=6)

    def test_a_chain_met_inside_an_arc_splits_the_arc(self):
        found = self.closed_at((5 * S2 + 35, 5 - 5 * S2, 0), [S2, S2, 0])
        self.assertEqual(self.kinds(found), ["arc", "line", "arc", "line", "arc", "line", "arc", "line", "arc"])
        self.assertTrue(close(found.recipe["start"], [35 + 5 * S2, 5 - 5 * S2], 1e-8))
        self.assertTrue(close(found.recipe["segments"][0]["to"], [40, 5], 1e-8))

    def test_a_chain_met_at_the_joint_of_a_line_and_an_arc_is_not_split(self):
        found = self.closed_at((35, 0, 0), [1, 0, 0])
        self.assertEqual(self.kinds(found), ["arc", "line", "arc", "line", "arc", "line", "arc", "line"])
        self.assertTrue(close(found.recipe["start"], [35, 0]))

    def test_a_chain_met_inside_a_free_curve_splits_it_into_two_fitted_parts(self):
        side = [[5 + 0.5 * k, 0.2 * math.sin(math.pi * 0.5 * k / 30), 0.0] for k in range(61)]
        curve = {"kind": "other", "start": side[0], "end": side[-1], "samples": side}
        rim = rounded_rectangle()
        rim[2] = curve
        rim[1] = dict(rim[1], end=side[0])
        rim[3] = dict(rim[3], start=side[-1])
        found = self.closed_at((20, 0.2, 0), [1, 0, 0], rim)
        self.assertEqual(found.recipe["segments"][0]["kind"], "spline")
        self.assertEqual(found.recipe["segments"][-1]["kind"], "spline")
        self.assertLessEqual(path_checks.seam_turn(found.recipe["start"], found.recipe["segments"]),
                             tolerances.SMOOTH_JOIN_DEG)

    def test_a_chain_listed_the_other_way_round_runs_clockwise(self):
        backwards = path_curves.turned_round(rounded_rectangle())
        found = self.closed_at((20, 0, 0), [1, 0, 0], backwards)
        self.assertEqual(found.winding, -1)
        self.assertTrue(close(found.direction, [-1, 0, 0]))

    def test_the_outline_may_sit_inside_the_loop_as_long_as_it_clears_the_bends(self):
        plane, points = at_point((20, 0, 0), [1, 0, 0])
        points = [vec.add(p, [0, 2, 0]) for p in points]
        self.assertNotIsInstance(recipe_plan(path_of(rounded_rectangle(), frame=XY_SKETCH), plane, points), Problem)

    SQUARE_LOOP = [line((0, 0, 0), (10, 0, 0)), line((10, 0, 0), (10, 10, 0)), line((10, 10, 0), (0, 10, 0)),
                   line((0, 10, 0), (0, 0, 0))]

    def test_sharp_corners_between_lines_are_mitred(self):
        found = self.closed_at((5, 0, 0), [1, 0, 0], self.SQUARE_LOOP)
        self.assertEqual(self.kinds(found), ["line"] * 5)
        self.assertIsNone(found.moved)
        self.assertEqual(self.closed_at((5, 0, 0), [1, 0, 0], self.SQUARE_LOOP, twisted=True).words,
                         words.SHARP_CORNER)

    def test_an_outline_on_a_corner_is_carried_to_the_middle_of_the_line_it_is_square_to(self):
        found = self.closed_at((10, 0, 0), [1, 0, 0], self.SQUARE_LOOP)
        self.assertTrue(close(found.start, [5, 0, 0]) and close(found.moved, [-5, 0, 0]))
        self.assertTrue(close(found.direction, [-1, 0, 0]))
        self.assertAlmostEqual(found.length, 40.0)
        self.assertEqual(self.closed_at((10, 0, 0), [1, 0, 0], self.SQUARE_LOOP, twisted=True).words,
                         words.CLOSED_AT_CORNER)

    def test_corners_closer_than_the_outline_needs_are_refused(self):
        plane, points = at_point((5, 0, 0), [1, 0, 0])
        wide = [vec.add(p, vec.scale(vec.sub(p, [5, 0, 0]), 5.0)) for p in points]
        found = recipe_plan(path_of(self.SQUARE_LOOP, frame=XY_SKETCH), plane, wide)
        self.assertEqual(found.code, "corner_too_tight")

    def test_a_line_between_two_corners_needs_room_for_both_mitres(self):
        """Each 90 degree corner needs 6 mm of straight path: the 10 mm sides have room for one mitre, not two."""
        corners = [(0, 0, 0), (30, 0, 0), (30, 10, 0), (0, 10, 0)]
        loop = [line(a, b) for a, b in zip(corners, corners[1:] + corners[:1])]
        plane, points = at_point((15, 0, 0), [1, 0, 0])
        wide = [vec.add(p, vec.scale(vec.sub(p, [15, 0, 0]), 5.0)) for p in points]
        found = recipe_plan(path_of(loop, frame=XY_SKETCH), plane, wide)
        self.assertEqual(found.words, words.CORNER_TOO_TIGHT % (12.0, 10.0))

    def test_a_closed_chain_that_bends_in_3d_is_refused(self):
        skew = [line((0, 0, 0), (10, 0, 0)), line((10, 0, 0), (10, 10, 0)), line((10, 10, 0), (0, 10, 5)),
                line((0, 10, 5), (0, 0, 0))]
        self.assertEqual(self.closed_at((5, 0, 0), [1, 0, 0], skew).words, words.CLOSED_3D)

    def test_a_plane_that_misses_the_chain_is_refused(self):
        self.assertEqual(self.closed_at((60, 0, 0), [1, 0, 0]).words, words.OFF_PLANE)

    def test_a_chain_that_meets_the_plane_at_a_slant_is_refused(self):
        self.assertEqual(self.closed_at((20, 0, 0), [S2, S2, 0]).words, words.NOT_SQUARE)

    def test_a_taper_or_a_kept_direction_is_refused(self):
        for option, reason in (("tapered", words.CLOSED_TAPER), ("fixed", words.CLOSED_PARALLEL)):
            with self.subTest(option):
                found = self.closed_at((20, 0, 0), [1, 0, 0], as_step=True, **{option: True})
                self.assertEqual(found.words, reason)

    def test_an_outline_wider_than_the_bend_is_refused(self):
        plane, points = at_point((20, 0, 0), [1, 0, 0])
        wide = [vec.add(p, [0, 6, 0]) for p in points]
        found = recipe_plan(path_of(rounded_rectangle(), frame=XY_SKETCH), plane, wide)
        self.assertIsInstance(found, Problem)

    def test_a_loop_whose_parts_pass_closer_than_the_outline_allows_is_refused(self):
        ends = [(20 + 2 * math.sin(math.radians(a)), 2 - 2 * math.cos(math.radians(a))) for a in range(0, 181, 5)]
        back = [(-x, 4 - y) for x, y in ends]
        slim = [[x, y, 0.0] for x, y in [(-20, 0)] + ends + back + [(-20, 0)]]
        self.assertIsNotNone(path_checks.overlap_problem(slim, 2.2, True))
        self.assertIsNone(path_checks.overlap_problem(slim, 1.9, True))

    def test_the_start_and_end_of_a_closed_loop_are_neighbours(self):
        circle = [[10 * math.cos(t), 10 * math.sin(t), 0.0] for t in (2 * math.pi * k / 120 for k in range(121))]
        circle[-1] = circle[0]
        self.assertIsNone(path_checks.overlap_problem(circle, 1.0, True))
        self.assertIsNotNone(path_checks.overlap_problem(circle, 1.0, False))

    def test_the_written_directions_at_the_seam_are_compared(self):
        circle = [{"kind": "arc", "through": [10.0, 10.0], "to": [0.0, 20.0]},
                  {"kind": "arc", "through": [-10.0, 10.0], "to": [0.0, 0.0]}]
        self.assertAlmostEqual(path_checks.seam_turn([0.0, 0.0], circle), 0.0, places=6)
        triangle = [{"kind": "line", "to": [10.0, 0.0]}, {"kind": "line", "to": [10.0, 10.0]},
                    {"kind": "line", "to": [0.0, 0.0]}]
        self.assertAlmostEqual(path_checks.seam_turn([0.0, 0.0], triangle), 135.0, places=6)


class RefusalTest(unittest.TestCase):
    def refused(self, curves, reason, **kwargs):
        found = plan(curves, **kwargs)
        self.assertIsInstance(found, Problem)
        self.assertEqual(found.words, reason)

    def test_a_path_the_capture_calls_closed_is_not_taken_as_open(self):
        self.refused([line((0, 0, 0), (30, 0, 0))], words.CLOSED, closed=True)

    def test_curves_that_do_not_join(self):
        self.refused([line((0, 0, 0), (10, 0, 0)), line((10, 1, 0), (20, 1, 0))], words.NOT_ONE_CHAIN)

    def test_curves_that_branch(self):
        self.refused([line((0, 0, 0), (10, 0, 0)), line((10, 0, 0), (20, 0, 0)), line((10, 0, 0), (10, 10, 0))],
                     words.NOT_ONE_CHAIN)

    def test_a_path_that_is_not_sketch_curves_or_edges(self):
        found = recipe_plan({"kind": "other", "curves": []}, FRAME, SQUARE)
        self.assertEqual(found.words, words.NOT_SKETCH)

    def test_a_free_curve_without_samples(self):
        broken = {"kind": "other", "type": "NurbsCurve3D", "start": [0, 0, 0], "end": [9, 0, 0], "samples": []}
        self.refused([broken], words.UNREADABLE)

    def test_a_zero_length_line(self):
        self.refused([line((0, 0, 0), (0, 0, 0))], words.UNREADABLE)

    def test_an_ellipse(self):
        ellipse = {"kind": "ellipse", "center": [0, 0, 0], "major_dir": [1, 0, 0], "major_radius": 4, "minor_radius": 2}
        self.refused([ellipse], words.UNKNOWN_CURVE)

    def test_a_path_through_the_middle_of_the_outline(self):
        self.refused([line((-10, 0, 0), (10, 0, 0))], words.BOTH_SIDES)

    def test_a_path_that_never_reaches_the_outline(self):
        self.refused([line((5, 0, 0), (20, 0, 0))], words.OFF_PLANE)

    def test_a_path_that_leaves_the_outline_at_a_slant(self):
        self.refused([line((0, 0, 0), (10, 10, 0))], words.NOT_SQUARE)

    def test_a_circle_whose_plane_lies_flat_on_the_outline(self):
        ring = {"kind": "circle", "center": [0, 0, 0], "normal": [1, 0, 0], "radius": 10}
        self.refused([ring], words.NOT_SQUARE)

    def test_a_circle_the_outline_plane_misses(self):
        ring = {"kind": "circle", "center": [0, 20, 0], "normal": [0, 0, 1], "radius": 10}
        self.refused([ring], words.OFF_PLANE, outline={"origin": [0, 0, 0], "z": [0, 1, 0]})

    def test_a_sharp_corner_between_two_lines_is_mitred_unless_the_outline_twists(self):
        corner = [line((0, 0, 0), (10, 0, 0)), line((10, 0, 0), (10, 10, 0))]
        found = plan(corner)
        self.assertEqual([s["kind"] for s in found.recipe["segments"]], ["line", "line"])
        twisted = recipe_plan(path_of(corner), FRAME, SQUARE, path_limits.options(as_step=True, twisted=True))
        self.assertEqual((twisted.words, twisted.cause), (words.SHARP_CORNER, "sharpCorner"))

    def test_a_sharp_corner_of_an_open_path_too_tight_for_its_outline(self):
        wide = [[0, 4 * y, z] for y in (-1, 1) for z in (-1, 1)]
        found = plan([line((0, 0, 0), (3, 0, 0)), line((3, 0, 0), (3, 10, 0))], points=wide)
        self.assertEqual(found.code, "corner_too_tight")

    def test_a_sharp_corner_next_to_an_arc(self):
        across = quarter([15, 0, 0], [-1, 0, 0], [0, -1, 0], 5)
        self.refused([line((0, 0, 0), (10, 0, 0)), across], words.SHARP_CORNER)

    def test_two_far_apart_parts_that_pass_closer_than_the_outline_allows(self):
        """A line, then an arc round almost a full turn that ends 0.67 mm from the line."""
        mid = [10 + 5 * math.cos(math.radians(75)), 5 + 5 * math.sin(math.radians(75)), 0]
        end = [10 + 5 * math.cos(math.radians(240)), 5 + 5 * math.sin(math.radians(240)), 0]
        loop = [line((0, 0, 0), (10, 0, 0)), arc((10, 0, 0), end, mid, (10, 5, 0))]
        found = plan(loop, frame=XY_SKETCH)
        self.assertIn("run into itself", found.words)
        self.assertIn("reaches 1.00 mm", found.words)
        self.assertIsInstance(plan(loop, frame=XY_SKETCH, points=[[0, 0.1, 0], [0, -0.1, 0]]), path_model.PathPlan)

    def test_a_bend_in_3d_that_is_not_tangent(self):
        chain = pipe_in_3d()
        chain[4] = line((15, 20, 5), (16, 20, 20))
        self.refused(chain, words.BENDS_3D)

    def test_a_free_curve_in_3d(self):
        samples = [[0, 0, 0], [5, 0, 1], [10, 1, 3]]
        curve = {"kind": "other", "type": "NurbsCurve3D", "start": samples[0], "end": samples[-1], "mid": samples[1],
                 "samples": samples, "tangent_start": [1, 0, 0]}
        self.refused([curve, line((10, 1, 3), (10, 1, 9))], words.BENDS_3D)

    def test_too_many_parts(self):
        with mock.patch.object(path_limits, "MAX_SEGMENTS", 2):
            self.refused(pipe_with_bend(), words.TOO_MANY)
        with mock.patch.object(path_limits, "MAX_POINTS", 3):
            self.refused(pipe_in_3d(), words.TOO_MANY)

    def test_a_smooth_path_that_crosses_itself(self):
        samples = [[t * t - 1, t * (t * t - 1), 0] for t in [-1.5 + 3 * i / 399 for i in range(400)]]
        tangent = [-3 / math.hypot(-3, 5.75), 5.75 / math.hypot(-3, 5.75), 0]
        curve = {"kind": "other", "type": "NurbsCurve3D", "start": samples[0], "end": samples[-1], "mid": samples[200],
                 "samples": samples, "tangent_start": tangent}
        self.refused([curve], words.CROSSES, outline={"origin": samples[0], "z": tangent})

    def test_an_outline_wider_than_the_tightest_bend_is_refused_in_flat_and_3d_paths(self):
        wide = [[0, y, 0] for y in (-1, 6)]
        found = plan(pipe_with_bend(), points=wide)
        self.assertIn("reaches 6.00 mm", found.words)
        self.assertIsInstance(plan(pipe_in_3d(), points=wide), Problem)
        self.assertIsInstance(plan(pipe_in_3d()), path_model.PathPlan)

    def test_the_outline_is_measured_across_the_path_plane_only(self):
        tall = [[0, 0, z] for z in (-50, 50)]
        self.assertIsInstance(plan(pipe_with_bend(), points=tall), path_model.PathPlan)


class AxisReachTest(unittest.TestCase):
    """A path of one arc or a full circle is a revolve about its axis: only an outline that reaches the axis is refused,
    one on the outer side may be as wide as it likes."""
    OUTER = [[0, y, z] for y in (-4, 0) for z in (-2, 2)]
    INNER = [[0, y, z] for y in (0, 4) for z in (-2, 2)]

    def test_an_outline_on_the_outer_side_of_an_arc_is_not_refused(self):
        found = plan([quarter([0, 3, 0], [0, -1, 0], [1, 0, 0], 3)], points=self.OUTER)
        self.assertIsInstance(found, path_model.PathPlan)
        self.assertIn("reaches 4.00 mm", plan([quarter([0, 3, 0], [0, -1, 0], [1, 0, 0], 3)], points=self.INNER).words)

    def test_an_outline_on_the_outer_side_of_a_circle_is_not_refused(self):
        ring = {"kind": "circle", "center": [0, 3, 0], "normal": [1, 0, 0], "radius": 3}
        frame = {"origin": [0, 0, 0], "z": [0, 0, 1]}
        outer = [[x, y, 0] for x in (-2, 2) for y in (-4, 0)]
        self.assertIsInstance(plan([ring], points=outer, outline=frame), path_model.PathPlan)
        self.assertIsInstance(plan([ring], points=[[x, y, 0] for x in (-2, 2) for y in (0, 4)], outline=frame), Problem)


class RebuiltTest(unittest.TestCase):
    """A flat path read back from written numbers is tested against the app's rules (`rebuilt_refusal`)."""

    ON = {"origin": [0, 0, 0], "normal": [0, 0, 1], "xDir": [1, 0, 0]}
    NORMAL = [1.0, 0.0, 0.0]

    def recipe(self, *segments, start=(0, 0), **extra):
        return dict({"kind": "flat", "on": self.ON, "start": list(start), "segments": list(segments)}, **extra)

    def refusal(self, recipe, reach=1.0, **options):
        return path_rebuilt.rebuilt_refusal(path_rebuilt.flat_curves(recipe), recipe.get("closed", False), self.NORMAL, reach,
                                     **options)

    def pipe(self, run=20.0, radius=10.0):
        """Along x, a quarter arc turning to +y, along y."""
        return self.recipe({"kind": "line", "to": [run, 0]},
                           {"kind": "arc", "through": [run + radius * S2, radius * (1 - S2)],
                            "to": [run + radius, radius]},
                           {"kind": "line", "to": [run + radius, radius + 20]})

    def test_a_path_that_keeps_every_rule_is_not_refused(self):
        self.assertIsNone(self.refusal(self.pipe()))

    def test_the_curves_are_the_written_points_in_the_placements_frame(self):
        first, bend, last = path_rebuilt.flat_curves(self.pipe())
        self.assertEqual((first["end"], bend["kind"], last["end"]), ([20.0, 0.0, 0.0], "arc", [30.0, 30.0, 0.0]))

    def test_an_outline_that_reaches_the_bend_centre_is_refused(self):
        self.assertIn("bends in a radius", self.refusal(self.pipe(radius=3.0), reach=3.0).reason)
        self.assertIsNone(self.refusal(self.pipe(radius=3.0), reach=2.9))

    def test_a_path_that_does_not_leave_the_outline_square_is_refused(self):
        slanted = self.recipe({"kind": "line", "to": [20, 5]})
        self.assertEqual(self.refusal(slanted).reason, words.NOT_SQUARE)

    def test_a_path_that_leaves_the_outline_the_other_way_is_refused_when_the_way_is_given(self):
        back = self.recipe({"kind": "line", "to": [-20, 0]})
        self.assertIsNone(self.refusal(back, leaves=None))
        self.assertEqual(self.refusal(back, leaves=[1.0, 0.0, 0.0]).reason, words.TURNED_ROUND)

    def test_a_corner_between_two_lines_is_refused_unless_it_is_mitred_with_room_for_the_outline(self):
        corner = self.recipe({"kind": "line", "to": [20, 0]}, {"kind": "line", "to": [20, 20]})
        self.assertEqual(self.refusal(corner).reason, words.SHARP_CORNER)
        self.assertIsNone(self.refusal(corner, mitres=True))
        self.assertIn("too close", self.refusal(corner, reach=21.0, mitres=True).reason)

    def test_a_path_that_crosses_itself_is_refused(self):
        """Along x, three quarters of a turn about (20, 10), then back down across the first leg."""
        loop = self.recipe({"kind": "line", "to": [20, 0]},
                           {"kind": "arc", "through": [20 + 10 * S2, 10 + 10 * S2], "to": [10, 10]},
                           {"kind": "line", "to": [10, -5]})
        self.assertEqual(self.refusal(loop, reach=0.1).reason, words.CROSSES)

    def test_a_closed_path_of_smooth_parts_is_not_refused(self):
        stadium = self.recipe({"kind": "line", "to": [20, 0]}, {"kind": "arc", "through": [25, 5], "to": [20, 10]},
                              {"kind": "line", "to": [0, 10]}, {"kind": "arc", "through": [-5, 5], "to": [0, 0]},
                              closed=True)
        self.assertIsNone(self.refusal(stadium, reach=1.0))

    def test_an_outline_kept_in_one_direction_needs_the_path_to_keep_rising(self):
        self.assertEqual(self.refusal(self.pipe(), fixed=True).reason, words.TURNS_BACK)
        sixty = self.recipe({"kind": "line", "to": [20, 0]},
                            {"kind": "arc", "through": [25, 10 - 10 * math.sin(math.radians(60))],
                             "to": [20 + 10 * math.cos(math.radians(30)), 5]})
        self.assertIsNone(self.refusal(sixty, fixed=True))

    def test_a_segment_that_is_a_free_curve_cannot_be_rebuilt(self):
        with self.assertRaises(ValueError):
            path_rebuilt.flat_curves(self.recipe({"kind": "spline", "through": [[5, 1]], "to": [10, 0]}))

    def test_a_line_without_length_cannot_be_read(self):
        self.assertEqual(self.refusal(self.recipe({"kind": "line", "to": [0, 0]})).reason, words.UNREADABLE)


if __name__ == "__main__":
    unittest.main()
