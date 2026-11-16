"""The Orca translation of captures: the features it writes, where they sit, which fields follow variables and what
each ticked parameter became. No Fusion and no Orca: the planes and extents are checked against the capture's box."""
import copy
import math
import sys
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests import orca_extents as ex
from tests.derived_fixtures import MODEL, PARAMS, box_capture, plate_graph, plate_profile
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.capture_model.capture import CaptureError
from lib.design_model import words
from lib.orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType, SketchShape
from lib.orca_recipe.recipe import deserialize, serialize
from lib.orca_translate import FIXED, PARTLY, UNUSED, VARIABLE, causes, translate
from lib.orca_translate.formulas import (OrcaFormulaError, orca_value, to_orca, variable_names,
                                         variable_values)
from lib.orca_translate.place import Placement, moved_box, plane_point
from lib.orca_translate.skip import Skip
from lib.params import size_table

BOX_TICKED = ["box_count", "cube_mm", "depth_mm", "height_mm", "wall_mm", "pipe_d_mm", "pipe_offset_mm"]


def hole_on_origin(capture):
    """The capture with its hole's sketch read as sitting on the origin XY plane, which no size moves."""
    hole = next(it for it in capture["items"] if it["type"] == "HoleFeature")
    hole["data"]["reference"] = {"kind": "constructionPlane", "token": "", "origin": True}
    return capture


def table_of(capture, ticked):
    return size_table.build(capture["parameters"]["user"], ticked, capture["parameters"]["model"])


def kinds(result):
    return [f.type for f in result.recipe.features]


def solids(result):
    return [f for f in result.recipe.features if f.type == FeatureType.EXTRUDE]


def prism_box(recipe, env=None):
    """The box of the New and Add extrudes of rectangle and circle sketches, from the planes and extents as Orca
    builds them, the bound fields worked out over `env` (variable values)."""
    def value(feature, field):
        if env is not None and field in feature.expr:
            return orca_value(feature.expr[field], env)
        return getattr(feature, field)
    points = []
    for f in recipe.features:
        if f.type != FeatureType.EXTRUDE or f.mode not in (BooleanMode.NEW, BooleanMode.ADD):
            continue
        sketch = recipe.features[f.sketch_ref]
        if sketch.entities:
            raise AssertionError("prism_box reads rectangles and circles only")
        if sketch.shape == SketchShape.RECTANGLE:
            hw, hh = value(sketch, "width") / 2, value(sketch, "height") / 2
            outline = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        else:
            r = value(sketch, "radius")
            outline = [(-r, -r), (r, -r), (r, r), (-r, r)]
        d = value(f, "distance")
        spans = {ExtrudeEnd.BLIND: (0.0, -d if f.flip else d), ExtrudeEnd.SYMMETRIC: (-d / 2, d / 2),
                 ExtrudeEnd.TWO_SIDED: (-value(f, "distance2"), d)}[f.extrude_end]
        for xy in outline:
            base = plane_point(sketch.plane, xy)
            for t in spans:
                points.append([base[i] + sketch.plane.normal[i] * t for i in range(3)])
    return {"min": [min(p[i] for p in points) for i in range(3)], "max": [max(p[i] for p in points) for i in range(3)]}


def expected_box(capture):
    return moved_box(Placement(capture).to_orca, capture["target"]["box"])


def assert_box(test, found, wanted, tol=1e-6):
    for key in ("min", "max"):
        for a, b in zip(found[key], wanted[key]):
            test.assertAlmostEqual(a, b, delta=tol)


def plate_with_hole():
    """`extrude_plate` with the outline of the derived plate (a 40 by 20 rectangle from the origin with a circle
    hole placed from its right edge) and the graph of its sketch."""
    capture = copy.deepcopy(load_capture("extrude_plate"))
    capture["items"][1]["data"]["profiles"] = [plate_profile()]
    capture["parameters"] = {"user": PARAMS, "model": MODEL}
    capture["sketch_graphs"] = [plate_graph()[0]]
    return capture


