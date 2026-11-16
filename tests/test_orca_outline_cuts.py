"""Outlines built from plane cuts (`orca_translate/outline_cuts.py`): the recipe read in Python (`orca_cuts.Section`)
gives, at other values of the variables, the outline Fusion draws there, in every cell of its edge lines; the limits
of the variables are told; and outlines the cuts cannot build keep their drawn numbers."""
import copy
import math
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.orca_cuts import (ANGLED, ELL, PLATE, PLATE_HEIGHT, TRAPEZOID, U, WINDOW, Section, Shape, cell_points,
                             heights, holed_capture, onto_plate_capture, outline_capture, projected_window_capture,
                             window_capture, window_pattern_capture)
from tests.orca_extents import UP
from tests.orca_outline import finish
from tests.translator_helpers import verdict_of
from scripts.orca_live_check import table_for

from lib.orca_recipe.enums import BooleanMode, FeatureType
from lib.orca_translate import (FIXED, PARTLY, VARIABLE, causes, halfplanes, limits, outline_cuts, sketches,
                                translate)


def run(capture):
    return translate(capture, table_for(capture))


def of_type(result, kind):
    return [f for f in result.recipe.features if f.type == kind]


def outcomes(result):
    return {p["name"]: p["outcome"] for p in result.parameters}


def told(result, name):
    """The limit told on the parameter's line (a `limits.Limit`), or None."""
    found = [w for p in result.parameters if p["name"] == name for w in p["follows"] if hasattr(w, "high")]
    return found[0] if found else None


class SectionCase(unittest.TestCase):
    def assert_section(self, result, expect, polygons, setting, frame=UP):
        """At `setting` (variable to number), the recipe's only body holds a point of the sketch plane exactly when
        `expect(point)` does, at a point of every cell of the edge lines of `polygons`."""
        section = Section(result.recipe, setting)
        self.assertEqual(len(section.bodies), 1)
        for x, y in cell_points(polygons[0], polygons[1:]):
            world = result.place.point([frame["origin"][i] + frame["x"][i] * x + frame["y"][i] * y
                                        + frame["z"][i] * 5.0 for i in range(3)])
            self.assertEqual(section.bodies[0](world), expect((x, y)), "%r at %r" % ((x, y), setting))

    def assert_outline(self, shape, settings, frame=UP, up="z"):
        capture = outline_capture(shape, frame=frame)
        capture["up_axis"] = up
        result = run(capture)
        for setting in [{}] + settings:
            polygon = shape.corners(dict(shape.values, **setting))
            self.assert_section(result, lambda q: halfplanes.in_polygon(polygon, q), [polygon], setting, frame)
        return result

    def assert_solid(self, result, expect, polygons, setting, levels):
        """As `assert_section`, at each height of `levels` above the sketch plane: `expect(point, height)`."""
        section = Section(result.recipe, setting)
        self.assertEqual(len(section.bodies), 1)
        for z in levels:
            for x, y in cell_points(polygons[0], polygons[1:]):
                self.assertEqual(section.bodies[0](result.place.point((x, y, z))), expect((x, y), z),
                                 "%r at height %r, %r" % ((x, y), z, setting))


class FixedSidesTest(SectionCase):
    def test_an_ell_follows_its_legs_and_wall(self):
        result = self.assert_outline(ELL, [{"leg_a": 55.0}, {"wall": 5.0}, {"leg_b": 12.0, "wall": 11.0}])
        self.assertEqual(of_type(result, FeatureType.TRANSFORM), [])
        self.assertEqual(set(outcomes(result).values()), {VARIABLE})
        # The drawn sketch is not written: the outline is a block cut by planes.
        self.assertTrue(all(not f.entities for f in of_type(result, FeatureType.SKETCH)))

    def test_a_u_needs_tools_inside_tools(self):
        record, corners = U.sketch()
        self.assertGreater(halfplanes.depth(halfplanes.formula(corners)), 1)
        self.assert_outline(U, [{"wall": 12.0}, {"base": 3.0, "width": 70.0}, {"high": 9.0}])


