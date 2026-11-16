"""Rounds and chamfers of side edges on outlines whose sizes follow variables, cut as corner tools in the Orca copy.
No Fusion and no Orca: the written recipe is read in Python (`orca_cuts.Section`) at several values of the variables
and compared with the outline whose corners are worked out from the shapes of `tests/orca_corners.py`."""
import copy
import math
import unittest
from types import SimpleNamespace
from unittest import mock

from tests import context  # noqa: F401
from tests import orca_corners as corners
from tests import orca_outline as shapes
from tests.orca_cuts import ELL, TRAPEZOID, WINDOW, Section, Shape

from lib.design_model.design import as_read
from lib.orca_recipe.enums import BooleanMode, FaceGroup, FeatureType
from lib.orca_translate import VARIABLE, causes, corner_hosts, corner_tools, finishes, steps, translate
from lib.orca_translate.context import Context
from lib.orca_translate.place import Placement
from lib.orca_translate.skip import Skip
from scripts.orca_live_check import table_for


def run(capture):
    return translate(capture, table_for(capture))


def left_out(result):
    return [(g["name"], g["cause"]) for g in result.left_out]


def of_type(result, kind):
    return [f for f in result.recipe.features if f.type == kind]


def _probes(points, reach, box):
    """Points near every corner of the outline (a fine grid over each corner's tools) and over its box, off the
    lines of the outline."""
    out = []
    for x, y in points:
        for i in range(13):
            for j in range(13):
                out.append((x + reach * (-1.5 + 3.0 * (i + 0.37) / 13), y + reach * (-1.5 + 3.0 * (j + 0.41) / 13)))
    (x0, y0), (x1, y1) = box
    for i in range(31):
        for j in range(31):
            out.append((x0 + (x1 - x0) * (i + 0.37) / 31, y0 + (y1 - y0) * (j + 0.41) / 31))
    return out


def mismatches(result, shape, steps_of, changed, height, inside, box, body=0, reach=4.0):
    """How many probe points the recipe at `changed` puts on the wrong side of the outline with its corners."""
    values = dict(shape.values, **changed)
    points = shape.corners(values)
    rounds = corners.rounds_of(steps_of, values)
    section = Section(result.recipe, changed)
    return sum(section.bodies[body](result.place.point((u, v, height))) != inside(points, rounds, (u, v))
               for u, v in _probes(points, reach, box))


def plain(points, rounds, x):
    return corners.rounded_inside(points, rounds, x)


def through_plate(points, rounds, x):
    return 0 < x[0] < 60 and 0 < x[1] < 40 and not corners.rounded_inside(points, rounds, x)