class PlacementTest(unittest.TestCase):
    def test_the_part_sits_on_the_bed_centre_and_the_planes_carry_it_there(self):
        for name in ("extrude_plate", "extrude_two_sides", "extrude_symmetric_half", "extrude_offset_sketch",
                     "extrude_start_offset", "extrude_profiles_two_planes", "zup_plate_yup", "extrude_flipped",
                     "extrude_sign_disagrees"):
            with self.subTest(name):
                capture = load_capture(name)
                result = translate(capture)
                self.assertEqual(result.left_out, [])
                box = expected_box(capture)
                self.assertAlmostEqual((box["min"][0] + box["max"][0]) / 2, 128.0)
                self.assertAlmostEqual(box["min"][2], 0.0)
                assert_box(self, prism_box(result.recipe), box)

    def test_the_modeling_origin_is_the_bed_centre(self):
        result = translate(load_capture("extrude_plate"))
        self.assertEqual(result.recipe.modeling_origin, (128.0, 128.0, 0.0))

    def test_a_y_up_design_is_turned_to_z_up(self):
        capture = load_capture("zup_plate_yup")
        self.assertEqual(capture["up_axis"], "y")
        plane = translate(capture).recipe.features[0].plane
        self.assertAlmostEqual(abs(plane.normal[2]), 1.0)

    def test_a_part_whose_place_in_the_assembly_is_unknown_is_refused(self):
        capture = copy.deepcopy(load_capture("extrude_plate"))
        capture["target"]["placement"] = {"path": "Box:1", "error": "no frame", "uses": 1, "linked": False}
        with self.assertRaises(CaptureError):
            translate(capture)

    def test_a_turned_sketch_keeps_its_axes(self):
        plane = translate(load_capture("extrude_offset_sketch")).recipe.features[0].plane
        self.assertEqual(plane.x_axis, (0.0, 1.0, 0.0))
        self.assertEqual(plane.normal, (0.0, 0.0, 1.0))


