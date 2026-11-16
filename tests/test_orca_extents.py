"""Extrude extents of the Orca copy beyond a plain distance (`orca_translate/extents.py`): an end on a face or plane,
a start on one, a face as the outline, and tapers. Each case checks what Orca is told to build and which parameters
follow, against the captures of tests/orca_extents.py."""
import copy
import math
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests import orca_extents as ex
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType
from lib.orca_translate import FIXED, PARTLY, VARIABLE, causes, limits, translate
from lib.orca_recipe.feature import CadFeature
from lib.orca_translate.formulas import orca_value
from lib.orca_translate.solid import ADD, Solid, Tapered
from lib.params import size_table


def run(capture, ticked=None):
    users = (capture.get("parameters") or {}).get("user")
    table = None
    if users:
        names = [p["name"] for p in users] if ticked is None else ticked
        table = size_table.build(users, names, capture["parameters"]["model"])
    return translate(capture, table)


def extrudes(result):
    return [f for f in result.recipe.features if f.type == FeatureType.EXTRUDE]


def named(result, name):
    return next(f for f in result.recipe.features if f.name == name)


def outcome(result, name):
    return next(p for p in result.parameters if p["name"] == name)


def at(feature, field, **env):
    """A field's value as Orca works it out with the variables `env`."""
    return orca_value(feature.expr[field], env) if field in feature.expr else getattr(feature, field)


