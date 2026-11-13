"""Outlines whose corners turn with an angle size: the range is cut where the outline would cross itself
(sketch_crossings.order_ranges)."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_translate_crossings import capture_with, line, user

from lib.params import size_table
from lib.sketch_values.motion import Motion, Terms
from lib.translator import translate


def angle(name, deg):
    return {"name": name, "expression": "%g deg" % deg, "value": math.radians(deg), "display_value": deg,
            "unit": "deg", "comment": "", "is_favorite": False, "kind": "angle", "value_type": "numeric",
            "dependency_parameters": []}


def turned(*legs):
    """`Terms` of a sum of `(coefficient, length size or "", function)` products with the angle `a_deg`."""
    return Terms(0.0, [(k, ([("", leg, 1.0)] if leg else []) + [(f, "a_deg", 1.0)]) for k, leg, f in legs],
                 "Sketch1")


def run(capture, motion):
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"])
    return translate(capture, size_table=table, motion=motion)


class CrossingCutTest(unittest.TestCase):
    def test_an_outline_that_crosses_itself_in_a_corner_of_the_ranges_cuts_them(self):
        # The right side sits at (p - q) * sin(a): with p at its minimum and q at its maximum it passes the left side.
        corners = [(0, 0), (9.0, 0), (9.0, 5), (-2, 5)]
        capture = capture_with([line(corners[i], corners[(i + 1) % 4], "e%d" % i) for i in range(4)], "p_mm", 14.0)
        capture["parameters"]["user"] += [user("q_mm", 5.0), angle("a_deg", 90.0)]
        side = turned((1.0, "p_mm", "sin"), (-1.0, "q_mm", "sin"))
        result = run(capture, Motion({"1/p0/l0/points.1.0": side, "1/p0/l0/points.2.0": side}))
        sizes = result.recipe.get("sizes", {})
        self.assertEqual((sorted(sizes), result.loose, result.fixed), (["a_deg", "p_mm", "q_mm"], [], []))
        self.assertGreater(sizes["p_mm"]["min"], sizes["q_mm"]["max"])
        self.assertEqual(sorted(c["name"] for c in result.cuts), ["p_mm", "q_mm"])