class CopiedTest(unittest.TestCase):
    def assert_follows(self, capture, shape, steps_of, changes, height, inside, box, **kwargs):
        result = run(capture)
        self.assertEqual(left_out(result), [])
        for changed in changes:
            with self.subTest(changed=changed):
                self.assertEqual(mismatches(result, shape, steps_of, changed, height, inside, box, **kwargs), 0)
        return result

    def test_rounds_and_a_chamfer_of_an_outline_built_from_cuts(self):
        # An inward and an outer round, then a chamfer: the outline stays built from cuts and every size follows.
        result = self.assert_follows(corners.rounded_outline(ELL, corners.ELL_STEPS), ELL, corners.ELL_STEPS,
                                     [{}, {"leg_a": 50.0}, {"wall": 12.0}, {"leg_b": 20.0, "wall": 5.0}], 5.0, plain,
                                     ((-1, -1), (52, 32)))
        self.assertEqual({p["outcome"] for p in result.parameters}, {VARIABLE})
        self.assertEqual(of_type(result, FeatureType.SKETCH)[0].entities, [])

    def test_a_round_whose_size_follows_a_parameter_at_a_side_that_turns(self):
        steps_of = corners.TRAPEZOID_STEPS
        result = self.assert_follows(corners.rounded_outline(TRAPEZOID, steps_of), TRAPEZOID, steps_of,
                                     [{}, {"ang": 50.0}, {"ang": 110.0}, {"fr": 5.0}, {"high": 12.0, "base": 50.0}],
                                     5.0, plain, ((-15, -1), (55, 25)), reach=6.0)
        found = {p["name"]: p for p in result.parameters}
        self.assertEqual(found["fr"]["outcome"], VARIABLE)
        # The round may grow until it takes the whole side it shares with the chamfer, and an Orca Hole of no size
        # stops the rebuild, so it must stay above the smallest corner.
        (limit,) = [w for w in found["fr"]["follows"] if hasattr(w, "high")]
        self.assertTrue(10.0 < limit.high < 20.0)
        self.assertEqual(limit.low, corner_tools.SIZE_MIN)
        hole = of_type(result, FeatureType.HOLE)[0]
        self.assertIn("fr", hole.expr["hole_diameter"])

    def test_a_symmetric_extrude(self):
        self.assert_follows(corners.rounded_outline(ELL, corners.ELL_STEPS, "symmetric"), ELL, corners.ELL_STEPS,
                            [{}, {"wall": 12.0}], -2.0, plain, ((-1, -1), (52, 32)))

    def test_the_corners_of_a_window_cut_through_a_plate_fill_it(self):
        self.assert_follows(corners.rounded_window(corners.FOUR), WINDOW, corners.FOUR,
                            [{}, {"wx": 20.0}, {"wide": 30.0}, {"tall": 8.0}], 5.0, through_plate,
                            ((-1, -1), (61, 41)))

    def test_a_rectangle_that_follows_sizes_keeps_its_rectangle(self):
        capture = shapes.plate_sized_outline(4.0)
        result = run(capture)
        self.assertEqual(left_out(result), [])
        sketch = of_type(result, FeatureType.SKETCH)[0]
        self.assertEqual((set(sketch.expr), sketch.entities), ({"width", "height"}, []))
        self.assertEqual({p["name"]: p["outcome"] for p in result.parameters if p["name"] in (
            "cube_mm", "depth_mm", "height_mm")}, dict.fromkeys(("cube_mm", "depth_mm", "height_mm"), VARIABLE))
        for changed, width, depth in (({}, 80.0, 60.0), ({"cube_mm": 30.0}, 92.0, 60.0), ({"depth_mm": 20.0}, 80.0,
                                                                                            20.0)):
            with self.subTest(changed=changed):
                points = [(-width / 2, -depth / 2), (width / 2, -depth / 2), (width / 2, depth / 2),
                          (-width / 2, depth / 2)]
                section = Section(result.recipe, changed)
                rounds = {k: (4.0, False) for k in range(4)}
                wrong = sum(section.bodies[0](result.place.point((u, v, 16.0))) != plain(points, rounds, (u, v))
                            for u, v in _probes(points, 8.0, ((-50, -35), (50, 35))))
                self.assertEqual(wrong, 0)

    def test_a_rectangle_joined_to_a_plate_becomes_a_body_of_its_own(self):
        result = self.assert_follows(corners.rounded_block(corners.FOUR), corners.CENTRED, corners.FOUR,
                                     [{}, {"wide": 30.0}, {"deep": 10.0}], 8.0, plain, ((-1, -1), (61, 41)))
        extrudes = of_type(result, FeatureType.EXTRUDE)
        self.assertEqual(extrudes[1].mode, BooleanMode.NEW)
        self.assertEqual(result.recipe.features[-1].mode, BooleanMode.ADD)

    def test_a_rectangle_cut_from_a_plate_becomes_a_body_of_its_own(self):
        def pocket(points, rounds, x):
            return 0 < x[0] < 60 and 0 < x[1] < 40 and not plain(points, rounds, x)
        result = self.assert_follows(corners.rounded_block(corners.FOUR, "cut"), corners.CENTRED, corners.FOUR,
                                     [{}, {"wide": 30.0}, {"deep": 10.0}], 3.0, pocket, ((-1, -1), (61, 41)))
        extrudes = of_type(result, FeatureType.EXTRUDE)
        self.assertEqual(extrudes[1].mode, BooleanMode.NEW)
        self.assertEqual(result.recipe.features[-1].mode, BooleanMode.CUT)

    def test_a_second_round_of_the_same_rectangle_goes_before_it_joins_the_part(self):
        steps_of = [("Fillet1", False, [0, 1], 2.0, None), ("Fillet2", False, [2, 3], 3.0, None)]
        result = self.assert_follows(corners.rounded_block(steps_of), corners.CENTRED, steps_of,
                                     [{}, {"wide": 30.0}, {"deep": 10.0}], 8.0, plain, ((-1, -1), (61, 41)))
        (joined,) = [f for f in of_type(result, FeatureType.BOOLEAN) if f.mode == BooleanMode.ADD]
        self.assertIs(result.recipe.features[-1], joined)

    def test_a_pattern_repeats_the_corners_with_the_window(self):
        capture = corners.rounded_pattern(corners.FOUR)
        shape = Shape(dict(WINDOW.values, wx=5.0), WINDOW.draw)
        result = run(capture)
        self.assertEqual(left_out(result), [])

        def two(points, rounds, x):
            return through_plate(points, rounds, x) and not corners.rounded_inside(points, rounds, (x[0] - 30, x[1]))
        self.assertEqual(mismatches(result, shape, corners.FOUR, {}, 5.0, two, ((-1, -1), (61, 41))), 0)

    def test_a_pattern_repeats_corners_whose_sides_turn_with_an_angle(self):
        shape, steps_of = corners.PLACED_TRAPEZOID, [("Fillet1", False, [1], 3.0, "fr"), ("Chamfer1", True, [3], 2.0,
                                                                                         None)]
        result = run(corners.rounded_window_pattern(shape, steps_of))
        self.assertEqual(left_out(result), [])
        self.assertTrue(any(f.type == FeatureType.TRANSFORM and f.name.startswith("Pattern1: Window corner")
                            for f in result.recipe.features))
        for changed in ({}, {"ang": 55.0}, {"fr": 2.0}, {"base": 18.0}):
            values = dict(shape.values, **changed)
            points = shape.corners(values)
            rounds = corners.rounds_of(steps_of, values)
            copies = [[(x + shift, y) for x, y in points] for shift in (0.0, 25.0)]
            section = Section(result.recipe, changed)
            for moved in copies:
                with self.subTest(changed=changed, at=moved[0]):
                    wrong = sum(section.bodies[0](result.place.point((u, v, 5.0)))
                                != (0 < u < 60 and 0 < v < 40 and not any(plain(c, rounds, (u, v)) for c in copies))
                                for u, v in _probes(moved, 4.0, ((moved[0][0] - 2, 8), (moved[1][0] + 2, 22))))
                    self.assertEqual(wrong, 0)

    def test_a_pattern_of_the_window_without_its_round_is_left_out(self):
        # Orca's pattern writes its first copy over the original window, which would lose its rounded corners.
        capture = corners.rounded_pattern(corners.FOUR)
        capture["items"][-1]["data"]["sources"] = [3]
        self.assertEqual(left_out(run(capture)), [("Pattern1", causes.REPEATS_FINISH)])

    def test_a_round_of_the_top_edges_after_the_corners_is_orcas_top_group(self):
        result = run(shapes.sized_outline_then_top(4.0, 1.0))
        self.assertEqual(left_out(result), [])
        features = result.recipe.features
        (top_round,) = of_type(result, FeatureType.FILLET)
        self.assertEqual((top_round.face_group, top_round.dressup_size), (FaceGroup.TOP, 1.0))
        # Orca rounds the top edges of the part with its corners already cut: the round comes after every tool.
        self.assertEqual(len(of_type(result, FeatureType.HOLE)), 4)
        last_tool = max(n for n, f in enumerate(features) if f.type == FeatureType.BOOLEAN)
        self.assertGreater(features.index(top_round), last_tool)

    def test_a_later_top_round_limits_how_small_the_corners_may_get(self):
        # Orca cannot round the top edges along a corner arc of 1.1 times the top round or less, and stops the
        # rebuild: the corner size is told a lower limit above that.
        result = run(shapes.sized_outline_then_top(4.0, 2.0, sized="fr"))
        self.assertEqual(left_out(result), [])
        (fr,) = [p for p in result.parameters if p["name"] == "fr"]
        lows = [w.low for w in fr["follows"] if getattr(w, "low", None) is not None]
        self.assertTrue(2.2 < max(lows) < 4.0, lows)

    def test_a_step_with_a_rectangle_that_follows_sizes_and_a_drawn_outline_copies_both(self):
        from tests.orca_extents import UP, extrude, profile, rect, side, sketch_item
        capture = shapes.plate_sized_outline(4.0)
        top = dict(UP, origin=[0.0, 0.0, 32.0])
        capture["items"] = capture["items"][:2] + [
            sketch_item(2, "Sketch2"),
            extrude(3, "Block", [profile("Sketch2", top, rect(-10, -10, 10, 10))], operation="join",
                    side_one=side(10.0), end_offset=10.0, target_box_before={"min": [-40, -30, 0], "max": [40, 30, 32]}),
            shapes.finish(4, "Fillet1", [([(40, 30, 16), (10, 10, 37)], 2.0)])]
        result = run(capture)
        self.assertEqual(left_out(result), [])
        found = {f.name: f for f in of_type(result, FeatureType.SKETCH)}
        bound, drawn = found["Extrude1 sketch"], found["Block sketch"]
        self.assertEqual((set(bound.expr), bound.entities), ({"width", "height"}, []))
        self.assertEqual(len(drawn.entities), 5)
        self.assertEqual(len(of_type(result, FeatureType.HOLE)), 1)
        # The corner tool goes in before the block, and the block's extrude still reads its own sketch.
        features = result.recipe.features
        block = next(f for f in of_type(result, FeatureType.EXTRUDE) if f.name == "Block")
        self.assertIs(features[block.sketch_ref], drawn)
        self.assertLess(features.index(of_type(result, FeatureType.HOLE)[0]), block.sketch_ref)

    def test_a_pattern_of_a_combine_rounds_the_corners_of_every_copy(self):
        # The Combine writes the rounded tool body, and the pattern writes it again: each writing gets its own tools.
        result = run(corners.rounded_tool(corners.FOUR, copies=2))
        self.assertEqual(left_out(result), [])
        for changed in ({}, {"wide": 12.0}, {"deep": 6.0}):
            values = dict(corners.SMALL.values, **changed)
            points = corners.SMALL.corners(values)
            rounds = corners.rounds_of(corners.FOUR, values)
            section = Section(result.recipe, changed)
            copies = [[(x + shift, y) for x, y in points] for shift in (0.0, 15.0)]
            for moved in copies:
                with self.subTest(changed=changed, at=moved[0]):
                    wrong = sum(section.bodies[0](result.place.point((u, v, 8.0)))
                                != any(plain(c, rounds, (u, v)) for c in copies)
                                for u, v in _probes(moved, 3.0, ((moved[0][0] - 2, 12), (moved[2][0] + 2, 28))))
                    self.assertEqual(wrong, 0)