class ToTest(unittest.TestCase):
    def test_an_end_on_a_face_that_a_size_moves_follows_that_size(self):
        result = run(ex.to_top_face(offset=5.0))
        post = named(result, "Post")
        self.assertEqual((post.extrude_end, post.flip, post.mode), (ExtrudeEnd.BLIND, False, BooleanMode.ADD))
        self.assertAlmostEqual(post.distance, 15.0)
        self.assertAlmostEqual(at(post, "distance", h=20.0), 25.0)
        self.assertEqual(outcome(result, "h")["outcome"], VARIABLE)

    def test_an_end_on_an_offset_plane_follows_its_distance(self):
        result = run(ex.to_offset_plane(lift=15.0))
        post = named(result, "Post")
        self.assertAlmostEqual(post.distance, 15.0)
        self.assertAlmostEqual(at(post, "distance", lift_mm=25.0), 25.0)
        self.assertEqual(outcome(result, "lift_mm")["outcome"], VARIABLE)

    def test_two_sides_to_two_planes_follow_the_plane_that_moves(self):
        result = run(ex.two_planes(top=20.0))
        (rod,) = extrudes(result)
        self.assertEqual(rod.extrude_end, ExtrudeEnd.TWO_SIDED)
        self.assertEqual((rod.distance, rod.distance2), (15.0, 5.0))
        self.assertAlmostEqual(at(rod, "distance", top_mm=30.0), 25.0)
        self.assertNotIn("distance2", rod.expr)
        self.assertEqual(outcome(result, "top_mm")["outcome"], VARIABLE)

    def test_a_face_no_copied_step_places_keeps_the_length_and_marks_its_sizes(self):
        capture = ex.to_top_face()
        capture["items"][3]["data"]["side_one"]["face_point"] = [20.0, 0.0, 5.0]  # on a side wall
        result = run(capture)
        self.assertNotIn("distance", named(result, "Post").expr)
        self.assertEqual(outcome(result, "h")["outcome"], PARTLY)

    def test_an_end_on_a_plane_no_size_moves_is_its_measured_length(self):
        result = run(load_capture("extrude_to_plane"))
        self.assertEqual(result.left_out, [])
        post = extrudes(result)[1]
        self.assertEqual((post.extrude_end, post.flip, post.distance), (ExtrudeEnd.BLIND, False, 10.0))

    def test_the_taper_of_a_side_that_ends_on_a_face_comes_from_its_parameter(self):
        capture = ex.to_top_face()
        data = capture["items"][3]["data"]
        data["params"]["side_one.taper_deg"] = ex.param("d5", "-5 deg", -5.0)
        data["side_leans"] = [math.sin(math.radians(5.0))] * 4
        self.assertEqual(named(run(capture), "Post").taper_deg, -5.0)
        del data["params"]["side_one.taper_deg"]
        self.assertEqual([g["cause"] for g in run(capture).left_out], [gap_hints.REFUSED])

    def test_a_measured_end_elsewhere_leaves_the_step_out(self):
        capture = ex.to_top_face()
        capture["items"][3]["data"]["end_offset"] = 12.0
        self.assertEqual([g["cause"] for g in run(capture).left_out], [gap_hints.REFUSED])

    def test_a_cut_may_end_short_of_its_length_only_where_it_leaves_the_part(self):
        def cut_up(top, end, post=False, thin_before=False):
            """A 40 by 20 by 10 plate, optionally a 30 tall post beside the cut (the part's box then reaches past the
            cut's end) and a thin extrude the copy leaves out, then a 10 by 10 cut from the base up to a plane `top`
            above it, whose measured end face is `end` up."""
            items = ex.plate_items(sized=False)
            box = {"min": [-20, -10, 0], "max": [20, 10, 30 if post else 10]}
            if post:
                items.append(ex.extrude(2, "Post", [ex.profile("Sketch1", ex.UP, ex.rect(15, -5, 20, 5))],
                                        operation="join", side_one=ex.side(30.0), end_offset=30.0,
                                        target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]}))
            if thin_before:
                items.append(ex.extrude(3, "Rib", [ex.profile("Sketch1", ex.UP, ex.rect(-20, 8, 20, 10))],
                                        operation="join", side_one=ex.side(10.0), end_offset=10.0, thin=True,
                                        target_box_before=box))
            items += [ex.plane_item(4, "Plane1"), ex.sketch_item(5, "Sketch2"),
                      ex.extrude(6, "Cut", [ex.profile("Sketch2", ex.UP, ex.rect(-5, -5, 5, 5))], operation="cut",
                                 side_one=dict(ex.plane_target(top, "cp1"), kind="toEntity", offset=0.0),
                                 end_offset=end, target_box_before=box)]
            return ex.capture(items, (box["min"], box["max"]), 7000.0)

        cases = (("end past the whole part", cut_up(20.0, 10.0), True),
                 ("leaves the part the copy built", cut_up(20.0, 10.0, post=True), True),
                 ("ends inside material", cut_up(8.0, 6.0), False),
                 ("the copy's part misses a step", cut_up(20.0, 10.0, post=True, thin_before=True), False))
        for name, capture, copied in cases:
            with self.subTest(name):
                left = [g["name"] for g in run(capture).left_out]
                self.assertEqual("Cut" not in left, copied)

    def test_both_sides_on_one_side_of_the_sketch_are_left_out(self):
        capture = ex.two_planes()
        capture["items"][3]["data"]["side_two"]["plane"]["point"] = [0.0, 0.0, 10.0]
        self.assertEqual([g["cause"] for g in run(capture).left_out], [gap_hints.EXTRUDE_END_FACE])


class MeasuredEndTest(unittest.TestCase):
    """The checks against what Fusion measured come from the shared reader, for every kind of side."""

    def plate(self, **data):
        items = ex.plate_items(sized=False)
        items[1]["data"].update(data)
        return run(ex.capture(items, ((-20, -10, 0), (20, 10, 10)), 8000.0))

    def test_a_plain_extrude_whose_end_face_is_elsewhere_is_left_out(self):
        self.assertEqual(self.plate().left_out, [])
        self.assertEqual([g["index"] for g in self.plate(end_offset=12.0).left_out], [1])

    def test_a_symmetric_extrude_is_checked_at_half_its_length(self):
        sym = {"extent_type": "symmetric", "side_one": None,
               "symmetric": {"distance": 5.0, "full_length": False, "taper_deg": 0.0}}
        self.assertEqual(self.plate(end_offset=-5.0, **sym).left_out, [])
        self.assertEqual([g["index"] for g in self.plate(end_offset=10.0, **sym).left_out], [1])

    def test_two_sides_whose_end_face_fits_only_the_turned_sides_are_turned(self):
        result = self.plate(extent_type="two", end_offset=-6.0, side_one=ex.side(6.0), side_two=ex.side(4.0))
        (plate,) = extrudes(result)
        self.assertEqual((plate.extrude_end, plate.distance, plate.distance2), (ExtrudeEnd.TWO_SIDED, 4.0, 6.0))


