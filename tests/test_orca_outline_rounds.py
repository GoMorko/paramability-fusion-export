"""Rounds and chamfers of the side edges of straight extrudes in the Orca copy: drawn into the extrude's outline as
arcs or lines across the corners, and left out with the cause when that would not give Fusion's part. No Fusion and no
Orca: the redrawn outlines are measured against the worked out shapes of `tests/orca_outline.py`."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests import orca_outline as shapes
from tests.orca_extents import UP, extrude, profile, rect, side, sketch_item
from tests.translator_helpers import load_capture

from lib.design_model.design import as_read
from lib.orca_recipe.enums import EntityType, FaceGroup, FeatureType
from lib.orca_translate import FIXED, VARIABLE, causes, finishes, steps, translate
from lib.orca_translate.context import Context
from lib.orca_translate.place import Placement
from lib.params import size_table
from scripts.orca_live_check import table_for


def sketches(result):
    return [f for f in result.recipe.features if f.type == FeatureType.SKETCH]


def finish_features(result):
    return [f for f in result.recipe.features if f.type in (FeatureType.FILLET, FeatureType.CHAMFER)]


def _points(entity):
    """Points along an Orca line or arc, from p0 to p1."""
    if entity.type == EntityType.LINE:
        return [tuple(entity.p0), tuple(entity.p1)]
    a0, a1 = entity.start_angle, entity.end_angle
    return [(entity.center[0] + entity.radius * math.cos(a0 + (a1 - a0) * k / 400.0),
             entity.center[1] + entity.radius * math.sin(a0 + (a1 - a0) * k / 400.0)) for k in range(401)]


def area(feature):
    """The area inside the closed outline of a sketch's lines and arcs, its pieces chained end to end."""
    pieces = [_points(e) for e in feature.entities]
    chain = pieces.pop(0)
    while pieces:
        end = chain[-1]
        n, flip = min(((n, f) for n in range(len(pieces)) for f in (False, True)),
                      key=lambda nf: math.dist(end, pieces[nf[0]][-1 if nf[1] else 0]))
        piece = pieces.pop(n)
        chain += list(reversed(piece)) if flip else piece
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(chain, chain[1:] + chain[:1]))) / 2.0


def kinds(feature):
    return sorted("arc" if e.type == EntityType.ARC else "line" for e in feature.entities)


def left_out(result):
    return [(g["name"], g["cause"]) for g in result.left_out]