class ExtrudeTest(unittest.TestCase):
    def test_one_sided_two_sided_and_symmetric_ends(self):
        two = solids(translate(load_capture("extrude_two_sides")))[0]
        self.assertEqual((two.extrude_end, two.distance, two.distance2), (ExtrudeEnd.TWO_SIDED, 6.0, 4.0))
        sym = solids(translate(load_capture("extrude_symmetric_half")))[0]
        self.assertEqual((sym.extrude_end, sym.distance), (ExtrudeEnd.SYMMETRIC, 10.0))
        flipped = solids(translate(load_capture("extrude_sign_disagrees")))[0]
        self.assertTrue(flipped.flip)

    def test_operations_become_orca_modes(self):
        cut = solids(translate(load_capture("extrude_cut_through_one")))
        self.assertEqual([f.mode for f in cut], [BooleanMode.NEW, BooleanMode.CUT])
        self.assertEqual(cut[1].extrude_end, ExtrudeEnd.THROUGH_ALL)
        joined = solids(translate(load_capture("extrude_two_profiles")))
        self.assertEqual([f.mode for f in joined], [BooleanMode.NEW, BooleanMode.ADD, BooleanMode.ADD])
        meet = solids(translate(load_capture("extrude_intersect")))
        self.assertEqual(meet[1].mode, BooleanMode.INTERSECT)

    def test_a_ring_is_a_circle_with_a_circle_cut_through_it(self):
        result = translate(load_capture("extrude_ring"))
        sketches = [f for f in result.recipe.features if f.type == FeatureType.SKETCH]
        self.assertEqual([(s.shape, s.radius) for s in sketches], [(SketchShape.CIRCLE, 10.0), (SketchShape.CIRCLE, 6.0)])
        self.assertEqual([(f.mode, f.extrude_end) for f in solids(result)],
                         [(BooleanMode.NEW, ExtrudeEnd.BLIND), (BooleanMode.CUT, ExtrudeEnd.THROUGH_ALL)])

    def test_arcs_are_written_through_their_middle(self):
        sketch = translate(load_capture("extrude_slot_arcs")).recipe.features[0]
        arcs = [e for e in sketch.entities if e.type == 1]
        self.assertEqual(len(arcs), 2)
        for arc in arcs:
            mid = (arc.start_angle + arc.end_angle) / 2
            point = (arc.center[0] + arc.radius * math.cos(mid), arc.center[1] + arc.radius * math.sin(mid))
            self.assertTrue(any(abs(point[0] - x) < 1e-9 and abs(point[1]) < 1e-9 for x in (-5.0, 25.0)), point)

    def test_steps_orca_cannot_follow_are_left_out_with_a_cause(self):
        for name, cause in (("extrude_taper", causes.TAPER_SHAPE), ("extrude_thin", gap_hints.THIN_OUTLINE),
                            ("extrude_to_tilted", gap_hints.EXTRUDE_END_FACE),
                            ("extrude_cut_splits_target", gap_hints.REFUSED),
                            ("extrude_taper_unreadable", gap_hints.REFUSED)):
            with self.subTest(name):
                gaps = translate(load_capture(name)).left_out
                self.assertEqual([g["cause"] for g in gaps], [cause])

    def test_a_step_that_lists_another_body_with_the_parts_name_is_left_out(self):
        result = translate(load_capture("extrude_target_token_changes"))
        self.assertEqual([(g["index"], g["cause"]) for g in result.left_out], [(3, causes.BODY_LOST)])
        # A new body named like the part, that lists no body of the part: not passed by as helper geometry.
        capture = copy.deepcopy(load_capture("extrude_plate"))
        step = copy.deepcopy(capture["items"][1])
        step.update(index=2, name="Extrude2", bodies_before=[capture["items"][1]["bodies_after"][0]],
                    bodies_after=[{"token": "t9", "name": capture["target"]["name"]}])
        step["data"].update(operation="newBody", participants=[])
        capture["items"].append(step)
        self.assertEqual([(g["index"], g["cause"]) for g in translate(capture).left_out], [(2, causes.BODY_LOST)])

    def test_an_extrude_through_all_that_adds_material_is_left_out(self):
        # Fusion ends it where the part ends, which moves with the sizes; no Orca length follows that.
        def joined(kind):
            capture = copy.deepcopy(load_capture("extrude_cut_through_one"))
            data = capture["items"][3]["data"]
            data["operation"] = "join"
            through = {"kind": "throughAll", "positive": True, "taper_deg": 0.0}
            if kind == "symmetric":
                data["extent_type"] = "symmetric"
            elif kind == "two":
                data.update(extent_type="two", side_two=dict(through))
            return capture

        def new_body():
            capture = copy.deepcopy(load_capture("extrude_cut_through_one"))
            capture["items"][1]["data"]["side_one"] = {"kind": "throughAll", "positive": True, "taper_deg": 0.0}
            return capture

        for name, capture, index in (("one side", joined("one"), 3), ("symmetric", joined("symmetric"), 3),
                                     ("two sides", joined("two"), 3), ("new body", new_body(), 1)):
            with self.subTest(name):
                result = translate(capture)
                gap = next(g for g in result.left_out if g["index"] == index)
                self.assertEqual(gap["cause"], causes.THROUGH_ALL_ADDS)
        cut = translate(load_capture("extrude_cut_through_one"))
        self.assertEqual(cut.left_out, [])

    def test_a_step_without_a_handler_is_left_out_and_later_steps_still_copy(self):
        result = translate(box_capture())
        self.assertEqual([g["name"] for g in result.left_out], ["Shell1", "Fillet1"])
        verdicts = {i["name"]: i["verdict"] for i in result.items}
        self.assertEqual((verdicts["Extrude1"], verdicts["Hole1"], verdicts["Sketch1"]),
                         ("copied", "copied", "skipped"))

    def test_a_step_left_out_keeps_nothing_its_handler_wrote_first(self):
        walk = sys.modules["lib.orca_translate.translate"]
        real = walk.HANDLERS["ExtrudeFeature"]

        def writes_then_skips(ctx, item):
            real(ctx, item)
            ctx.notes.append("written before the skip")
            ctx.doubt(["cube_mm"], "doubted before the skip")
            return Skip("left out after writing")

        capture = box_capture()
        with mock.patch.dict(walk.HANDLERS, {"ExtrudeFeature": writes_then_skips}):
            result = translate(capture, table_of(capture, BOX_TICKED))
        self.assertIn("Extrude1", [g["name"] for g in result.left_out])
        self.assertEqual((result.recipe.features, result.bound), ([], []))
        self.assertNotIn("written before the skip", result.notes)
        self.assertFalse(any("doubted before the skip" in p["reasons"] for p in result.parameters))
        self.assertFalse(any(p["follows"] for p in result.parameters))

    def test_an_error_in_one_handler_leaves_that_step_out_and_the_copy_goes_on(self):
        walk = sys.modules["lib.orca_translate.translate"]
        real = walk.HANDLERS["HoleFeature"]

        def writes_then_fails(ctx, item):
            real(ctx, item)
            return 1 / 0

        capture = box_capture()
        with mock.patch.dict(walk.HANDLERS, {"HoleFeature": writes_then_fails}):
            result = translate(capture, table_of(capture, BOX_TICKED))
        (gap,) = [g for g in result.left_out if g["name"] == "Hole1"]
        self.assertEqual(gap["cause"], causes.INTERNAL_ERROR)
        self.assertIn("ZeroDivisionError", gap["error"])
        self.assertNotIn(FeatureType.HOLE, kinds(result))
        self.assertEqual({i["name"]: i["verdict"] for i in result.items}["Extrude1"], "copied")

    def test_a_two_sided_extrude_to_planes_checks_the_measured_end_against_its_own_side(self):
        def two_sided_cut(end_offset):
            """A 40 by 20 by 10 plate and a 10 by 10 cut sketched 5 up, two sides: up to a plane 8 up (3 long) and
            down to the origin XY plane (5 long)."""
            up = dict(ex.plane_target(8.0, "cp2"), kind="toEntity", offset=0.0)
            down = {"kind": "toEntity", "offset": 0.0, "entity_type": "ConstructionPlane", "origin": True,
                    "plane": {"point": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0]}}
            items = ex.plate_items(sized=False) + [
                ex.plane_item(2, "Plane1"), ex.sketch_item(3, "Sketch2"),
                ex.extrude(4, "Cut", [ex.profile("Sketch2", ex.at(5.0), ex.rect(-5, -5, 5, 5))], operation="cut",
                           extent="two", side_one=up, side_two=down, end_offset=end_offset,
                           target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]})]
            return ex.capture(items, ((-20, -10, 0), (20, 10, 10)), 7200.0)

        # A face 6 up lies on the first side, 3 long: no match, though a cut may end short of the second side.
        for end, copied in ((3.0, True), (-5.0, True), (6.0, False)):
            with self.subTest(end=end):
                result = translate(two_sided_cut(end))
                self.assertEqual([g["name"] for g in result.left_out], [] if copied else ["Cut"])

    def test_an_extrude_to_a_face_of_another_component_says_why_that_face_cannot_be_placed(self):
        face = {"kind": "toEntity", "offset": 0.0, "foreign": True, "entity_type": "BRepFace",
                "ref": {"type": "BRepFace"}}
        plane = {"kind": "toEntity", "offset": 0.0, "foreign": True, "entity_type": "ConstructionPlane",
                 "ref": {"type": "ConstructionPlane"}, "plane": {"point": [0, 0, 20], "normal": [0, 0, 1]}}
        for target, why in ((face, words.CURVED_TARGET), (plane, words.UNPLACED_TARGET)):
            with self.subTest(why=why):
                items = ex.plate_items(sized=False) + [ex.sketch_item(2, "Sketch2"), ex.extrude(
                    3, "Post", [ex.profile("Sketch2", ex.at(10.0), ex.rect(-5, -5, 5, 5))], operation="join",
                    side_one=target, end_offset=10.0, target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]})]
                (gap,) = translate(ex.capture(items, ((-20, -10, 0), (20, 10, 20)), 9000.0)).left_out
                self.assertEqual((gap["reason"], gap["cause"]), (why, gap_hints.OTHER_COMPONENT))

    def test_a_nearer_end_face_is_accepted_only_where_its_own_side_leaves_the_part(self):
        def two_sided_cut(one, two, end_offset, pocket=False, **face):
            """A 40 by 20 by 10 plate and a 10 by 10 cut sketched 5 up, `one` up and `two` down. With `pocket`, a
            cut first takes the top 4 of the plate inside the same square."""
            items = ex.plate_items(sized=False) + [ex.sketch_item(2, "Sketch2")]
            if pocket:
                items.append(ex.extrude(3, "Pocket", [ex.profile("Sketch2", ex.at(10.0), ex.rect(-5, -5, 5, 5))],
                                        operation="cut", side_one=ex.side(-4.0), end_offset=-4.0,
                                        target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]}))
            items.append(ex.extrude(4, "Cut", [ex.profile("Sketch2", ex.at(5.0), ex.rect(-5, -5, 5, 5))],
                                    operation="cut", extent="two", side_one=ex.side(one), side_two=ex.side(two),
                                    end_offset=end_offset,
                                    target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]}, **face))
            return ex.capture(items, ((-20, -10, 0), (20, 10, 10)), 7000.0)

        cases = (
            ((8.0, 3.0, 5.0, False), True),  # the face is the plate top; its side ends 3 above the part
            ((8.0, 3.0, -2.0, False), False),  # the face is on the side that ends inside material
            ((3.0, 3.0, 2.0, False), False),  # neither side leaves the part
            ((3.0, 3.0, 1.0, True), True),  # the pocket floor: the copy holds no material past it on that side
            ((8.0, 3.0, -2.0, False, {"end_area": 0.96}), True),  # not an end cap: no measure
            ((8.0, 3.0, -2.0, False, {"end_normal": [1, 0, 0]}), True),
            ((8.0, 3.0, -2.0, False, {"end_normal": [0, 0, 1]}), False),
        )
        for args, copied in cases:
            with self.subTest(args=args):
                face = args[4] if len(args) > 4 else {}
                result = translate(two_sided_cut(*args[:4], **face))
                self.assertEqual("Cut" not in [g["name"] for g in result.left_out], copied)

    def test_the_recipe_writes_and_reads_back(self):
        result = translate(box_capture(), table_of(box_capture(), BOX_TICKED))
        back = deserialize(serialize(result.recipe))
        self.assertEqual(back.features, result.recipe.features)
        self.assertEqual(back.variables, result.variables)
        self.assertTrue(all(f.thread_major_nominal and f.pattern_inclusive for f in back.features))