class FromTest(unittest.TestCase):
    def test_a_start_on_a_face_moves_the_sketch_and_marks_the_sizes_that_move_the_face(self):
        result = run(ex.from_top_face(length=5.0))
        boss = named(result, "Boss")
        sketch = result.recipe.features[boss.sketch_ref]
        self.assertAlmostEqual(sketch.plane.origin[2], result.place.point([0.0, 0.0, 10.0])[2])
        self.assertEqual((boss.extrude_end, boss.distance), (ExtrudeEnd.BLIND, 5.0))
        self.assertEqual(outcome(result, "h")["outcome"], PARTLY)

    def test_a_start_at_a_distance_from_a_face_is_left_out(self):
        capture = ex.from_top_face()
        capture["items"][3]["data"]["params"]["start.offset"] = ex.param("d9", "2 mm", 2.0)
        self.assertEqual([g["cause"] for g in run(capture).left_out], [gap_hints.EXTRUDE_END_FACE])

    def test_a_face_as_the_outline_is_drawn_where_it_is_now(self):
        result = run(ex.face_outline(length=5.0))
        self.assertEqual(result.left_out, [])
        raise_ = named(result, "Raise")
        sketch = result.recipe.features[raise_.sketch_ref]
        self.assertAlmostEqual(sketch.plane.origin[2], result.place.point([0.0, 0.0, 10.0])[2])
        self.assertEqual(outcome(result, "h")["outcome"], PARTLY)


class TaperTest(unittest.TestCase):
    def test_a_shrinking_block_keeps_its_taper_as_a_number(self):
        result = run(ex.tapered_block(deg=-5.0, sized=True))
        (block,) = extrudes(result)
        self.assertEqual((block.extrude_end, block.flip, block.taper_deg), (ExtrudeEnd.BLIND, False, -5.0))
        self.assertNotIn("taper_deg", block.expr)
        self.assertEqual(outcome(result, "draft_deg")["outcome"], FIXED)

    def test_a_rod_taper_follows_its_size_and_turns_with_the_direction(self):
        for down, sign in ((False, 1.0), (True, -1.0)):
            with self.subTest(down=down):
                result = run(ex.tapered_rod(deg=-10.0, down=down))
                (rod,) = extrudes(result)
                self.assertEqual((rod.flip, rod.taper_deg), (down, sign * -10.0))
                self.assertAlmostEqual(at(rod, "taper_deg", draft_deg=-5.0), sign * -5.0)
                self.assertEqual(outcome(result, "draft_deg")["outcome"], VARIABLE)

    def test_a_tapered_extrude_to_both_sides_is_two_blind_halves(self):
        result = run(ex.tapered_symmetric(deg=-10.0))
        halves = extrudes(result)
        self.assertEqual([(f.extrude_end, f.flip, f.mode, f.taper_deg, f.distance) for f in halves],
                         [(ExtrudeEnd.BLIND, False, BooleanMode.NEW, -10.0, 10.0),
                          (ExtrudeEnd.BLIND, True, BooleanMode.ADD, 10.0, 10.0)])
        self.assertEqual(halves[0].sketch_ref, halves[1].sketch_ref)
        sides = extrudes(run(ex.tapered_two_sides(up=-10.0, down=-5.0)))
        self.assertEqual([(f.flip, f.taper_deg, f.distance) for f in sides], [(False, -10.0, 10.0), (True, 5.0, 5.0)])

    def test_a_smooth_slot_and_a_tapered_cut_are_copied(self):
        for capture in (ex.tapered_slot(), ex.tapered_cut()):
            with self.subTest(capture["items"][-1]["name"]):
                result = run(capture)
                self.assertEqual(result.left_out, [])
                self.assertNotEqual(extrudes(result)[-1].taper_deg, 0.0)

    def test_outlines_orca_tapers_otherwise_are_left_out(self):
        square = ex.rect(-5, -5, 5, 5)
        cases = (("arcs meeting at corners", ex.tapered_outline(ex.lens(), -25.0)),
                 ("a growing square", ex.tapered_outline(square, 5.0)),
                 ("a square with a hole", ex.tapered_outline(square, -5.0, holes=[ex.circle(1.0)])),
                 ("a circle shrunk to nothing", ex.tapered_outline(ex.circle(1.0), -40.0)))
        for name, capture in cases:
            with self.subTest(name):
                self.assertEqual([g["cause"] for g in run(capture).left_out], [causes.TAPER_SHAPE])

    def test_a_taper_on_a_cut_through_all_is_left_out(self):
        capture = copy.deepcopy(load_capture("extrude_cut_through_one"))
        capture["items"][3]["data"]["side_one"]["taper_deg"] = -5.0
        self.assertEqual([g["cause"] for g in translate(capture).left_out], [causes.TAPER_EXTENT])


