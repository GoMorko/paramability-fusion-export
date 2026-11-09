"""Picks on the inner walls of a shell, on edges where the walls of two steps cross and on tapered walls, and the
order of the outlines of one join extrude, on the sized filter tray (80 x 60 x 32, shell 2 mm open at the top)."""
import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, steps_of
from tests.test_translate_follow import HEIGHT, at, fixed_names, tab, tray
from tests.test_translate_sized import CUBE, H, param, run

BIG = {"FilterBox___height__contains_CeramicMedium": 2.5, CUBE: 30, "wall_mm": 3}


def _round(points, index=3, name="Fillet9"):
    return {"index": index, "name": name, "type": "FilletFeature", "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}],
            "data": {"sets": [{"kind": "constant", "radius": 0.5, "continuity": "tangent", "input_kinds": ["edge"],
                               "edges": [{"token": "e%d" % n, "closed": False, "points": [p]}
                                         for n, p in enumerate(points)]}]}}


def _square(x0, y0, x1, y1):
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return [{"kind": "line", "start": corners[n], "end": corners[(n + 1) % 4]} for n in range(4)]


def _profile(curves, z=0.0):
    frame = {"origin": [0, 0, z], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
    return {"sketch": "Sketch9", "frame": frame, "loops": [{"outer": True, "curves": curves}]}


def _notch(depth_expr):
    """A cut 5 x wall deep from a sketch on the tray top across the front wall."""
    item = tab(side_one={"kind": "distance", "distance": -10.0, "taper_deg": 0.0}, index=3)
    item["name"] = "Notch"
    item["data"].update(operation="cut", profiles=[_profile(_square(30, -1, 50, 5), z=32)], end_offset=-10.0,
                        params={"side_one.distance": param("d40", depth_expr, -10.0)})
    return item


def _picked(result):
    return steps_of(result.recipe, "round")[-1]["edges"]["near"]


def _worked_out(result, table, point, sizes=None):
    return [at(result.recipe, table, c, sizes) for c in point]


class ShellInnerWallTest(unittest.TestCase):
    def test_inner_corner_and_floor_edges_follow_the_wall_and_height(self):
        result, table = run(tray(lambda c: c["items"].append(_round([[2, 2, 16], [40, 2, 2]])), keep=[0, 1, 2]))
        self.assertEqual(result.fixed, [])
        corner, floor = _picked(result)
        self.assertEqual(corner, [{"expr": "wall_mm"}, {"expr": "wall_mm"}, {"expr": "0.5 * " + HEIGHT}])
        self.assertEqual(_worked_out(result, table, floor, BIG), [40, 3, 3])
        assert_schema_ok(self, result.recipe)

    def test_an_extrude_from_the_inner_floor_follows_the_wall(self):
        start = {"kind": "fromEntity", "plane": {"point": [40, 30, 2], "normal": [0, 0, 1]}, "entity_type": "BRepFace",
                 "face_point": [40, 30, 2]}

        def edit(capture):
            post = tab(start=start, side_one={"kind": "distance", "distance": 5.0, "taper_deg": 0.0})
            post["data"].update(profiles=[_profile(_square(30, 20, 40, 30))], end_offset=7.0)
            capture["items"].append(post)
        result, _ = run(tray(edit, keep=[0, 1, 2]))
        self.assertEqual(result.fixed, [])
        self.assertEqual(steps_of(result.recipe, "extrude")[1]["sketch"]["on"]["origin"], [0, 0, {"expr": "wall_mm"}])


class CrossingTest(unittest.TestCase):
    def test_a_notch_floor_crossing_the_outer_and_inner_wall_follows_both(self):
        def edit(capture):
            capture["items"] += [_notch("-wall_mm * 5"), _round([[40, 0, 22], [40, 2, 22]], index=4)]
        result, table = run(tray(edit, keep=[0, 1, 2]))
        self.assertEqual(result.fixed, [])
        outer, inner = _picked(result)
        self.assertEqual(_worked_out(result, table, outer, BIG), [40, 0, 17])
        self.assertEqual(_worked_out(result, table, inner, BIG), [40, 3, 17])


class TaperTest(unittest.TestCase):
    def _tapered(self, taper_expr):
        lean = math.sin(math.radians(5))
        inset = 10 * math.tan(math.radians(5))

        def edit(capture):
            item = tab(side_one={"kind": "distance", "distance": 10.0, "taper_deg": -5.0})
            item["data"].update(end_offset=10.0, side_leans=[lean], params={
                "side_one.distance": param("d41", "wall_mm * 5", 10.0),
                "side_one.taper_deg": param("d42", taper_expr, -5.0)})
            capture["items"] += [item, _round([[85, inset, 10]], index=11)]
            capture["parameters"]["user"].append({
                "name": "taper_deg", "expression": "5 deg", "value": math.radians(5), "unit": "deg", "comment": "",
                "is_favorite": True, "value_type": "numeric", "dependency_parameters": [], "dependent_parameters": [],
                "kind": "angle", "display_value": 5.0})
        return run(tray(edit, keep=[0, 1]), ticked=[H, CUBE, "wall_mm", "taper_deg"])

    def test_the_far_outline_of_a_tapered_extrude_follows_its_length(self):
        result, table = self._tapered("-5 deg")
        self.assertEqual(result.fixed, [])
        point = _worked_out(result, table, _picked(result)[0], BIG)
        self.assertEqual(point, [85, round(15 * math.tan(math.radians(5)), 6), 15])

    def test_a_pick_on_a_wall_whose_taper_follows_a_size_follows_it(self):
        result, table = self._tapered("-taper_deg")
        self.assertEqual(result.fixed, [])
        point = _worked_out(result, table, _picked(result)[0], dict(BIG, taper_deg=8))
        self.assertEqual(point, [85, round(15 * math.tan(math.radians(8)), 6), 15])


class OutlineOrderTest(unittest.TestCase):
    def test_an_outline_that_touches_only_a_later_one_waits_for_it(self):
        def edit(capture):
            item = tab(side_one={"kind": "distance", "distance": 10.0, "taper_deg": 0.0})
            item["data"].update(end_offset=10.0, profiles=[_profile(_square(90, 0, 100, 10)),
                                                           _profile(_square(78, 0, 90, 5))])
            capture["items"].append(item)
        result, _ = run(tray(edit, keep=[0, 1]))
        firsts = [step["sketch"]["outer"] for step in steps_of(result.recipe, "extrude")[1:]]
        self.assertEqual([outline["center"][0] for outline in firsts], [84, 95])

    def test_outlines_that_share_a_curve_make_one_step(self):
        def edit(capture):
            item = tab(side_one={"kind": "distance", "distance": 10.0, "taper_deg": 0.0})
            ring = [{"kind": "arc", "start": [p, 30], "end": [-p + 80, 30], "mid": [40, 30 + m], "center": [40, 30],
                     "radius": r} for r in (10, 5) for p, m in ((30 if r == 10 else 35, r), (30 if r == 10 else 35, -r))]
            top = _profile([ring[0], ring[2], {"kind": "line", "start": [30, 30], "end": [35, 30]},
                            {"kind": "line", "start": [45, 30], "end": [50, 30]}])
            bottom = _profile([ring[1], ring[3], {"kind": "line", "start": [30, 30], "end": [35, 30]},
                               {"kind": "line", "start": [45, 30], "end": [50, 30]}])
            item["data"].update(end_offset=10.0, profiles=[top, bottom])
            capture["items"].append(item)
        result, _ = run(tray(edit, keep=[0, 1]))
        added = steps_of(result.recipe, "extrude")[1:]
        self.assertEqual(len(added), 1)
        self.assertEqual(len(added[0]["sketch"]["inner"]), 1)


if __name__ == "__main__":
    unittest.main()