class DrawnTest(unittest.TestCase):
    def test_side_edges_of_a_plate_become_arcs_or_corner_lines_of_its_outline(self):
        for chamfer, wanted in ((False, ["arc"] * 4 + ["line"] * 4), (True, ["line"] * 8)):
            with self.subTest(chamfer=chamfer):
                capture = shapes.plate([(shapes.PLATE_SIDES, 2.0)], chamfer)
                result = translate(capture)
                self.assertEqual((left_out(result), finish_features(result)), ([], []))
                (sketch,) = sketches(result)
                self.assertEqual(kinds(sketch), wanted)
                self.assertAlmostEqual(area(sketch) * 10.0, capture["target"]["volume_mm3"], places=2)
                if not chamfer:
                    self.assertEqual({e.radius for e in sketch.entities if e.type == EntityType.ARC}, {2.0})

    def test_corners_into_the_material_are_filled_and_corners_of_it_taken(self):
        cases = {"inward": [([(10, 10, 5)], 3.0)], "inward and outer": [([(10, 10, 5), (40, 0, 5), (0, 30, 5)], 3.0)]}
        for name, sets in cases.items():
            for chamfer in (False, True):
                with self.subTest(name, chamfer=chamfer):
                    capture = shapes.ell(sets, chamfer)
                    result = translate(capture)
                    self.assertEqual(left_out(result), [])
                    self.assertAlmostEqual(area(sketches(result)[0]) * 10.0, capture["target"]["volume_mm3"],
                                           places=2)

    def test_corners_that_are_not_square(self):
        for chamfer in (False, True):
            with self.subTest(chamfer=chamfer):
                capture = shapes.hexagon(2.0, chamfer)
                result = translate(capture)
                self.assertEqual(left_out(result), [])
                self.assertAlmostEqual(area(sketches(result)[0]) * 10.0, capture["target"]["volume_mm3"], places=2)

    def test_the_corners_of_a_cut_are_drawn_into_the_cut(self):
        for name, capture, hole, depth in (
                ("window", shapes.window(3.0), 480.0 - 4 * shapes.corner_area(3.0), 6.0),
                ("pocket", shapes.pocket(2.0), 200.0 - 4 * shapes.corner_area(2.0), 8.0)):
            with self.subTest(name):
                result = translate(capture)
                self.assertEqual(left_out(result), [])
                self.assertAlmostEqual(area(sketches(result)[1]), hole, places=3)

    def test_the_result_lists_the_redrawn_sketch_under_the_extrude_that_wrote_it(self):
        result = translate(shapes.plate([(shapes.PLATE_SIDES, 2.0)]))
        (sketch,) = sketches(result)
        notes = {v["name"]: v["note"] for v in result.items}
        verdicts = {v["name"]: v["verdict"] for v in result.items}
        self.assertEqual((verdicts["Extrude1"], verdicts["Fillet1"]), ("copied", "copied"))
        # The round writes no feature of its own: its line names the sketch it changed and the step that wrote it.
        self.assertEqual([f.name for f in result.recipe.features], [sketch.name, "Extrude1"])
        self.assertTrue(sketch.name in notes["Fillet1"] and "Extrude1" in notes["Fillet1"])

    def test_sides_the_corners_take_whole_are_gone(self):
        result = translate(shapes.window(6.0))
        self.assertEqual(kinds(sketches(result)[1]), ["arc"] * 4 + ["line"] * 2)

    def test_sets_of_different_sizes_each_keep_their_size(self):
        result = translate(load_capture("fillet_two_radii"))
        self.assertEqual(left_out(result), [])
        self.assertEqual(sorted(e.radius for e in sketches(result)[0].entities if e.type == EntityType.ARC),
                         [2.0, 2.0, 3.0, 3.0])


    def test_a_group_round_after_drawn_corners_takes_the_new_outline(self):
        capture = shapes.plate_then_top(3.0, 1.0)
        result = translate(capture)
        self.assertEqual(left_out(result), [])
        (top,) = finish_features(result)
        self.assertEqual((top.face_group, top.dressup_size), (FaceGroup.TOP, 1.0))


class SizeTest(unittest.TestCase):
    def test_the_round_size_stays_a_number_with_the_reason(self):
        capture = shapes.plate([(shapes.PLATE_SIDES, 2.0)], sized=True)
        result = translate(capture, table_for(capture))
        (param,) = result.parameters
        self.assertEqual(param["outcome"], FIXED)
        self.assertEqual(result.variables, {})


