"""Thin extrudes in the Orca copy (`orca_translate/thin.py`): the recipe read in Python (`orca_cuts.Section`) holds the
wall Fusion builds at other values of the variables; walls whose side or shape cannot be told are left out with
their causes."""
import importlib.util
import math
import os
import unittest

from tests import context  # noqa: F401
from tests import orca_thin
from tests.orca_cuts import Section, cell_points
from tests.orca_extents import UP, profile, rect
from tests.derived_fixtures import dimension
from tests.sketch_solve_helpers import L, P, Sketch, rectangle
from scripts.orca_live_check import table_for

from lib.capture_model import gap_hints
from lib.design_model.steps import thin as facts
from lib.orca_recipe.enums import BooleanMode, FeatureType
from lib.orca_translate import VARIABLE, causes, halfplanes, translate
from lib.orca_translate.formulas import orca_value, variable_values


GEOMETRY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "fixture_geometry.py")


def run(capture):
    return translate(capture, table_for(capture))


def outcomes(result):
    return {p["name"]: p["outcome"] for p in result.parameters}


def causes_of(result):
    return [g["cause"] for g in result.left_out]


def thin_item(capture):
    return capture["items"][-1]["data"]


def box(w, d, grow=0.0):
    hw, hd = w / 2 + grow, d / 2 + grow
    return [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]


class WallCase(unittest.TestCase):
    def assert_holds(self, result, expect, polygons, setting, z):
        """At `setting`, the only body holds a point at height `z` exactly when `expect((x, y))` does, at a point of
        every cell of the edge lines of `polygons`."""
        section = Section(result.recipe, setting)
        self.assertEqual(len(section.bodies), 1)
        for x, y in cell_points(polygons[0], polygons[1:]):
            world = result.place.point([x, y, z])
            self.assertEqual(section.bodies[0](world), expect((x, y)), "%r at %r" % ((x, y), setting))


class LiveCheckCaptureTest(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("numpy"), "scripts/fixture_geometry.py needs numpy")
    def test_the_worked_out_volumes_match_the_grid_of_the_fixture_script(self):
        spec = importlib.util.spec_from_file_location("fixture_geometry", GEOMETRY)
        geometry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(geometry)
        # The script rounds the outer corners of a closed wall as the app does, so the frame is not compared.
        for build, tolerance in ((orca_thin.divider, 0.05), (orca_thin.ell, 0.05), (orca_thin.ring_wall, 12.0)):
            capture = build()
            box, volume, _ = geometry.evaluate(capture)
            self.assertEqual(capture["target"]["box"], box)
            self.assertAlmostEqual(capture["target"]["volume_mm3"], volume, delta=tolerance)