def limit_of(param):
    """The limit told on a parameter's line (`limits.Limit`), or None."""
    found = [text for text in param["follows"] if isinstance(text, limits.Limit)]
    return found[0] if found else None


def sketched_up(lift, z):
    """`to_offset_plane` with the post sketched `z` up: its length is lift_mm - z."""
    capture = ex.to_offset_plane(lift=lift)
    post = capture["items"][-1]["data"]
    post["profiles"][0]["frame"], post["end_offset"] = ex.at(z), lift - z
    return capture


class LimitTest(unittest.TestCase):
    def test_a_to_length_that_a_variable_takes_to_zero_tells_how_far_it_may_go(self):
        # The limit is told also when it is far from the value: past it Orca extrudes the other way without an error.
        for lift, z in ((15.0, 5.0), (100.0, 5.0)):
            with self.subTest(lift=lift):
                param = outcome(run(sketched_up(lift, z)), "lift_mm")
                self.assertEqual(param["outcome"], VARIABLE)
                self.assertEqual((limit_of(param).low, limit_of(param).high), (z, None))
                self.assertEqual(limit_of(param).why, (limits.END_PASSES_START, None))

    def test_a_to_length_no_variable_takes_to_zero_tells_nothing(self):
        param = outcome(run(ex.to_offset_plane(lift=15.0)), "lift_mm")
        self.assertIsNone(limit_of(param))

    def test_a_taper_angle_that_would_shrink_the_outline_to_nothing_tells_how_far_it_may_go(self):
        for down in (False, True):
            with self.subTest(down=down):
                param = outcome(run(ex.tapered_rod(deg=-10.0, down=down)), "draft_deg")
                # A radius of 10 over a length of 10 closes at 45 degrees in (less the 0.05 mm kept).
                self.assertAlmostEqual(limit_of(param).low, -math.degrees(math.atan(9.95 / 10.0)), delta=0.1)
                self.assertEqual(limit_of(param).why[0], limits.TAPER_CLOSES)

    def test_only_a_limit_orca_stops_on_may_be_left_untold_for_being_far(self):
        for near, high in ((True, None), (False, 60.0)):
            with self.subTest(near=near):
                found = limits.words("h", None, 60.0, 5.0, " mm", near)
                self.assertEqual(found.high if found is not None else None, high)

    def test_a_later_end_on_an_extrude_whose_length_was_unbound_keeps_its_number(self):
        capture = ex.to_top_face(offset=5.0)
        cap = copy.deepcopy(capture["items"][-1])
        cap["index"], cap["name"] = 4, "Cap"
        cap["data"].update(profiles=[ex.profile("Sketch2", ex.UP, ex.rect(-2, -2, 2, 2))], end_offset=15.0,
                           side_one=dict(ex.face_target(15.0, (1.0, 1.0)), kind="toEntity", offset=0.0),
                           target_box_before={"min": [-20, -10, 0], "max": [20, 10, 15]})
        capture["items"].append(cap)
        real = limits.guard

        def unsure_post(ctx, fields, ok, reason):
            # The Post's check cannot be worked out, so its length is unbound and keeps its number.
            return real(ctx, fields, ok if fields[0][0].name != "Post" else (lambda numbers: False), reason)

        with mock.patch.object(limits, "guard", unsure_post):
            result = run(capture)
        self.assertNotIn("distance", named(result, "Post").expr)
        self.assertNotIn("distance", named(result, "Cap").expr)
        self.assertAlmostEqual(named(result, "Cap").distance, 15.0)
        self.assertEqual(outcome(result, "h")["outcome"], PARTLY)

    def test_each_limit_keeps_the_cause_of_the_first_value_past_it(self):
        sketch = CadFeature(name="Box sketch")
        sketch.expr["width"] = "w - 5"  # the shape reaches zero at w = 5
        found = limits.ranges(_Context({"w": "10"}), [(sketch, "width")],
                              lambda numbers: limits.stop(numbers[0] < 15.0, limits.CUTS_DIFFER))
        self.assertEqual(found["w"].why, (limits.SHAPE_ZERO, limits.CUTS_DIFFER))
        unsaid = limits.ranges(_Context({"w": "10"}), [(sketch, "width")], lambda numbers: numbers[0] < 15.0)
        self.assertEqual(unsaid["w"].why, (limits.SHAPE_ZERO, None))
        told = limits.words("w", 5.0, 20.0, 10.0, " mm", False, why=found["w"].why)
        self.assertEqual(told.why, (limits.SHAPE_ZERO, limits.CUTS_DIFFER))
        self.assertEqual(limits.words("w", None, 20.0, 10.0, " mm", False, why=found["w"].why).why,
                         (None, limits.CUTS_DIFFER))

    def test_a_shape_size_is_walked_down_to_zero_itself(self):
        # Values near zero are tested as Orca writes them, without an exponent, so the walk reaches the true end.
        sketch = CadFeature(name="Box sketch")
        sketch.expr["width"] = "w"
        found = limits.ranges(_Context({"w": "10"}), [(sketch, "width")], lambda numbers: True)
        self.assertLess(found["w"][0], 1e-6)
        self.assertEqual(found["w"].why, (limits.SHAPE_ZERO, None))

    def test_a_field_whose_limit_cannot_be_told_keeps_its_number(self):
        extrude = CadFeature(name="Post")
        ctx = _Context({"lift_mm": "15"})
        ctx.bind(extrude, "distance", "lift_mm - 5", ["lift_mm"], "Post distance")
        # A check that fails at the current values cannot place the limit.
        limits.guard(ctx, [(extrude, "distance", "Post distance")], lambda numbers: False, "why")
        self.assertEqual((extrude.expr, ctx.bound, ctx.follows, ctx.doubts), ({}, [], {}, {"lift_mm": ["why"]}))