class LeftOutTest(unittest.TestCase):
    def test_a_corner_at_a_curved_side_is_left_out(self):
        half_disk = [{"kind": "line", "start": [-10, 0], "end": [10, 0]},
                     {"kind": "arc", "start": [10, 0], "end": [-10, 0], "center": [0, 0], "radius": 10.0,
                      "mid": [0, 10]}]
        capture = shapes.plate([([(10, 0, 5)], 1.0)])
        capture["items"][1]["data"]["profiles"][0]["loops"][0]["curves"] = half_disk
        self.assertEqual(left_out(translate(capture)), [("Fillet1", causes.CORNER_CURVE)])

    def test_rounds_on_an_outline_with_a_spline_are_left_out(self):
        from tests.orca_sweeps import arch
        for name, points in {"side edge": [(0, 0, 5)], "top edges": [(30, 0, 10), (15, 0, 10)]}.items():
            with self.subTest(name):
                capture = arch()
                capture["items"].append(shapes.finish(2, "Fillet1", [(points, 1.0)]))
                self.assertEqual(left_out(translate(capture)), [("Fillet1", causes.EDGES_UNKNOWN)])

    def test_a_round_larger_than_its_side_is_left_out(self):
        capture = shapes.plate([(shapes.PLATE_SIDES[1:3], 11.0)])
        self.assertEqual(left_out(translate(capture)), [("Fillet1", causes.NO_ROOM)])

    def test_a_later_step_against_a_face_next_to_the_edge_leaves_it_out(self):
        for x0, cause in ((14, [("Fillet1", causes.CORNER_CHANGED)]), (8, [])):
            with self.subTest(x0=x0):
                capture = shapes.plate([([(20, 10, 5)], 3.0)])
                fillet = capture["items"].pop()
                capture["items"] += [
                    sketch_item(2, "Sketch2"),
                    extrude(3, "Block", [profile("Sketch2", UP, rect(x0, 10, x0 + 4, 14))], operation="join",
                            side_one=side(10.0), end_offset=10.0,
                            target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]}),
                    dict(fillet, index=4)]
                self.assertEqual(left_out(translate(capture)), cause)

    def test_a_step_left_out_between_the_extrude_and_the_round_leaves_it_out(self):
        capture = shapes.plate([(shapes.PLATE_SIDES, 2.0)])
        fillet = capture["items"].pop()
        capture["items"] += [dict(fillet, index=2, name="Other", type="EmbossFeature", data={}),
                             dict(fillet, index=3)]
        self.assertEqual([cause for name, cause in left_out(translate(capture)) if name == "Fillet1"],
                         [causes.CORNER_CHANGED])

    def test_a_round_left_out_between_counts_only_near_the_corner_or_when_not_measured(self):
        # The box's outline follows sizes, so the round of its corners (radius 4) is left out; then a block (from
        # height z) and a round of one block corner.
        def built(block, z=32.0, gap_points=True):
            capture = shapes.plate_sized_outline(4.0)
            capture["items"].pop()
            # A chamfer of two sizes, 4 and 3, of the box's side edges: left out (Orca chamfers evenly), measured.
            sides = [(x, y, 16) for x, y in ((-40, -30), (40, -30), (40, 30), (-40, 30))]
            gap = shapes.finish(4, "Chamfer1", [(sides, 4.0)], chamfer=True)
            gap["data"]["sets"][0].update(kind="twoDistances", distance_two=3.0)
            if not gap_points:
                for record in gap["data"]["sets"][0]["edges"]:
                    record["points"] = []
            x0, y0, x1, y1 = block
            capture["items"] += [
                sketch_item(2, "Sketch2"),
                extrude(3, "Block", [profile("Sketch2", dict(UP, origin=[0.0, 0.0, z]), rect(x0, y0, x1, y1))],
                        operation="join", side_one=side(10.0), end_offset=10.0,
                        target_box_before={"min": [-40, -30, 0], "max": [40, 30, 32]}),
                gap, shapes.finish(5, "Fillet2", [([(x1, y1, z + 5)], 2.0)])]
            return [g for g in left_out(translate(capture, table_for(capture))) if g[0] == "Fillet2"]

        far, near = (-10, -10, 10, 10), (28, 18, 38, 28)
        self.assertEqual(built(far), [])
        self.assertEqual(built(near), [("Fillet2", causes.CORNER_CHANGED)])
        self.assertEqual(built(far, gap_points=False), [("Fillet2", causes.CORNER_CHANGED)])
        # A block beside the box, its back face in the plane of the box's back face: far, but on a face of the gap.
        self.assertEqual(built((50, 20, 60, 29), z=0.0), [])
        self.assertEqual(built((50, 20, 60, 30), z=0.0), [("Fillet2", causes.CORNER_CHANGED)])

    def test_a_corner_next_to_an_earlier_round_of_a_face_group_is_left_out(self):
        top = [(0, -10, 10), (20, 0, 10), (0, 10, 10), (-20, 0, 10)]
        capture = shapes.plate([(top, 1.0)])
        capture["items"] += [sketch_item(3, "Sketch2"),
                             extrude(4, "Block", [profile("Sketch2", UP, rect(14, 4, 19.5, 9.5))], operation="join",
                                     side_one=side(20.0), end_offset=20.0,
                                     target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]}),
                             shapes.finish(5, "Fillet2", [([(19.5, 9.5, 15)], 1.0)])]
        result = translate(capture)
        self.assertEqual(len(finish_features(result)), 1)
        self.assertEqual(left_out(result), [("Fillet2", causes.CORNER_CHANGED)])

    def test_an_edge_that_goes_on_past_the_measured_point_is_left_out(self):
        capture = shapes.plate([([(-20, -10, 5)], 2.0)])
        fillet = capture["items"].pop()
        top = dict(UP, origin=[0.0, 0.0, 10.0])
        capture["items"] += [sketch_item(2, "Sketch2"),
                             extrude(3, "Stack", [profile("Sketch2", top, rect(-20, -10, 20, 10))], operation="join",
                                     side_one=side(10.0), end_offset=10.0,
                                     target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]}),
                             dict(fillet, index=4)]
        self.assertEqual(left_out(translate(capture)), [("Fillet1", causes.CORNER_CHANGED)])