class HoleTest(unittest.TestCase):
    def test_a_hole_sits_on_its_position_and_drills_along_its_direction(self):
        capture = load_capture("hole_blind_flat")
        hole = translate(capture).recipe.features[-1]
        self.assertEqual(hole.type, FeatureType.HOLE)
        self.assertEqual(hole.plane.origin, Placement(capture).point([10, 10, 10]))
        self.assertEqual(hole.plane.normal, (0.0, 0.0, -1.0))
        self.assertEqual((hole.hole_through, hole.hole_depth, hole.hole_diameter), (False, 8.0, 5.0))

    def test_the_measured_bottom_turns_a_stored_direction(self):
        hole = translate(load_capture("hole_direction_disagrees")).recipe.features[-1]
        self.assertEqual(hole.plane.normal, (0.0, 0.0, -1.0))

    def test_counterbore_countersink_and_several_points(self):
        bore = translate(load_capture("hole_counterbore_through")).recipe.features[-1]
        self.assertEqual(bore.hole_style, 1)
        self.assertGreater(bore.hole_cbore_diameter, bore.hole_diameter)
        sink = translate(load_capture("hole_countersink_through")).recipe.features[-1]
        self.assertEqual(sink.hole_style, 2)
        three = translate(load_capture("hole_three_points"))
        self.assertEqual(sum(1 for f in three.recipe.features if f.type == FeatureType.HOLE), 3)

    def test_a_drill_point_left_flat_is_noted(self):
        self.assertEqual(len(translate(load_capture("hole_blind_tip")).notes), 1)