class TurningSidesTest(SectionCase):
    def test_a_trapezoid_turns_its_sides_with_the_angle(self):
        result = self.assert_outline(TRAPEZOID, [{"ang": 50.0}, {"ang": 90.0}, {"ang": 120.0, "high": 12.0}])
        turns = of_type(result, FeatureType.TRANSFORM)
        self.assertEqual(len(turns), 4)  # one pair for each side, as they turn opposite ways
        self.assertTrue(all("ang" in f.expr["xf_angle_deg"] for f in turns))

    def test_an_angled_ell_whose_inner_sides_are_tied_by_distances_only(self):
        self.assert_outline(ANGLED, [{"ang": 90.0}, {"ang": 150.0, "wall": 4.0}, {"leg_b": 50.0, "leg_a": 20.0}])

    def test_sizes_that_rest_on_a_distance_keeping_two_lines_parallel_follow_only_partly(self):
        # Hand test OR18 has not shown yet that Fusion keeps such lines parallel.
        found = {p["name"]: p for p in run(outline_capture(ANGLED)).parameters}
        unconfirmed = sketches.UNCONFIRMED % "Sketch1"
        self.assertEqual({n for n, p in found.items() if unconfirmed in p["reasons"]}, {"leg_b", "wall", "ang"})
        self.assertEqual((found["leg_a"]["outcome"], found["ang"]["outcome"]), (VARIABLE, PARTLY))
        with mock.patch.object(sketches, "DISTANCE_KEEPS_PARALLEL", True):
            self.assertEqual(set(outcomes(run(outline_capture(ANGLED))).values()), {VARIABLE})

    def test_sides_turn_the_right_way_on_a_sketch_plane_that_faces_another_way(self):
        side_plane = {"origin": [5.0, -3.0, 2.0], "x": [0.0, 1.0, 0.0], "y": [0.0, 0.0, 1.0], "z": [1.0, 0.0, 0.0]}
        self.assert_outline(ANGLED, [{"ang": 90.0}, {"ang": 150.0, "wall": 4.0}], side_plane)


class FramesTest(SectionCase):
    """Sketch planes that face other ways, and a design whose up axis is Y."""

    OBLIQUE = {"origin": [3.0, 1.0, -2.0], "x": [math.cos(0.3), 0.0, math.sin(0.3)], "y": [0.0, 1.0, 0.0],
               "z": [-math.sin(0.3), 0.0, math.cos(0.3)]}
    # The sketch normal against x cross y, as a sketch seen from behind.
    REVERSED = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, -1.0]}
    UPRIGHT = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 0.0, -1.0], "z": [0.0, 1.0, 0.0]}

    def test_turning_sides_on_oblique_reversed_and_upright_planes_with_z_or_y_up(self):
        for name in ("OBLIQUE", "REVERSED", "UPRIGHT"):
            for up in ("z", "y"):
                with self.subTest(frame=name, up=up):
                    frame = getattr(self, name)
                    self.assert_outline(ANGLED, [{"ang": 90.0}, {"ang": 150.0, "wall": 4.0}], frame, up)
                    self.assert_outline(TRAPEZOID, [{"ang": 50.0}, {"ang": 120.0, "high": 12.0}], frame, up)


class ExtentTest(SectionCase):
    """The block the cuts start from is extruded as the Fusion extrude is, and its lengths follow."""

    def test_flipped_symmetric_and_two_sided_extents(self):
        for extent in ("flip", "symmetric", "two"):
            with self.subTest(extent=extent):
                result = run(outline_capture(ELL, extent=extent))
                for setting in ({}, {"leg_a": 55.0, "t": 14.0}):
                    polygon = ELL.corners(dict(ELL.values, **setting))
                    low, high = heights(extent, setting.get("t", ELL.values["t"]))
                    levels = (low - 1.0, low + 0.1, (low + high) / 2.0, high - 0.1, high + 1.0)
                    self.assert_solid(result, lambda q, z, p=polygon, lo=low, hi=high: lo < z < hi and
                                      halfplanes.in_polygon(p, q), [polygon], setting, levels)

    def test_a_join_and_an_intersect_with_the_part(self):
        top = ELL.values["t"]
        levels = (-1.0, PLATE_HEIGHT / 2.0, (PLATE_HEIGHT + top) / 2.0, top + 1.0)
        for operation in ("join", "intersect"):
            with self.subTest(operation=operation):
                result = run(onto_plate_capture(ELL, operation))
                self.assertEqual(result.left_out, [])
                for setting in ({}, {"wall": 12.0, "leg_b": 20.0}):
                    polygon = ELL.corners(dict(ELL.values, **setting))

                    def expect(q, z, p=polygon):
                        in_plate = halfplanes.in_polygon(PLATE, q) and 0.0 < z < PLATE_HEIGHT
                        in_ell = halfplanes.in_polygon(p, q) and 0.0 < z < top
                        return (in_plate or in_ell) if operation == "join" else (in_plate and in_ell)
                    self.assert_solid(result, expect, [polygon, PLATE], setting, levels)