def pocket_pattern(round_first):
    """A 40 by 20 plate, a square pocket 4 deep and a pattern of it, 3 copies 10 apart; a round of the first pocket's
    upright edges before or after the pattern."""
    capture = copy.deepcopy(load_capture("rpattern_negative"))
    cut = capture["items"][3]["data"]["profiles"][0]
    cut["loops"][0]["curves"] = rect(23, 8, 27, 12)
    for element in capture["items"][4]["data"]["elements"]:
        element["frame"]["origin"][0] = -abs(element["frame"]["origin"][0])
    fillet = shapes.finish(0, "Fillet1", [([(23, 8, 8), (27, 8, 8), (27, 12, 8), (23, 12, 8)], 1.0)])
    pattern = capture["items"].pop()
    capture["items"] += [fillet, pattern] if round_first else [pattern, fillet]
    for n, item in enumerate(capture["items"]):
        item["index"] = n
    capture["items"][-2 if round_first else -1]["data"]["sources"] = [3]
    return capture


class RepeatTest(unittest.TestCase):
    def test_a_round_on_an_outline_a_pattern_copied_is_left_out(self):
        result = translate(pocket_pattern(round_first=False))
        self.assertEqual(left_out(result), [("Fillet1", causes.SKETCH_SHARED)])

    def test_a_pattern_of_an_extrude_with_a_round_drawn_in_is_left_out(self):
        result = translate(pocket_pattern(round_first=True))
        self.assertEqual(left_out(result), [("RectangularPattern1", causes.REPEATS_FINISH)])

    def test_a_round_after_a_mirror_of_the_body_is_left_out(self):
        # The plate of `mirror_body` runs from x 0 to 40 and is mirrored across x = 0; the round is on its far edge.
        for combine, wanted in ((True, [("Fillet1", causes.BODY_COPIED)]), (False, [])):
            with self.subTest(combine=combine):
                capture = load_capture("mirror_body")
                capture["items"][6]["data"]["combine"] = combine
                capture["items"].append(shapes.finish(7, "Fillet1", [([(40, -10, 5)], 2.0)]))
                result = translate(capture)
                self.assertEqual(left_out(result), wanted)
                self.assertEqual(kinds(sketches(result)[0]), [] if combine else ["arc"] + ["line"] * 4)


class RollbackTest(unittest.TestCase):
    def test_taking_the_round_back_restores_the_outline(self):
        capture = shapes.plate([(shapes.PLATE_SIDES, 2.0)])
        ctx = Context(capture, None, Placement(capture))
        extrude_item, fillet = capture["items"][1], capture["items"][2]
        written = steps.extrude(ctx, as_read(extrude_item))
        ctx.written[1], ctx.shapes[1] = written, list(ctx.solid.pieces)
        sketch = written[0]
        before = (copy.deepcopy(sketch.entities), sketch.shape, ctx.solid.pieces[0])
        mark = ctx.checkpoint()
        self.assertEqual(finishes.fillet(ctx, as_read(fillet)), [sketch])
        self.assertEqual(len(sketch.entities), 8)
        ctx.rollback(mark)
        self.assertEqual((sketch.entities, sketch.shape, ctx.solid.pieces[0]), before)
        self.assertEqual(ctx.reshaped, {})


if __name__ == "__main__":
    unittest.main()