class LeftOutTest(unittest.TestCase):
    def test_a_round_too_big_for_its_side(self):
        steps_of = [("Fillet1", False, [1], 9.0, None)]
        self.assertEqual(left_out(run(corners.rounded_outline(ELL, steps_of))), [("Fillet1", causes.NO_ROOM)])

    def test_too_many_features(self):
        with mock.patch.object(corner_hosts, "MAX_FEATURES", 10):
            result = run(corners.rounded_outline(ELL, corners.ELL_STEPS))
        # The round's two tools take more features than allowed; the chamfer's one tool does not.
        self.assertEqual(left_out(result), [("Fillet1", causes.CORNER_TOOLS)])

    def test_a_later_top_round_when_the_corners_cannot_be_worked_out_again(self):
        # Without the corners at other sizes, the copy cannot tell which corner sizes the top round still fits.
        with mock.patch.object(corner_tools, "loop_at", return_value=None):
            result = run(shapes.sized_outline_then_top(4.0, 2.0, sized="fr"))
        self.assertEqual(left_out(result), [("Fillet2", causes.NO_ROOM)])

    def test_a_round_size_orca_cannot_write_keeps_its_number(self):
        capture = corners.rounded_outline(TRAPEZOID, corners.TRAPEZOID_STEPS)
        for record in [capture["items"][2]["data"]["params"]["sets.0.radius"]] + [
                m for m in capture["parameters"]["model"] if m["name"] == "r_fr"]:
            record["expression"] = "round(fr)"
        result = run(capture)
        self.assertEqual(left_out(result), [])
        hole = of_type(result, FeatureType.HOLE)[0]
        # The corner still follows the outline; its size stays 3, and fr gets the reason.
        self.assertEqual((hole.hole_diameter, "hole_diameter" in hole.expr, "hole_x" in hole.expr), (6.0, False, True))
        (fr,) = [p for p in result.parameters if p["name"] == "fr"]
        self.assertTrue(fr["reasons"])

    def test_a_round_on_an_outline_no_longer_in_the_copy(self):
        capture = corners.rounded_outline(ELL, corners.ELL_STEPS)
        ctx = Context(capture, table_for(capture), Placement(capture))
        ctx.written[1] = steps.extrude(ctx, as_read(capture["items"][1]))
        ctx.shapes[1] = list(ctx.solid.pieces)
        ctx.cut_built.clear()
        made = finishes.fillet(ctx, as_read(capture["items"][2]))
        self.assertEqual(made.cause, causes.CORNER_CHANGED)
        self.assertEqual(ctx.corner_hosts, {})

    def test_a_variable_without_a_parameter_line_leaves_the_round_out(self):
        # Orca builds another shape past a limit of the corners, so a limit that cannot be told stops the step.
        with mock.patch.object(corner_tools, "walk", return_value={"no_line": (1.0, 2.0)}):
            result = run(corners.rounded_outline(ELL, corners.ELL_STEPS[:1]))
        self.assertEqual(left_out(result), [("Fillet1", causes.CORNER_TOOLS)])

    def test_a_rectangle_left_sharp_names_each_size_once(self):
        made = SimpleNamespace(bound={"width": ("w_size", ["w_size"]), "height": ("w_size / 2", ["w_size"])})
        prism = SimpleNamespace(built=None, sketch=(made, SimpleNamespace()), slot=None)
        found = corner_hosts.host_of(SimpleNamespace(corner_hosts={}, cut_built={}), prism, 1, "round")
        self.assertEqual((found.cause, found.reason.count("w_size")), (causes.ROUND_UNBINDS, 1))

    def test_limits_keep_each_corner_on_its_side(self):
        # The chamfer at (0, 30) takes 3 from the top of the leg, which is `wall` wide: wall may not go under 3.
        result = run(corners.rounded_outline(ELL, corners.ELL_STEPS))
        (limit,) = [w for p in result.parameters if p["name"] == "wall" for w in p["follows"] if hasattr(w, "low")]
        self.assertAlmostEqual(limit.low, 3.0, places=2)