class VariableTest(unittest.TestCase):
    def test_parameters_that_drive_the_box_become_variables_and_follow(self):
        capture = box_capture()
        result = translate(capture, table_of(capture, BOX_TICKED))
        sketch, extrude = result.recipe.features[0], result.recipe.features[1]
        self.assertEqual(sketch.expr, {"width": "box_width_mm", "height": "depth_mm"})
        self.assertEqual(extrude.expr, {"distance": "height_mm"})
        self.assertEqual(result.variables["box_width_mm"], "box_count * cube_mm + 2")
        values = variable_values(result.variables)
        assert_box(self, prism_box(result.recipe, values), expected_box(capture))
        moved = variable_values(dict(result.variables, cube_mm="30", height_mm="20"))
        found = prism_box(result.recipe, moved)
        self.assertAlmostEqual(found["max"][0] - found["min"][0], 92.0)
        self.assertAlmostEqual(found["max"][2] - found["min"][2], 20.0)

    def test_each_ticked_parameter_says_what_it_became(self):
        capture = hole_on_origin(box_capture())
        found = {p["name"]: p for p in translate(capture, table_of(capture, BOX_TICKED)).parameters}
        self.assertEqual(found["height_mm"]["outcome"], VARIABLE)
        self.assertEqual(found["height_mm"]["follows"], ["Extrude1 distance"])
        self.assertEqual(found["pipe_d_mm"]["outcome"], VARIABLE)
        self.assertEqual(found["wall_mm"]["outcome"], FIXED)  # only Shell1 reads it, and Shell1 is left out
        self.assertEqual(found["pipe_offset_mm"]["outcome"], FIXED)

    def test_without_the_sketch_graph_the_rectangle_keeps_its_numbers(self):
        capture = hole_on_origin(box_capture(graph=False))
        result = translate(capture, table_of(capture, BOX_TICKED))
        self.assertEqual(result.recipe.features[0].expr, {})
        found = {p["name"]: p["outcome"] for p in result.parameters}
        self.assertEqual((found["depth_mm"], found["cube_mm"], found["height_mm"]), (FIXED, FIXED, VARIABLE))

    def test_a_plate_with_a_hole_drills_the_hole_where_its_sizes_put_it(self):
        capture = plate_with_hole()
        result = translate(capture, table_of(capture, ["width", "height", "margin"]))
        offsets = sorted(f.expr["cut_offset"] for f in result.recipe.features if "cut_offset" in f.expr)
        self.assertEqual(offsets, ["height", "width"])
        (hole,) = [f for f in result.recipe.features if f.type == FeatureType.HOLE]
        self.assertTrue(hole.hole_through)
        moved = variable_values(dict(result.variables, width="60", height="30", margin="8"))
        centre = [hole.plane.origin[i] + orca_value(hole.expr["hole_x"], moved) * hole.plane.x_axis[i]
                  + orca_value(hole.expr["hole_y"], moved) * hole.plane.y_axis[i] for i in range(3)]
        for a, b in zip(centre, result.place.point((52.0, 15.0, 0.0))):
            self.assertAlmostEqual(a, b)
        self.assertEqual([round(c, 9) for c in hole.plane.normal], [0.0, 0.0, 1.0])  # drilled into the plate
        found = {p["name"]: p["outcome"] for p in result.parameters}
        self.assertEqual(set(found.values()), {VARIABLE})

    def test_a_plate_extruded_the_other_way_drills_its_hole_that_way(self):
        capture = plate_with_hole()
        capture["items"][1]["data"]["end_offset"] = -10.0
        capture["target"]["box"] = {"min": [0.0, 0.0, -10.0], "max": [40.0, 20.0, 0.0]}
        result = translate(capture, table_of(capture, ["width", "height", "margin"]))
        (hole,) = [f for f in result.recipe.features if f.type == FeatureType.HOLE]
        self.assertEqual([round(c, 9) for c in hole.plane.normal], [0.0, 0.0, -1.0])
        moved = variable_values(dict(result.variables, width="60", height="30", margin="8"))
        centre = [hole.plane.origin[i] + orca_value(hole.expr["hole_x"], moved) * hole.plane.x_axis[i]
                  + orca_value(hole.expr["hole_y"], moved) * hole.plane.y_axis[i] for i in range(3)]
        for a, b in zip(centre, result.place.point((52.0, 15.0, 0.0))):
            self.assertAlmostEqual(a, b)

    def test_a_symmetric_plate_keeps_a_plain_rectangle_around_a_hole_that_keeps_its_place(self):
        capture = plate_with_hole()
        data = capture["items"][1]["data"]
        data.update(extent_type="symmetric", side_one=None, end_offset=None,
                    symmetric={"distance": 10.0, "full_length": True, "taper_deg": 0.0})
        capture["target"]["box"] = {"min": [0.0, 0.0, -5.0], "max": [40.0, 20.0, 5.0]}
        result = translate(capture, table_of(capture, ["width", "height", "margin"]))
        # Material on both sides of the sketch: the hole stays a cut that keeps its place, so the rectangle grows
        # about its centre with it rather than being built from cuts.
        self.assertNotIn(FeatureType.HOLE, kinds(result))
        self.assertNotIn(FeatureType.CUT, kinds(result))
        found = {p["name"]: p["outcome"] for p in result.parameters}
        self.assertEqual((found["width"], found["margin"]), (PARTLY, FIXED))

    def test_an_unused_parameter_is_said_to_be_unused(self):
        capture = box_capture()
        capture["parameters"]["user"].append(dict(capture["parameters"]["user"][3], name="spare"))
        found = {p["name"]: p for p in translate(capture, table_of(capture, BOX_TICKED + ["spare"])).parameters}
        self.assertEqual(found["spare"]["outcome"], UNUSED)
        self.assertIsNone(found["spare"]["variable"])