class ClosedWallTest(WallCase):
    def assert_frame(self, result, inner_grow, outer_grow, settings):
        for setting in settings:
            v = dict({"width": 80.0, "depth": 50.0, "wall": 2.0}, **setting)
            outer = box(v["width"], v["depth"], outer_grow * v["wall"])
            inner = box(v["width"], v["depth"], inner_grow * v["wall"])
            self.assert_holds(result, lambda q: halfplanes.in_polygon(outer, q) and not halfplanes.in_polygon(
                inner, q), [outer, inner], setting, 10.0)

    def test_a_wall_outside_a_rectangle_follows_its_sizes_and_thickness(self):
        result = run(orca_thin.frame_wall())
        self.assertEqual(result.left_out, [])
        self.assert_frame(result, 0.0, 1.0, [{}, {"wall": 3.0}, {"width": 100.0, "depth": 30.0}])
        self.assertEqual(set(outcomes(result).values()), {VARIABLE})

    def test_a_wall_inside_or_centred_on_a_rectangle_takes_the_side_the_end_face_shows(self):
        w, d, t = 80.0, 50.0, 2.0
        for location, area, inner, outer in (
                ("side1", w * d - (w - 2 * t) * (d - 2 * t), -1.0, 0.0),
                ("center", (w + t) * (d + t) - (w - t) * (d - t), -0.5, 0.5)):
            with self.subTest(location):
                result = run(orca_thin.frame_wall(location=location, end_area=area))
                self.assertEqual(result.left_out, [])
                self.assert_frame(result, inner, outer, [{}, {"wall": 3.0}])

    def test_a_wall_with_rounded_outer_corners_is_left_out(self):
        w, d, t = 80.0, 50.0, 2.0
        rounded = 2 * (w + d) * t + math.pi * t * t
        result = run(orca_thin.frame_wall(end_area=rounded))
        self.assertEqual(causes_of(result), [gap_hints.REFUSED])
        self.assertEqual(result.recipe.features, [])

    def test_a_rectangle_that_fusion_moves_as_it_grows_keeps_its_numbers(self):
        capture = orca_thin.frame_wall()
        s = Sketch()
        corners = [0, s.point(80.0, 0.0), s.point(80.0, 50.0), s.point(0.0, 50.0)]
        lines = rectangle(s, corners)
        dimension(s, "linear", [L(lines[0])], 80.0, "d_width", "width", "horizontal")
        dimension(s, "linear", [L(lines[1])], 50.0, "d_depth", "depth", "vertical")
        capture["sketch_graphs"] = [orca_thin.graph_of(s)]
        thin_item(capture)["profiles"] = [profile("Sketch1", UP, rect(0, 0, 80, 50))]
        result = run(capture)
        self.assertEqual(result.left_out, [])
        sketches = [f for f in result.recipe.features if f.type == FeatureType.SKETCH]
        self.assertEqual([sorted(f.expr) for f in sketches], [["height", "width"], []])
        self.assertNotEqual(outcomes(result)["width"], VARIABLE)
        self.assertEqual(outcomes(result)["wall"], VARIABLE)

    def test_a_wall_inside_a_circle_follows_its_diameter_and_thickness(self):
        result = run(orca_thin.ring_wall())
        self.assertEqual(result.left_out, [])
        outer, inner = [f for f in result.recipe.features if f.type == FeatureType.SKETCH]
        for setting, radii in (({}, (20.0, 18.0)), ({"wall": 3.0}, (20.0, 17.0)), ({"dia": 60.0}, (30.0, 28.0))):
            values = variable_values(dict(result.recipe.variables, **{k: repr(v) for k, v in setting.items()}))
            self.assertEqual(tuple(orca_value(f.expr["radius"], values) for f in (outer, inner)), radii)

    def test_on_a_part_the_wall_is_a_tool_body_that_joins_cuts_or_intersects_it(self):
        plate = box(120.0, 100.0)
        for operation, mode, keep in (
                ("join", BooleanMode.ADD, lambda wall, on: on or wall),
                ("cut", BooleanMode.CUT, lambda wall, on: on and not wall),
                ("intersect", BooleanMode.INTERSECT, lambda wall, on: on and wall)):
            with self.subTest(operation):
                result = run(orca_thin.onto_plate(orca_thin.frame_wall, operation))
                self.assertEqual(result.left_out, [])
                (boolean,) = [f for f in result.recipe.features if f.type == FeatureType.BOOLEAN]
                self.assertEqual(boolean.mode, mode)
                outer, inner = box(86.0, 56.0), box(80.0, 50.0)

                def expect(q):
                    wall = halfplanes.in_polygon(outer, q) and not halfplanes.in_polygon(inner, q)
                    return keep(wall, halfplanes.in_polygon(plate, q))
                self.assert_holds(result, expect, [plate, outer, inner], {"wall": 3.0}, 1.0)

    def test_a_cut_that_misses_the_part_is_left_out(self):
        capture = orca_thin.onto_plate(orca_thin.ring_wall, "cut")
        thin_item(capture)["profiles"][0]["frame"] = dict(UP, origin=[500.0, 0.0, 0.0])
        self.assertEqual(causes_of(run(capture)), [causes.MISSES_PART])

    def test_outlines_the_wall_cannot_be_built_from_are_left_out(self):
        ell = [(0, 0), (30, 0), (30, 5), (5, 5), (5, 20), (0, 20)]
        ell_curves = [{"kind": "line", "start": list(a), "end": list(b)} for a, b in zip(ell, ell[1:] + ell[:1])]
        cases = {
            "other shape": (lambda d: d["profiles"].__setitem__(0, profile("Sketch1", UP, ell_curves)),
                            causes.THIN_SHAPE),
            "hole": (lambda d: d["profiles"][0]["loops"].append({"outer": False, "curves": rect(-5, -5, 5, 5)}),
                     gap_hints.THIN_OUTLINE),
            "several": (lambda d: d["profiles"].append(profile("Sketch1", UP, rect(50, 50, 60, 60))),
                        gap_hints.THIN_OUTLINE),
            "two ways": (lambda d: d.update(extent_type="two"), gap_hints.REFUSED),
        }
        for name, (edit, cause) in cases.items():
            with self.subTest(name):
                capture = orca_thin.frame_wall()
                edit(thin_item(capture))
                self.assertEqual(causes_of(run(capture)), [cause])