class IntoThePartTest(SectionCase):
    def test_a_window_whose_corner_moves_is_cut_from_the_plate(self):
        capture = window_capture()
        result = run(capture)
        (boolean,) = [f for f in of_type(result, FeatureType.BOOLEAN) if f.bool_tool_body != -1 and
                      f.name.endswith("into the part")]
        self.assertEqual(boolean.mode, BooleanMode.CUT)
        for setting in ({}, {"wx": 30.0, "wy": 2.0}, {"wide": 8.0, "tall": 30.0}):
            window = WINDOW.corners(dict(WINDOW.values, **setting))
            self.assert_section(result, lambda q, w=window: halfplanes.in_polygon(PLATE, q)
                                and not halfplanes.in_polygon(w, q), [window, PLATE], setting)

    def test_a_pattern_writes_the_built_window_again_as_its_tool(self):
        result = run(window_pattern_capture())
        self.assertEqual(verdict_of(result, 4)["verdict"], "copied")
        self.assertEqual(len(of_type(result, FeatureType.CUT)), 8)  # the window's four cuts, then the tool's
        moved = Shape(dict(WINDOW.values, wx=5.0), WINDOW.draw)
        for setting in ({}, {"wide": 12.0}):
            first = moved.corners(dict(moved.values, **setting))
            second = [(x + 30.0, y) for x, y in first]
            self.assert_section(result, lambda q: halfplanes.in_polygon(PLATE, q) and not (
                halfplanes.in_polygon(first, q) or halfplanes.in_polygon(second, q)), [first, second, PLATE],
                setting)


class LimitTest(unittest.TestCase):
    def test_the_limits_where_the_cuts_stop_giving_the_outline_are_told(self):
        ell = run(outline_capture(ELL))
        self.assertAlmostEqual(told(ell, "wall").high, 29.9)  # the wall reaches the 30 mm leg
        self.assertAlmostEqual(told(ell, "leg_a").low, 8.01)  # the leg shrinks to the wall
        trapezoid = run(outline_capture(TRAPEZOID))
        self.assertAlmostEqual(told(trapezoid, "ang").low, 45.1)  # the top shrinks to nothing at 45 degrees
        self.assertAlmostEqual(told(trapezoid, "high").high, 54.9)

    def test_a_place_that_may_go_below_zero_is_told_how_far(self):
        window = run(window_capture())
        # The window may move off the plate to the left, up to where it leaves the block the cuts start from.
        self.assertLess(told(window, "wx").low, -900.0)
        self.assertIsNone(told(window, "wide").low)  # a size reaches zero, which needs no limit

    def test_a_band_where_the_check_fails_is_not_stepped_over(self):
        # The walk from 50 steps down by 12.5, 25 and 50, past the band; the even tests between the ends find it.
        low, high = limits.bounds(lambda x: not 2.0 < x < 5.0 and x < 900.0, 50.0)
        self.assertAlmostEqual(low, 5.0, places=5)
        self.assertAlmostEqual(high, 900.0, places=5)

    def test_past_a_told_limit_the_cuts_no_longer_give_the_outline(self):
        result = run(outline_capture(ELL))
        section = Section(result.recipe, {"wall": 35.0})
        polygon = ELL.corners(dict(ELL.values, wall=35.0))
        found = [section.bodies[0](result.place.point((x, y, 5.0))) == halfplanes.in_polygon(polygon, (x, y))
                 for x, y in cell_points(polygon)]
        self.assertFalse(all(found))