class FormulaTest(unittest.TestCase):
    def test_app_formulas_become_orca_formulas(self):
        names = {"a": "a", "b": "b", "max": "max_v"}
        self.assertEqual(to_orca("2 * pi() * a", names), "2 * pi * a")
        self.assertEqual(to_orca("pow(a, 2) + max", names), "a * a + max_v")
        self.assertEqual(to_orca("min(a, b, 3)", names), "min(a, min(b, 3))")
        self.assertEqual(to_orca("-(a + b) / 2", names), "-(a + b) / 2")

    def test_forms_orca_has_not_are_refused(self):
        for text in ("a > 1 ? a : 2", "round(a)", "mod(a, 2)", "pow(a, 0.5)", "c + 1"):
            with self.subTest(text):
                with self.assertRaises(OrcaFormulaError):
                    to_orca(text, {"a": "a"})

    def test_variable_names_keep_clear_of_orca_words(self):
        self.assertEqual(variable_names(["width", "pi", "max", "pi_v"]),
                         {"width": "width", "pi": "pi_v2", "max": "max_v", "pi_v": "pi_v"})

    def test_variables_are_worked_out_in_order_as_orca_does(self):
        found = variable_values({"w": "a * 2", "a": "sin(30) * 10"})
        self.assertAlmostEqual(found["a"], 5.0)
        self.assertAlmostEqual(found["w"], 10.0)
        with self.assertRaises(Exception):
            variable_values({"a": "b + 1", "b": "a"})


if __name__ == "__main__":
    unittest.main()
