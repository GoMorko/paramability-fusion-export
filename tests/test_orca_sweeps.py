"""Sweeps, lofts and spline outlines in the Orca copy (`orca_translate/sweeps.py`, `lofts.py`, `splines.py`): what
Orca is told to build, which parameters follow, and which steps are left out with which cause, against the capture
fixtures and the captures of tests/orca_sweeps.py."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests import orca_sweeps as sw
from tests.test_orca_revolve import on_offset_plane
from tests.test_orca_extents import limit_of, outcome, run
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import BooleanMode, EntityType, ExtrudeEnd, FeatureType, SketchShape
from lib.orca_translate import FIXED, VARIABLE, causes, limits
from lib.orca_translate import splines, sweep_splines
from lib.orca_translate.lofts import Lofted
from lib.orca_translate.solid import Solid
from lib.orca_translate.sweeps import carried
from lib.design_model.paths import planner
from lib.design_model.paths.model import PathOptions
from lib.design_model.steps.sweep import profile_points
from lib.geometry import spline_fit


def types(result):
    return [f.type for f in result.recipe.features]


def left_causes(capture):
    return [g["cause"] for g in run(capture).left_out]


def sweep_data(capture):
    return next(i for i in capture["items"] if i["type"] == "SweepFeature")["data"]


class SweepTest(unittest.TestCase):
    def test_a_bent_path_is_an_orca_sweep_along_its_curves_in_order_from_the_outline(self):
        for name in ("sweep_pipe", "sweep_far_end"):
            with self.subTest(name):
                result = run(load_capture(name))
                self.assertEqual(result.left_out, [])
                self.assertEqual(types(result), [FeatureType.SKETCH, FeatureType.SKETCH, FeatureType.SWEEP])
                outline, path, made = result.recipe.features
                self.assertEqual((made.sketch_ref, made.sweep_path_ref, made.mode), (0, 1, BooleanMode.NEW))
                self.assertEqual(outline.shape, SketchShape.CIRCLE)
                kinds = [e.type for e in path.entities]
                self.assertEqual(kinds, [EntityType.LINE, EntityType.ARC, EntityType.LINE])
                # Orca starts the wire at the free end of the first entity: the outline sits there.
                self.assertAlmostEqual(math.dist(path.entities[0].p0, (0.0, 0.0)), 0.0, places=9)
                for before, after in zip(path.entities, path.entities[1:]):
                    self.assertAlmostEqual(math.dist(before.p1, after.p0), 0.0, places=6)

    def test_a_closed_path_starts_and_ends_at_the_outline(self):
        result = run(load_capture("sweep_closed_rim"))
        self.assertEqual(result.left_out, [])
        path = result.recipe.features[1]
        self.assertAlmostEqual(math.dist(path.entities[0].p0, (0.0, 0.0)), 0.0, places=9)
        self.assertAlmostEqual(math.dist(path.entities[-1].p1, path.entities[0].p0), 0.0, places=6)

    def test_a_straight_path_is_an_extrude_and_a_circle_a_revolve(self):
        straight = run(load_capture("sweep_straight"))
        self.assertEqual(types(straight), [FeatureType.SKETCH, FeatureType.EXTRUDE])
        extrude = straight.recipe.features[1]
        self.assertEqual((extrude.extrude_end, extrude.distance), (ExtrudeEnd.BLIND, 40.0))
        ring = run(load_capture("sweep_ring"))
        self.assertEqual(types(ring), [FeatureType.SKETCH, FeatureType.REVOLVE])
        self.assertEqual(ring.recipe.features[1].revolve_angle, 360.0)

    def test_an_arc_path_turns_the_way_fusion_turned_it(self):
        # A pin cut through where the bend ends meets it; the same pin on the mirrored side meets nothing.
        for clockwise in (False, True):
            end = -10.0 if clockwise else 10.0
            for y, cut in ((end, True), (-end, False)):
                with self.subTest(clockwise=clockwise, y=y):
                    capture = sw.block_and_bend(clockwise)
                    pin = sw.extrude(5, "Pin", [sw.profile("Pin sketch", dict(sw.UP, origin=[1.0, y, -5.0]),
                                                           sw.circle(0.5))], operation="cut",
                                     side_one={"kind": "distance", "distance": 10.0, "taper_deg": 0.0},
                                     end_offset=10.0, target_box_before=capture["target"]["box"])
                    capture["items"] += [sw.sketch_item(4, "Pin sketch"), pin]
                    self.assertEqual(left_causes(capture), [] if cut else [causes.MISSES_PART])

    def test_the_outline_follows_its_sizes_and_tells_how_far_it_may_grow_against_the_bend(self):
        result = run(sw.bar_along_bend(width=6.0, height=4.0))
        outline = result.recipe.features[0]
        self.assertEqual(outline.expr, {"width": "bar_w", "height": "bar_h"})
        width, height = outcome(result, "bar_w"), outcome(result, "bar_h")
        self.assertEqual((width["outcome"], height["outcome"]), (VARIABLE, VARIABLE))
        # The bend has a radius of 10: the bar may grow to twice that across the path's plane, and freely along it.
        # Neither side may reach zero, where the outline vanishes.
        self.assertEqual(limit_of(width).low, 0.01)
        self.assertAlmostEqual(limit_of(width).high, 20.0, delta=0.11)
        self.assertEqual(limit_of(width).why[1], limits.SWEEP_BEND)
        self.assertEqual((limit_of(height).low, limit_of(height).high), (0.01, None))

    def test_sizes_that_move_the_outline_plane_are_marked(self):
        capture = sw.bar_along_bend()
        on_offset_plane(capture, sweep_data(capture)["profiles"][0])
        result = run(capture)
        self.assertIn(FeatureType.SWEEP, types(result))
        self.assertEqual(outcome(result, "lift")["outcome"], FIXED)

    def test_the_sizes_of_the_path_keep_their_numbers(self):
        result = run(load_capture("sweep_pipe"))
        self.assertEqual(outcome(result, "bend_mm")["outcome"], FIXED)

    def test_the_shape_for_later_cuts_is_the_outline_carried_along_the_path(self):
        capture = load_capture("sweep_pipe")
        data = sweep_data(capture)
        profile = data["profiles"][0]
        found = planner.plan(data["path"], profile["frame"], profile_points(profile), PathOptions())
        loops = [loop["curves"] for loop in profile["loops"]]
        box = Solid([("add", carried(profile["frame"], loops, found))]).box()
        for got, want in zip(box["min"] + box["max"], capture["target"]["box"]["min"] + capture["target"]["box"]["max"]):
            self.assertAlmostEqual(got, want, delta=0.01)

    def test_a_later_cut_inside_a_swept_groove_meets_nothing_and_is_left_out(self):
        self.assertEqual(left_causes(sw.groove_then_hole(depth=1.0)), [causes.MISSES_PART])
        self.assertEqual(left_causes(sw.groove_then_hole(depth=3.0)), [])

    def test_sweeps_orca_builds_otherwise_are_left_out(self):
        parallel = load_capture("sweep_pipe")
        sweep_data(parallel)["orientation"] = "parallel"
        holed = sw.bar_along_bend()
        sweep_data(holed)["profiles"][0]["loops"].append({"outer": False, "curves": sw.circle(1.0)})
        cases = (("twist", load_capture("sweep_closed_twist"), causes.SWEEP_SHAPE),
                 ("one direction along a bend", parallel, causes.SWEEP_SHAPE),
                 ("sharp corner", load_capture("sweep_sharp_corner"), gap_hints.SHARP_CORNER),
                 ("sharp corners of a closed path", load_capture("sweep_closed_outline"), gap_hints.SHARP_CORNER),
                 ("holes along a bend", holed, causes.OUTLINE_HOLES),
                 ("tilted outline", load_capture("sweep_tilted_outline"), gap_hints.REFUSED),
                 ("path in 3D", load_capture("sweep_bend_3d"), gap_hints.REFUSED))
        for name, capture, cause in cases:
            with self.subTest(name):
                self.assertEqual(left_causes(capture), [cause])


class LoftTest(unittest.TestCase):
    def test_two_squares_are_a_ruled_orca_loft_of_two_sketches(self):
        result = run(load_capture("loft_two_squares"))
        self.assertEqual(result.left_out, [])
        first, second, made = result.recipe.features
        self.assertEqual((first.shape, second.shape), (SketchShape.RECTANGLE, SketchShape.RECTANGLE))
        self.assertEqual((made.type, made.loft_profile_refs, made.loft_ruled, made.mode),
                         (FeatureType.LOFT, [0, 1], True, BooleanMode.NEW))
        joined = run(load_capture("loft_on_plate"))
        self.assertEqual((joined.left_out, joined.recipe.features[-1].mode), ([], BooleanMode.ADD))

    def test_two_circles_follow_their_sizes_and_share_one_normal(self):
        capture = sw.cone()
        top = capture["items"][2]["data"]["profiles"][1]["frame"]
        top["y"], top["z"] = [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]  # the top sketch faces down
        result = run(capture)
        low, high, _ = result.recipe.features
        self.assertEqual(high.expr, {"radius": "0.5 * top_d"})
        self.assertEqual(outcome(result, "top_d")["outcome"], VARIABLE)
        self.assertEqual(tuple(low.plane.normal), tuple(high.plane.normal))

    def test_turned_corners_copy_only_when_the_pairing_is_clear_or_measured(self):
        self.assertEqual(left_causes(sw.turned_squares(0.5)), [])
        turned = sw.turned_squares(20.0)
        self.assertEqual(left_causes(turned), [causes.LOFT_SHAPE])
        data = turned["items"][-1]["data"]
        data["volume_after"] = turned["target"]["volume_mm3"]
        self.assertEqual(left_causes(turned), [])
        data["volume_after"] = 7000.0  # the volume of corners joined straight across, not Orca's pairing
        self.assertEqual(left_causes(turned), [causes.LOFT_SHAPE])

    def test_lofts_orca_builds_otherwise_are_left_out(self):
        cases = (("point", "loft_point_end", gap_hints.LOFT_KIND), ("rails", "loft_rails", gap_hints.LOFT_KIND),
                 ("tangent end", "loft_tangent_end", gap_hints.LOFT_KIND),
                 ("three outlines", "loft_three_sections", gap_hints.LOFT_KIND),
                 ("holes", "loft_tube", causes.OUTLINE_HOLES),
                 ("circle to square", "loft_circle_to_square", causes.LOFT_SHAPE),
                 ("crossing planes", "loft_crossing_sections", causes.LOFT_SHAPE))
        for name, fixture, cause in cases:
            with self.subTest(name):
                self.assertEqual(left_causes(load_capture(fixture)), [cause])

    def test_a_line_through_a_square_frustum_meets_its_walls_at_that_height(self):
        rings = [[[-10, -10, 0], [10, -10, 0], [10, 10, 0], [-10, 10, 0]],
                 [[-5, -5, 30], [5, -5, 30], [5, 5, 30], [-5, 5, 30]]]
        frame = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}
        (span,) = Lofted(frame, 30.0, rings=rings).span([-20.0, 0.0, 15.0], [1.0, 0.0, 0.0])
        self.assertAlmostEqual(span[0], 12.5, delta=1e-6)
        self.assertAlmostEqual(span[1], 27.5, delta=1e-6)

    def test_a_thin_slanted_loft_is_found_along_a_long_line_through_its_box(self):
        # A 0.1 mm thin section moved 37 mm sideways over 50 mm: a line at height 20 crosses it for 0.1 mm of its
        # 47 mm through the box, between two of 64 even samples.
        frame = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}
        slab = [[[-0.05, -10, 0], [0.05, -10, 0], [0.05, 10, 0], [-0.05, 10, 0]],
                [[36.95, -10, 50], [37.05, -10, 50], [37.05, 10, 50], [36.95, 10, 50]]]
        shapes = {"lines": Lofted(frame, 50.0, rings=slab),
                  "circles": Lofted(frame, 50.0, circles=[([0.0, 0.0, 0.0], 0.05), ([37.0, 0.0, 50.0], 0.05)])}
        for name, shape in shapes.items():
            with self.subTest(name):
                (span,) = shape.span([-10.0, 0.0, 20.0], [1.0, 0.0, 0.0])
                self.assertAlmostEqual(span[0], 24.75, delta=1e-6)
                self.assertAlmostEqual(span[1], 24.85, delta=1e-6)


class SplineTest(unittest.TestCase):
    def test_a_spline_outline_is_its_bezier_pieces_through_the_same_points(self):
        result = run(sw.arch())
        self.assertEqual(result.left_out, [])
        entities = result.recipe.features[0].entities
        self.assertEqual([e.type for e in entities], [EntityType.BSPLINE, EntityType.BSPLINE, EntityType.LINE])
        spec = sw.ARCH
        for u in (0.1, 0.25, 0.4, 0.55, 0.9):
            piece, t = (entities[0], u / 0.4) if u <= 0.4 else (entities[1], (u - 0.4) / 0.6)
            got = [sum(math.comb(3, k) * (1 - t) ** (3 - k) * t ** k * piece.ctrl[k][i] for k in range(4))
                   for i in range(2)]
            want = sw.nurbs_point(3, spec["knots"], spec["poles"], u)
            self.assertAlmostEqual(math.dist(got, want), 0.0, places=9)

    def test_a_quadratic_spline_is_pieces_of_three_poles(self):
        spec = {"degree": 2, "knots": [0, 0, 0, 0.3, 1, 1, 1], "poles": [(0, 0), (4, 6), (12, 8), (20, 0)]}
        pieces = splines.bezier_pieces(dict(spec, periodic=False))
        self.assertEqual([len(p) for p in pieces], [3, 3])
        self.assertIsNotNone(splines.entities(sw.spline_curve(spec)))

    def test_splines_orca_cannot_draw_exactly_stay_out(self):
        cases = (("weights that differ", dict(rational=True, weights=[1, 2, 1, 1, 1])),
                 ("closed", dict(periodic=True)),
                 ("degree five", dict(degree=5)),
                 ("a definition that misses the measured points", dict(knots=[0, 0, 0, 0, 0.5, 1, 1, 1, 1])))
        for name, nurbs in cases:
            with self.subTest(name):
                self.assertEqual(left_causes(sw.arch(**nurbs)), [gap_hints.REFUSED])
        self.assertEqual(left_causes(sw.arch(rational=True, weights=[2, 2, 2, 2, 2])), [])

    def test_a_spline_read_without_its_definition_stays_out(self):
        self.assertEqual(left_causes(copy.deepcopy(load_capture("extrude_spline"))), [gap_hints.REFUSED])


def _bezier_point(piece, t):
    n = len(piece.ctrl) - 1
    return [sum(math.comb(n, k) * (1 - t) ** (n - k) * t ** k * piece.ctrl[k][i] for k in range(n + 1))
            for i in range(2)]


class SplinePathTest(unittest.TestCase):
    def test_a_spline_in_the_path_is_written_exactly_from_the_outline(self):
        # Drawn from either end, the path sketch runs from the outline: the line, then the spline's Bezier pieces,
        # which pass through the spline itself (the path frame is the XY plane here).
        spec = sw.BEND_SPLINE
        for drawn_back in (False, True):
            with self.subTest(drawn_back=drawn_back):
                result = run(sw.pipe_along_spline(drawn_back=drawn_back))
                self.assertEqual(result.left_out, [])
                self.assertEqual(types(result), [FeatureType.SKETCH, FeatureType.SKETCH, FeatureType.SWEEP])
                path = result.recipe.features[1]
                self.assertEqual([e.type for e in path.entities],
                                 [EntityType.LINE, EntityType.BSPLINE, EntityType.BSPLINE])
                self.assertAlmostEqual(math.dist(path.entities[0].p0, (0.0, 0.0)), 0.0, places=9)
                for before, after in zip(path.entities, path.entities[1:]):
                    self.assertAlmostEqual(math.dist(before.p1, after.p0), 0.0, places=6)
                for u in (0.1, 0.3, 0.6, 0.9):
                    piece, t = (path.entities[1], u / 0.3) if u <= 0.3 else (path.entities[2], (u - 0.3) / 0.7)
                    want = sw.nurbs_point(3, spec["knots"], spec["poles"], u)
                    self.assertAlmostEqual(math.dist(_bezier_point(piece, t), want), 0.0, places=9)

    def test_the_shape_for_later_cuts_is_the_outline_carried_along_the_spline(self):
        capture = sw.pipe_along_spline()
        data = sweep_data(capture)
        profile = data["profiles"][0]
        found = planner.plan(sweep_splines.with_exact_splines(data["path"]), profile["frame"],
                             profile_points(profile), PathOptions(splines=spline_fit))
        loops = [loop["curves"] for loop in profile["loops"]]
        box = Solid([("add", carried(profile["frame"], loops, found))]).box()
        target = capture["target"]["box"]
        for got, want in zip(box["min"] + box["max"], target["min"] + target["max"]):
            self.assertAlmostEqual(got, want, delta=0.01)
        # A pin down through the spline meets the pipe; the same pin 3 mm off the spline, past its radius, does not.
        on, ahead = (sw.nurbs_point(3, sw.BEND_SPLINE["knots"], sw.BEND_SPLINE["poles"], u) for u in (0.5, 0.501))
        size = math.dist(on, ahead)
        across = (-(ahead[1] - on[1]) / size, (ahead[0] - on[0]) / size)
        for off, cut in ((0.0, True), (3.0, False)):
            with self.subTest(off=off):
                capture = sw.pipe_along_spline()
                at = [on[0] + off * across[0], on[1] + off * across[1], -5.0]
                pin = sw.extrude(4, "Pin", [sw.profile("Pin sketch", dict(sw.UP, origin=at),
                                                       sw.circle(0.5))], operation="cut",
                                 side_one={"kind": "distance", "distance": 10.0, "taper_deg": 0.0},
                                 end_offset=10.0, target_box_before=capture["target"]["box"])
                capture["items"] += [sw.sketch_item(3, "Pin sketch"), pin]
                self.assertEqual(left_causes(capture), [] if cut else [causes.MISSES_PART])

    def test_a_spline_sweep_cuts_or_joins_an_existing_body(self):
        for operation, mode in (("cut", BooleanMode.CUT), ("join", BooleanMode.ADD)):
            with self.subTest(operation):
                result = run(sw.block_and_spline_pipe(operation))
                self.assertEqual(result.left_out, [])
                self.assertEqual(result.recipe.features[-1].type, FeatureType.SWEEP)
                self.assertEqual(result.recipe.features[-1].mode, mode)

    def test_the_outline_follows_its_size_and_the_path_keeps_its_numbers(self):
        result = run(sw.sized_spline_pipe())
        wire, path = outcome(result, "wire"), outcome(result, "run")
        self.assertEqual((wire["outcome"], path["outcome"]), (VARIABLE, FIXED))
        self.assertTrue(path["reasons"])
        # The wire may grow close to twice the radius of the spline's tightest bend, never past it.
        bend = sweep_splines.tightest([sw.spline_curve(sw.BEND_SPLINE)])
        self.assertEqual(limit_of(wire).low, 0.01)
        self.assertLessEqual(limit_of(wire).high, 2.0 * bend)
        self.assertGreater(limit_of(wire).high, 0.9 * 2.0 * bend)

    def test_the_tightest_bend_is_read_along_the_exact_curve(self):
        # The parabola y = x * x as a quadratic Bezier: its tightest bend, at the vertex, has a radius of one half.
        parabola = {"kind": "other", "nurbs": {"degree": 2, "knots": [0, 0, 0, 1, 1, 1],
                                               "poles": [(-1.0, 1.0), (0.0, -1.0), (1.0, 1.0)], "rational": False,
                                               "weights": None, "periodic": False}}
        self.assertAlmostEqual(sweep_splines.tightest([parabola]), 0.5, places=6)

    def test_splines_in_the_path_orca_cannot_draw_exactly_stay_out(self):
        unread = sw.pipe_along_spline()
        del sweep_data(unread)["path"]["curves"][1]["flat"]["nurbs"]
        weighted = sw.pipe_along_spline()
        sweep_data(weighted)["path"]["curves"][1]["flat"]["nurbs"].update(rational=True, weights=[1, 2, 1, 1, 1])
        cornered = sw.pipe_along_spline()
        spline = sweep_data(cornered)["path"]["curves"][1]
        spline["flat"]["nurbs"]["poles"][1] = [28.0, 1.0]  # leaves the line at a slight angle, as its points do
        bent = sw.spline_curve(dict(sw.BEND_SPLINE, poles=spline["flat"]["nurbs"]["poles"]))
        spline.update(samples=[p + [0.0] for p in bent["samples"]], flat=bent)
        cases = (("no definition", unread, causes.SWEEP_PATH), ("weights that differ", weighted, causes.SWEEP_PATH),
                 ("a closed path", sw.ring_along_splines(), causes.SWEEP_PATH),
                 ("a corner where the spline meets the line", cornered, gap_hints.SHARP_CORNER))
        for name, capture, cause in cases:
            with self.subTest(name):
                self.assertEqual(left_causes(capture), [cause])


if __name__ == "__main__":
    unittest.main()
