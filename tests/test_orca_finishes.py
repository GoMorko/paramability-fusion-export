"""Fillets and chamfers in the Orca copy: a step whose picked edges are one of Orca's face groups of the copied part
becomes an Orca round or chamfer of that group; every other one, and shells and drafts, are left out with the reason.
No Fusion and no Orca: the groups are worked out from the copied extrudes and holes."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import model, user
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import FaceGroup, FeatureType
from lib.orca_recipe.recipe import deserialize, serialize
from lib.orca_translate import FIXED, causes, limits, translate
from lib.orca_translate import finish_body
from lib.params import size_table

# The plate of `extrude_plate`: 40 by 20, 10 high, from the origin.
TOP = [[20, 0, 10], [40, 10, 10], [20, 20, 10], [0, 10, 10]]
BOTTOM = [[x, y, 0] for x, y, _ in TOP]
SIDES = [[0, 0, 5], [40, 0, 5], [40, 20, 5], [0, 20, 5]]


def edges(points):
    return [{"token": "e%d" % n, "closed": False, "points": [p]} for n, p in enumerate(points)]


def finish_item(index, kind, points, size, **set_more):
    """A fillet ("FilletFeature") or chamfer ("ChamferFeature") of one set over edges at `points` (or edge
    records)."""
    entry = {"kind": "constant", "radius": size, "continuity": "tangent"} if kind == "FilletFeature" else \
        {"kind": "equal", "distance": size}
    records = points if points and isinstance(points[0], dict) else edges(points)
    entry.update(input_kinds=["edge"], edges=records)
    entry.update(set_more)
    name = ("Fillet%d" if kind == "FilletFeature" else "Chamfer%d") % index
    data = {"rolling_ball": True, "sets": [entry]} if kind == "FilletFeature" else \
        {"corner_type": "chamfer", "sets": [entry]}
    return {"index": index, "name": name, "type": kind, "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}], "data": data}


def plate(*finishes, base="extrude_plate"):
    capture = copy.deepcopy(load_capture(base))
    for kind, points, size in finishes:
        capture["items"].append(finish_item(len(capture["items"]), kind, points, size))
    return capture


def finishes(result):
    return [f for f in result.recipe.features if f.type in (FeatureType.FILLET, FeatureType.CHAMFER)]


def left_out(result, name):
    return next((g for g in result.left_out if g["name"] == name), None)


class GroupTest(unittest.TestCase):
    def test_edges_that_are_one_face_group_become_that_group(self):
        cases = {"top": (TOP, FaceGroup.TOP), "bottom": (BOTTOM, FaceGroup.BOTTOM),
                 "all": (TOP + BOTTOM + SIDES, FaceGroup.ALL)}
        for name, (points, group) in cases.items():
            with self.subTest(name):
                result = translate(plate(("FilletFeature", points, 2.0)))
                (made,) = finishes(result)
                self.assertEqual((made.type, made.face_group, made.dressup_size), (FeatureType.FILLET, group, 2.0))
                self.assertEqual(result.left_out, [])

    def test_hand_picked_edges_are_left_out(self):
        for name, points in {"three of four top": TOP[:3], "top and one side": TOP + SIDES[:1]}.items():
            with self.subTest(name):
                result = translate(plate(("FilletFeature", points, 1.0)))
                self.assertEqual(finishes(result), [])
                self.assertEqual(left_out(result, "Fillet2")["cause"], causes.HAND_PICKED)

    def test_a_round_with_a_set_whose_edges_are_not_known_is_left_out(self):
        capture = plate(("FilletFeature", TOP, 2.0))
        unread = dict(finish_item(0, "FilletFeature", [], 1.0)["data"]["sets"][0], input_kinds=[], read_error="x")
        capture["items"][-1]["data"]["sets"].append(unread)
        result = translate(capture)
        self.assertEqual(finishes(result), [])
        self.assertEqual(left_out(result, "Fillet2")["cause"], gap_hints.SET_UNREAD)

    def test_edges_not_on_the_copy_are_left_out(self):
        result = translate(plate(("ChamferFeature", [[20, 0, 12]], 1.0)))
        self.assertEqual(finishes(result), [])
        self.assertEqual(left_out(result, "Chamfer2")["cause"], causes.EDGES_NOT_ON_COPY)

    def test_a_closed_edge_picked_by_its_two_points(self):
        (made,) = finishes(translate(load_capture("fillet_closed_edge")))
        self.assertEqual(made.face_group, FaceGroup.TOP)

    def test_the_top_of_a_y_up_part_is_orcas_top(self):
        capture = plate(("FilletFeature", [[25, 12, -17], [45, 12, -7], [25, 12, 3], [5, 12, -7]], 1.0),
                        base="zup_plate_yup")
        (made,) = finishes(translate(capture))
        self.assertEqual(made.face_group, FaceGroup.TOP)

    def test_a_hole_through_the_part_adds_its_rim_to_the_top_edges(self):
        rim = {"token": "rim", "closed": True, "points": [[12.5, 10, 10], [7.5, 10, 10]]}
        without = translate(plate(("FilletFeature", TOP, 1.0), base="hole_through"))
        self.assertEqual(finishes(without), [])
        (made,) = finishes(translate(plate(("FilletFeature", edges(TOP) + [rim], 1.0), base="hole_through")))
        self.assertEqual(made.face_group, FaceGroup.TOP)

    def test_smooth_edges_may_be_picked_or_not(self):
        caps = [[10, -5, z] for z in (0, 10)] + [[10, 5, z] for z in (0, 10)] + \
               [[-5, 0, z] for z in (0, 10)] + [[25, 0, z] for z in (0, 10)]
        smooth = [[0, -5, 5], [0, 5, 5], [20, 5, 5], [20, -5, 5]]
        for name, points in {"without": caps, "with": caps + smooth}.items():
            with self.subTest(name):
                (made,) = finishes(translate(plate(("FilletFeature", points, 1.0), base="extrude_slot_arcs")))
                self.assertEqual(made.face_group, FaceGroup.ALL)

    def test_a_part_of_several_extrudes_is_left_out(self):
        result = translate(plate(("FilletFeature", TOP, 1.0), base="extrude_two_profiles"))
        self.assertEqual(finishes(result), [])
        self.assertEqual(left_out(result, "Fillet%d" % (len(result.items) - 1))["cause"], causes.EDGES_UNKNOWN)


class SizeTest(unittest.TestCase):
    def test_the_size_follows_its_parameter(self):
        capture = plate(("ChamferFeature", TOP, 1.0))
        capture["parameters"] = {"user": [user("edge", "1 mm", 1)], "model": [model("d9", "edge", 1)]}
        capture["items"][-1]["data"]["params"] = {"sets.0.distance": {"name": "d9", "expression": "edge",
                                                                      "value": 1.0}}
        table = size_table.build(capture["parameters"]["user"], ["edge"], capture["parameters"]["model"])
        result = translate(capture, table)
        (made,) = finishes(result)
        self.assertEqual(made.expr, {"dressup_size": "edge"})
        self.assertEqual(result.variables, {"edge": "1"})

    def test_a_size_that_leaves_too_little_of_a_face_is_left_out(self):
        for name, (points, size) in {"narrow top": (TOP, 9.5), "short sides": (TOP + BOTTOM + SIDES, 4.8)}.items():
            with self.subTest(name):
                result = translate(plate(("FilletFeature", points, size)))
                self.assertEqual(finishes(result), [])
                self.assertEqual(left_out(result, "Fillet2")["cause"], causes.NO_ROOM)
        self.assertEqual(len(finishes(translate(plate(("FilletFeature", TOP, 8.0))))), 1)

    def test_room_rules(self):
        body = finish_body.body_of(_solid("extrude_slot_arcs"))
        self.assertIsNone(finish_body.room(body, 2.0, 2))
        self.assertIsNotNone(finish_body.room(body, 4.6, 0))  # the arcs of radius 5
        self.assertIsNotNone(finish_body.room(body, 4.6, 2))  # 10 high
        self.assertIsNotNone(finish_body.room(body, 0.0005, 1))


def _solid(name):
    from lib.orca_translate.context import Context
    from lib.orca_translate.place import Placement
    from lib.orca_translate.steps import extrude
    from lib.design_model.design import as_read
    capture = load_capture(name)
    ctx = Context(capture, None, Placement(capture))
    extrude(ctx, as_read(capture["items"][1]))
    return ctx.solid


def hole_after(capture, x, depth):
    """`capture` with a blind 5 mm hole `depth` deep drilled down into the top of the plate at (x, 10)."""
    hole = copy.deepcopy(load_capture("hole_through")["items"][3])
    hole["index"] = len(capture["items"])
    hole["data"].update(positions=[[x, 10, 10]], extent={"kind": "distance", "depth": depth},
                        end_points=[[x, 10, 10 - depth]])
    capture["items"].append(hole)
    return capture


class RoundedTest(unittest.TestCase):
    def test_a_later_hole_must_meet_material_away_from_rounded_edges(self):
        near = translate(hole_after(plate(("FilletFeature", TOP, 3.0)), 1.5, 1.0))
        self.assertEqual(left_out(near, "Hole1")["cause"], causes.NEAR_ROUND)
        for capture in (hole_after(plate(("FilletFeature", TOP, 3.0)), 20.0, 1.0),
                        hole_after(plate(("FilletFeature", TOP, 3.0)), 1.5, 5.0),
                        hole_after(plate(("FilletFeature", BOTTOM, 3.0)), 1.5, 1.0)):
            with self.subTest(capture["items"][2]["data"]["sets"][0]["edges"][0]["points"]):
                self.assertEqual(translate(capture).left_out, [])

    def test_the_material_a_round_may_take(self):
        solid = _solid("extrude_plate")
        body = finish_body.body_of(solid)
        taken = finish_body.group_edges(body, finish_body.face_groups(body, lambda d: d), FaceGroup.TOP)
        zone = finish_body.Rounded(body, [body.edges[n] for n in taken], 2.0, solid, solid.pieces[0][1],
                                   lambda: True)
        down = [0.0, 0.0, -1.0]
        self.assertEqual(zone.span([1.0, 10.0, 20.0], down), [(8.0, 12.0)])  # 1 mm from a top edge
        self.assertEqual(zone.span([20.0, 10.0, 20.0], down), [])  # the middle of the top
        across = zone.span([-5.0, 10.0, 9.0], [1.0, 0.0, 0.0])
        self.assertEqual(len(across), 2)
        self.assertAlmostEqual(across[0][1], 7.0, places=6)
        self.assertAlmostEqual(across[1][0], 43.0, places=6)

    def test_a_round_size_that_follows_a_size_gets_its_largest_value(self):
        capture = plate(("ChamferFeature", TOP, 1.0))
        capture["parameters"] = {"user": [user("edge", "1 mm", 1)], "model": [model("d9", "edge", 1)]}
        capture["items"][-1]["data"]["params"] = {"sets.0.distance": {"name": "d9", "expression": "edge",
                                                                      "value": 1.0}}
        table = size_table.build(capture["parameters"]["user"], ["edge"], capture["parameters"]["model"])
        (param,) = translate(capture, table).parameters
        self.assertEqual((param["outcome"], len(param["follows"])), ("variable", 2))
        # Orca stops the rebuild on a chamfer of no size, so the lower limit is told too.
        (told,) = [w for w in param["follows"] if hasattr(w, "low")]
        self.assertGreater(told.low, 0.0)
        body = finish_body.body_of(_solid("extrude_plate"))
        chamfer = finishes(translate(capture, table))[0]
        (low, high), = limits.ranges(_Variables({"edge": "1"}), [(chamfer, "dressup_size")],
                                     lambda sizes: finish_body.room(body, sizes[0], 1) is None).values()
        self.assertIsNone(finish_body.room(body, high, 1))
        self.assertIsNotNone(finish_body.room(body, high * 1.001, 1))


class _Variables:
    """The part of a translation context that `limits.ranges` reads."""

    def __init__(self, variables):
        self._variables = variables

    def variables(self):
        return dict(self._variables)


class KindTest(unittest.TestCase):
    def test_kinds_orca_cannot_make_are_left_out(self):
        cases = {"fillet_variable": gap_hints.ROUND_KIND,
                 "fillet_g2": gap_hints.REFUSED, "fillet_feature_input": gap_hints.REFUSED,
                 "chamfer_uneven": gap_hints.REFUSED, "chamfer_two_sides": gap_hints.REFUSED,
                 "shell_open_top": causes.FACE_BY_NUMBER, "shell_closed": causes.FACE_BY_NUMBER}
        for name, cause in cases.items():
            with self.subTest(name):
                result = translate(load_capture(name))
                self.assertEqual(finishes(result), [])
                self.assertEqual([g["cause"] for g in result.left_out], [cause])

    def test_a_group_of_edges_with_two_sizes_is_left_out(self):
        capture = plate(("FilletFeature", TOP[:2], 1.0))
        capture["items"][-1]["data"]["sets"].append(dict(capture["items"][-1]["data"]["sets"][0], radius=2.0,
                                                         edges=edges(TOP[2:])))
        result = translate(capture)
        self.assertEqual([g["cause"] for g in result.left_out], [gap_hints.ROUND_KIND])

    def test_even_chamfers_given_two_ways_are_copied_and_the_second_value_stays(self):
        for name in ("chamfer_two_equal", "chamfer_angle_45"):
            with self.subTest(name):
                (made,) = finishes(translate(load_capture(name)))
                self.assertEqual((made.type, made.face_group), (FeatureType.CHAMFER, FaceGroup.TOP))
        capture = load_capture("chamfer_two_equal")
        capture["parameters"] = {"user": [user("side", "1 mm", 1)], "model": [model("d9", "side", 1)]}
        capture["items"][-1]["data"]["params"] = {"sets.0.distance_two": {"name": "d9", "expression": "side",
                                                                          "value": 1.0}}
        table = size_table.build(capture["parameters"]["user"], ["side"], capture["parameters"]["model"])
        (param,) = translate(capture, table).parameters
        self.assertEqual(param["outcome"], FIXED)

    def test_a_draft_is_left_out(self):
        capture = plate()
        capture["items"].append(dict(finish_item(2, "FilletFeature", TOP, 1.0), type="DraftFeature", name="Draft1",
                                     data={"faces": [], "angle_deg": 3.0}))
        result = translate(capture)
        self.assertEqual([(g["name"], g["cause"]) for g in result.left_out], [("Draft1", causes.FACE_BY_NUMBER)])


def with_sets(kind, *parts):
    """A step of `kind` ("FilletFeature" or "ChamferFeature") with one set per (edge points, size)."""
    capture = plate()
    item = finish_item(len(capture["items"]), kind, parts[0][0], parts[0][1])
    first = item["data"]["sets"][0]
    key = "radius" if kind == "FilletFeature" else "distance"
    item["data"]["sets"] = [dict(first, edges=edges(points), **{key: size}) for points, size in parts]
    capture["items"].append(item)
    return capture


class SizesTest(unittest.TestCase):
    def test_sets_of_different_sizes_on_the_top_and_the_bottom_are_made_one_after_the_other(self):
        for kind, made_type in (("ChamferFeature", FeatureType.CHAMFER), ("FilletFeature", FeatureType.FILLET)):
            with self.subTest(kind):
                result = translate(with_sets(kind, (TOP, 1.0), (BOTTOM, 2.0)))
                self.assertEqual([(f.type, f.face_group, f.dressup_size) for f in finishes(result)],
                                 [(made_type, FaceGroup.TOP, 1.0), (made_type, FaceGroup.BOTTOM, 2.0)])
                self.assertEqual(result.left_out, [])

    def test_sets_of_one_size_that_are_a_group_together_stay_one_feature(self):
        (made,) = finishes(translate(with_sets("ChamferFeature", (TOP[:2], 1.0), (TOP[2:], 1.0))))
        self.assertEqual((made.face_group, made.dressup_size), (FaceGroup.TOP, 1.0))

    def test_sizes_that_follow_two_variables_are_bound_each(self):
        capture = with_sets("ChamferFeature", (TOP, 1.0), (BOTTOM, 2.0))
        capture["parameters"] = {"user": [user("a", "1 mm", 1), user("b", "2 mm", 2)],
                                 "model": [model("d1", "a", 1), model("d2", "b", 2)]}
        capture["items"][-1]["data"]["params"] = {
            "sets.0.distance": {"name": "d1", "expression": "a", "value": 1.0},
            "sets.1.distance": {"name": "d2", "expression": "b", "value": 2.0}}
        table = size_table.build(capture["parameters"]["user"], ["a", "b"], capture["parameters"]["model"])
        result = translate(capture, table)
        self.assertEqual([f.expr.get("dressup_size") for f in finishes(result)], ["a", "b"])

    def test_a_size_that_leaves_too_little_with_the_other_is_left_out(self):
        result = translate(with_sets("FilletFeature", (BOTTOM, 4.0), (TOP, 4.8)))
        self.assertEqual(finishes(result), [])
        self.assertEqual([g["cause"] for g in result.left_out], [causes.NO_ROOM])

    def test_a_part_that_is_not_a_group_or_follows_a_group_that_changes_is_left_out(self):
        cases = {"hand picked": ((TOP[:2], 1.0), (TOP[2:], 2.0)),
                 "side after top": ((TOP, 1.0), (SIDES, 2.0))}
        for name, parts in cases.items():
            with self.subTest(name):
                result = translate(with_sets("ChamferFeature", *parts))
                self.assertEqual(finishes(result), [])
                self.assertEqual([g["cause"] for g in result.left_out], [gap_hints.REFUSED])


class OrderTest(unittest.TestCase):
    def test_the_other_end_after_a_round_is_copied_and_the_same_end_is_not(self):
        both = translate(plate(("FilletFeature", BOTTOM, 2.0), ("ChamferFeature", TOP, 1.0)))
        self.assertEqual([f.face_group for f in finishes(both)], [FaceGroup.BOTTOM, FaceGroup.TOP])
        again = translate(plate(("FilletFeature", TOP, 2.0), ("ChamferFeature", TOP, 1.0)))
        self.assertEqual(len(finishes(again)), 1)
        self.assertEqual(left_out(again, "Chamfer3")["cause"], causes.EDGES_CHANGED)

    def test_two_rounds_that_together_leave_too_little_are_left_out(self):
        result = translate(plate(("FilletFeature", BOTTOM, 4.0), ("FilletFeature", TOP, 4.8)))
        self.assertEqual(len(finishes(result)), 1)
        self.assertEqual(left_out(result, "Fillet3")["cause"], causes.NO_ROOM)

    def test_a_round_after_the_part_changed_is_left_out(self):
        capture = copy.deepcopy(load_capture("hole_through"))
        sketch, hole = capture["items"][2:4]
        capture["items"][2:] = [finish_item(2, "FilletFeature", TOP, 1.0), dict(sketch, index=3),
                                dict(hole, index=4), finish_item(5, "FilletFeature", BOTTOM, 1.0)]
        result = translate(capture)
        self.assertEqual([f.face_group for f in finishes(result)], [FaceGroup.TOP])
        self.assertEqual(left_out(result, "Fillet5")["cause"], causes.EDGES_CHANGED)

    def test_a_recipe_with_rounds_reads_back_the_same(self):
        recipe = translate(plate(("FilletFeature", BOTTOM, 2.0), ("ChamferFeature", TOP, 1.0))).recipe
        self.assertEqual(deserialize(serialize(recipe)).features, recipe.features)


if __name__ == "__main__":
    unittest.main()