class DrawnOutlineTest(unittest.TestCase):
    """Outlines the cuts do not build keep their drawn numbers, and the sizes they read say why."""

    def assert_drawn(self, result):
        self.assertEqual(of_type(result, FeatureType.CUT), [])
        self.assertTrue(of_type(result, FeatureType.SKETCH)[0].entities)

    def test_a_tapered_extrude_keeps_its_drawn_outline(self):
        result = run(outline_capture(TRAPEZOID, taper=-2.0))
        self.assert_drawn(result)
        self.assertEqual(outcomes(result)["ang"], FIXED)

    def test_an_outline_that_would_take_too_many_features_keeps_its_numbers(self):
        with mock.patch.object(outline_cuts, "MAX_FEATURES", 5):
            result = run(outline_capture(ELL))
        self.assert_drawn(result)
        self.assertEqual(outcomes(result)["wall"], FIXED)

    def test_tool_bodies_nested_too_deep_keep_the_numbers(self):
        with mock.patch.object(outline_cuts, "MAX_DEPTH", 0):
            result = run(outline_capture(ELL))
        self.assert_drawn(result)
        self.assertEqual(outcomes(result)["wall"], FIXED)

    def test_an_outline_whose_limits_cannot_be_found_keeps_its_numbers(self):
        calls = []

        def fits_only_once(planned, env):
            calls.append(env)
            return len(calls) == 1  # the check at the current sizes, then never again

        with mock.patch.object(outline_cuts.Planned, "fits", fits_only_once):
            result = run(outline_capture(ELL))
        self.assert_drawn(result)
        self.assertEqual(outcomes(result)["leg_a"], FIXED)

    def test_corner_formulas_that_do_not_give_the_drawn_corners_keep_the_numbers(self):
        capture = outline_capture(ELL)
        capture["sketch_graphs"] = [ELL.sketch({"leg_a": 41.0})[0]]
        result = run(capture)
        self.assert_drawn(result)
        self.assertEqual(outcomes(result)["leg_b"], FIXED)

    def test_corners_placed_by_projected_geometry_keep_the_numbers_and_mark_the_sizes_before(self):
        result = run(projected_window_capture())
        self.assertEqual(of_type(result, FeatureType.CUT), [])
        # The plate's height is read before the window, and may move the projected corner.
        self.assertEqual(outcomes(result)["thick"], PARTLY)


class SameSketchTest(unittest.TestCase):
    """A size the cut-built outline follows can also move another outline of its sketch that is drawn with numbers."""

    def test_a_hole_of_lines_placed_from_a_corner_the_cuts_follow_marks_that_size(self):
        result = run(holed_capture())
        self.assertTrue(of_type(result, FeatureType.CUT))  # the L is built from cuts
        found = outcomes(result)
        # The hole is drawn with numbers and stays put in Orca while leg_a moves it in Fusion.
        self.assertEqual(found["leg_a"], PARTLY)
        self.assertEqual((found["leg_b"], found["wall"]), (VARIABLE, VARIABLE))

    def test_two_corners_on_one_spot_keep_the_drawn_outline(self):
        capture = outline_capture(ELL)
        curves = capture["items"][1]["data"]["profiles"][0]["loops"][0]["curves"]
        curves.insert(1, {"kind": "line", "start": [40.0, 0.0], "end": [40.0, 0.0]})
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual(of_type(result, FeatureType.CUT), [])
        self.assertEqual(outcomes(result)["wall"], FIXED)


class RoundTest(unittest.TestCase):
    def test_a_round_of_a_side_edge_is_cut_from_the_outline_which_keeps_following(self):
        capture = outline_capture(ELL)
        capture["items"].append(finish(2, "Fillet1", [([(8.0, 8.0, 5.0)], 2.0)]))
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual(outcomes(result)["wall"], VARIABLE)
        self.assertEqual(len(of_type(result, FeatureType.HOLE)), 1)

    def test_a_round_of_all_top_edges_is_orcas_top_group(self):
        capture = outline_capture(ELL)
        record, corners = ELL.sketch()
        middles = [((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, 10.0) for a, b in zip(corners, corners[1:] + corners[:1])]
        capture["items"].append(finish(2, "Fillet1", [(middles, 1.0)]))
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual(len(of_type(result, FeatureType.FILLET)), 1)
        self.assertTrue(of_type(result, FeatureType.CUT))  # the outline is still built from cuts


class HalfPlaneTest(unittest.TestCase):
    def test_the_formula_of_an_ell_is_its_convex_sides_less_the_inward_corner(self):
        corners = ELL.corners()
        node = halfplanes.formula(corners)
        self.assertEqual(node, ("and", [("lit", 0), ("lit", 1), ("or", [("lit", 2), ("lit", 3)]), ("lit", 4),
                                        ("lit", 5)]))
        self.assertTrue(halfplanes.check(corners, node))

    def test_the_check_finds_a_formula_that_gives_another_shape(self):
        corners = ELL.corners()
        convex = ("and", [("lit", k) for k in range(6)])
        self.assertFalse(halfplanes.check(corners, convex))

    def test_a_loop_whose_sides_cross_is_not_simple(self):
        self.assertFalse(halfplanes.simple([(0, 0), (10, 0), (0, 10), (10, 10)]))
        self.assertTrue(halfplanes.simple(PLATE))


if __name__ == "__main__":
    unittest.main()
