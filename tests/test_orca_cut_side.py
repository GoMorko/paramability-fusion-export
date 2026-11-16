"""Cuts and holes of the Orca copy against the part the copy has built: a one way cut through all goes to the side
that holds material, and a cut or hole that meets no material is left out (Orca stops the whole rebuild on it)."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture

from lib.orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType
from lib.orca_translate import causes, translate
from lib.orca_translate.solid import ADD, CUT, Prism, Solid


def _lines(points):
    return [{"kind": "line", "start": list(a), "end": list(b)} for a, b in zip(points, points[1:] + points[:1])]


def _rect(u0, v0, u1, v1):
    return _lines([(u0, v0), (u1, v0), (u1, v1), (u0, v1)])


# An L: a wall along x (y 0..4) and a leg along y (x 0..4), 10 mm high.
L_OUTLINE = _lines([(0, 0), (40, 0), (40, 4), (4, 4), (4, 20), (0, 20)])
# A plane at y = 4 facing +y, as Fusion gives a sketch on the XZ plane of a Z up design (x runs to -x).
WALL_FRAME = {"origin": [0, 4, 0], "x": [-1, 0, 0], "y": [0, 0, 1], "z": [0, 1, 0]}


def l_part(cut_curves, positive=True, frame=WALL_FRAME):
    """The L extruded 10 mm, then a one way cut through all of `cut_curves` on `frame`, its end not measured (a cut
    through all makes no end face). The part's box holds material on both sides of the cut's plane."""
    capture = copy.deepcopy(load_capture("extrude_cut_through_one"))
    base, cut = capture["items"][1]["data"], capture["items"][3]["data"]
    base["profiles"][0]["loops"] = [{"outer": True, "curves": L_OUTLINE}]
    cut["profiles"][0]["frame"] = copy.deepcopy(frame)
    cut["profiles"][0]["loops"] = [{"outer": True, "curves": cut_curves}]
    cut["side_one"]["positive"] = positive
    cut["end_offset"] = None
    box = {"min": [0.0, 0.0, 0.0], "max": [40.0, 20.0, 10.0]}
    cut["target_box_before"] = copy.deepcopy(box)
    capture["target"]["box"] = box
    return capture


def cut_of(result):
    return [f for f in result.recipe.features if f.type == FeatureType.EXTRUDE][-1]


class CutSideTest(unittest.TestCase):
    def test_a_cut_stored_toward_empty_space_goes_through_the_wall_behind_it(self):
        # The slot lies over x 10..30, z 2..8: only the wall (y 0..4) is there, behind the plane.
        result = translate(l_part(_rect(-30, 2, -10, 8)))
        cut = cut_of(result)
        self.assertEqual((cut.mode, cut.extrude_end, cut.flip, cut.distance),
                         (BooleanMode.CUT, ExtrudeEnd.BLIND, True, 1000.0))
        self.assertEqual(len(result.notes), 1)
        self.assertEqual(result.left_out, [])

    def test_a_cut_stored_toward_material_keeps_its_direction(self):
        result = translate(l_part(_rect(-30, 2, -10, 8), positive=False))
        cut = cut_of(result)
        self.assertEqual((cut.extrude_end, cut.flip), (ExtrudeEnd.BLIND, True))
        self.assertEqual(result.notes, [])

    def test_a_cut_that_meets_no_material_is_left_out(self):
        # Over x 10..30, z 12..18: above the part on both sides of the plane.
        result = translate(l_part(_rect(-30, 12, -10, 18)))
        self.assertEqual([(g["name"], g["cause"]) for g in result.left_out], [("Extrude2", causes.MISSES_PART)])
        self.assertEqual([f.mode for f in result.recipe.features if f.type == FeatureType.EXTRUDE],
                         [BooleanMode.NEW])

    def test_a_cut_through_the_hole_of_a_ring_is_left_out(self):
        capture = copy.deepcopy(load_capture("extrude_ring"))
        cut = copy.deepcopy(capture["items"][-1])
        ring = cut["data"]["profiles"][0]
        inner = next(loop for loop in ring["loops"] if not loop.get("outer"))
        r = inner["curves"][0]["radius"]
        centre = inner["curves"][0]["center"]
        cut.update(index=len(capture["items"]), name="Bore")
        cut["data"].update(operation="cut", extent_type="one", end_offset=None, symmetric=None, side_two=None,
                           side_one={"kind": "throughAll", "positive": True, "taper_deg": 0.0},
                           target_box_before=copy.deepcopy(capture["target"]["box"]))
        ring["loops"] = [{"outer": True, "curves": [{"kind": "circle", "center": centre, "radius": r / 2}]}]
        capture["items"].append(cut)
        result = translate(capture)
        self.assertEqual([g["name"] for g in result.left_out], ["Bore"])

    def test_a_hole_that_misses_the_part_is_left_out_and_one_that_meets_it_is_kept(self):
        capture = copy.deepcopy(load_capture("hole_three_points"))
        hole = capture["items"][-1]["data"]
        kept = len(hole["positions"])
        hole["positions"].append([500.0, 500.0, hole["positions"][0][2]])
        hole["end_points"] = []
        result = translate(capture)
        self.assertEqual(sum(1 for f in result.recipe.features if f.type == FeatureType.HOLE), kept)
        self.assertEqual(len(result.notes), 1)
        hole["positions"] = hole["positions"][-1:]
        self.assertEqual([g["cause"] for g in translate(capture).left_out], [causes.MISSES_PART])


class SolidTest(unittest.TestCase):
    FLAT = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}

    def test_a_thin_wall_far_along_a_long_tool_is_met(self):
        solid = Solid()
        solid.add(ADD, Prism(self.FLAT, [_rect(0, 0, 10, 10)], 500.0, 500.2))
        self.assertTrue(solid.meets(Prism(self.FLAT, [_rect(2, 2, 3, 3)], 0.0, math.inf)))
        self.assertFalse(solid.meets(Prism(self.FLAT, [_rect(2, 2, 3, 3)], -math.inf, 0.0)))

    def test_a_cut_away_region_holds_no_material(self):
        solid = Solid()
        solid.add(ADD, Prism(self.FLAT, [_rect(0, 0, 10, 10)], 0.0, 5.0))
        solid.add(CUT, Prism(self.FLAT, [_rect(0, 0, 5, 10)], -math.inf, math.inf))
        side = {"origin": [0, 5, 2.5], "x": [0, 0, 1], "y": [0, 1, 0], "z": [1, 0, 0]}
        self.assertFalse(solid.meets(Prism(side, [_rect(-1, -1, 1, 1)], -math.inf, 4.9)))
        self.assertTrue(solid.meets(Prism(side, [_rect(-1, -1, 1, 1)], -math.inf, 5.1)))


if __name__ == "__main__":
    unittest.main()