class _Context:
    """The part of a translation context that `limits.guard` reads and changes."""

    def __init__(self, variables):
        self._variables = variables
        self.table = None
        self.bound, self.follows, self.doubts = [], {}, {}

    def variables(self):
        return dict(self._variables)

    def bind(self, feature, field, formula, reads, where):
        feature.expr[field] = formula
        self.bound.append({"feature": feature.name, "field": field, "formula": formula, "reads": list(reads)})
        for name in reads:
            self.follows.setdefault(name, []).append(where)

    def doubt(self, names, reason):
        for name in names:
            self.doubts.setdefault(name, []).append(reason)


class TaperedShapeTest(unittest.TestCase):
    def test_a_line_through_a_tapered_block_ends_at_its_leaning_walls(self):
        block = Tapered(ex.UP, ex.rect(0, 0, 40, 20), 0.0, 10.0, math.tan(math.radians(-45.0)))
        # At height 5 the walls have moved 5 in: the line along x meets the block from 5 to 35.
        (span,) = block.span([-10.0, 10.0, 5.0], [1.0, 0.0, 0.0])
        self.assertAlmostEqual(span[0], 15.0, delta=1e-6)
        self.assertAlmostEqual(span[1], 45.0, delta=1e-6)

    def test_the_box_of_a_growing_rod_is_its_wide_end(self):
        rod = Tapered(ex.UP, ex.circle(10.0), 0.0, 10.0, math.tan(math.radians(10.0)))
        box = Solid([(ADD, rod)]).box()
        wide = 10.0 + 10.0 * math.tan(math.radians(10.0))
        for got, want in zip(box["min"] + box["max"], [-wide, -wide, 0.0, wide, wide, 10.0]):
            self.assertAlmostEqual(got, want, delta=1e-3)


if __name__ == "__main__":
    unittest.main()