class LineWallTest(WallCase):
    def test_a_divider_centred_on_one_line_follows_its_length_and_thickness(self):
        result = run(orca_thin.divider())
        self.assertEqual(result.left_out, [])
        plate = box(40.0, 40.0)
        for setting in ({}, {"len": 36.0, "wall": 3.0}):
            v = dict({"len": 30.0, "wall": 1.6}, **setting)
            wall = box(v["len"], v["wall"])
            self.assert_holds(result, lambda q: halfplanes.in_polygon(wall, q), [plate, wall], setting, 10.0)
            self.assert_holds(result, lambda q: halfplanes.in_polygon(plate, q), [plate, wall], setting, 1.0)
        self.assertEqual(set(outcomes(result).values()), {VARIABLE})

    def test_a_centred_line_that_fusion_moves_as_it_grows_keeps_its_length(self):
        capture = orca_thin.divider()
        s = Sketch()
        end = s.point(30.0, 0.0)
        line = s.line(0, end)
        s.con("horizontal", L(line))
        dimension(s, "linear", [P(0), P(end)], 30.0, "d_len", "len", "horizontal")
        graph = orca_thin.graph_of(s)
        graph.update(sketch="Sketch2", token="s2")
        capture["sketch_graphs"] = [graph]
        data = thin_item(capture)
        data["path"] = orca_thin.path_record([(0.0, 0.0), (30.0, 0.0)])
        data["wall_faces"] = orca_thin.wall_faces(facts.band([[0, 0], [30, 0]], 0.8, 0.8), 0.0, 22.0, bottom=False)
        result = run(capture)
        self.assertEqual(result.left_out, [])
        (sketch,) = [f for f in result.recipe.features if f.name == "Divider sketch"]
        self.assertEqual(sorted(sketch.expr), ["height"])
        self.assertNotEqual(outcomes(result)["len"], VARIABLE)

    def test_a_line_of_several_lines_is_drawn_as_its_wall_with_numbers(self):
        result = run(orca_thin.ell())
        self.assertEqual(result.left_out, [])
        band = facts.band([list(p) for p in orca_thin.ELL_POINTS], 2.0, 0.0)
        self.assert_holds(result, lambda q: halfplanes.in_polygon(band, q), [band], {}, 10.0)
        self.assertNotEqual(outcomes(result)["wall_mm"], VARIABLE)

    def test_a_wall_whose_faces_do_not_show_its_side_is_left_out(self):
        capture = orca_thin.ell()
        thin_item(capture)["thin_wall"]["location"] = "side2"
        self.assertEqual(causes_of(run(capture)), [gap_hints.THIN_OUTLINE])


if __name__ == "__main__":
    unittest.main()