class RollbackTest(unittest.TestCase):
    def _context(self, capture, upto):
        ctx = Context(capture, table_for(capture), Placement(capture))
        for item in capture["items"][:upto]:
            if item["type"] == "ExtrudeFeature":
                start = len(ctx.solid.pieces)
                ctx.written[item["index"]] = steps.extrude(ctx, as_read(item))
                ctx.shapes[item["index"]] = ctx.solid.pieces[start:]
        return ctx

    def assert_taken_back(self, ctx, item):
        before = [copy.deepcopy(f) for f in ctx.features]
        pieces = list(ctx.solid.pieces)
        hosts = {maker: [(h, list(h.specs), h.count) for h in found] for maker, found in ctx.corner_hosts.items()}
        held = {index: list(found) for index, found in ctx.corner_steps.items()}
        mark = ctx.checkpoint()
        made = finishes.fillet(ctx, as_read(item))
        self.assertNotIsInstance(made, Skip)
        self.assertNotEqual(ctx.features, before)
        ctx.rollback(mark)
        self.assertEqual(ctx.features, before)
        self.assertEqual(ctx.solid.pieces, pieces)
        self.assertEqual({maker: [(h, list(h.specs), h.count) for h in found]
                          for maker, found in ctx.corner_hosts.items()}, hosts)
        self.assertEqual(ctx.corner_steps, held)

    def test_taking_the_corners_back_restores_the_recipe(self):
        capture = corners.rounded_block(corners.FOUR)
        ctx = self._context(capture, 4)
        self.assert_taken_back(ctx, capture["items"][4])

    def test_taking_a_second_round_of_the_same_rectangle_back_restores_the_recipe(self):
        capture = corners.rounded_block([("Fillet1", False, [0, 1], 2.0, None), ("Fillet2", False, [2, 3], 3.0,
                                                                                  None)])
        ctx = self._context(capture, 4)
        self.assertNotIsInstance(finishes.fillet(ctx, as_read(capture["items"][4])), Skip)
        self.assert_taken_back(ctx, capture["items"][5])


if __name__ == "__main__":
    unittest.main()
