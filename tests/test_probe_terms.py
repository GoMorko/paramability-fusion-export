"""Values that follow sizes along a curve: products of sizes and functions of angle sizes (probe/terms.py), carried
through the motion file into the written formulas."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_follow_or_flag import offending_sizes
from tests.test_translate_sketch_motion import motion_of
from tests.translator_helpers import load_capture, steps_of

from lib.params import size_table
from lib.params.expressions import evaluate
from lib.probe import plan
from lib.probe.fit import Column
from lib.probe.series import fit_series
from lib.probe.terms import Size, fit_terms
from lib.sketch_values.motion import Motion, Stuck, Terms
from lib.translator import translate


def cos(a):
    return math.cos(math.radians(a))


def sin(a):
    return math.sin(math.radians(a))


def cot(a):
    return 1.0 / math.tan(math.radians(a))


def states(now, singles, pairs=()):
    """State 0 at `now`, then one state per value in `singles` (one size changed), then the `pairs`."""
    out = [dict(now)]
    for name, values in singles.items():
        out += [dict(now, **{name: v}) for v in values]
    return out + [dict(now, **p) for p in pairs]


def fitted(value, at, angles=("a",)):
    sizes = [Size(n, n in angles, [s[n] for s in at]) for n in at[0]]
    return fit_terms([value(s) for s in at], sizes)


LEG = states({"leg": 12.0, "a": 120.0}, {"leg": (6.0, 24.0), "a": (75.0, 165.0, 97.5, 142.5)},
             [{"leg": 24.0, "a": 165.0}, {"leg": 6.0, "a": 75.0}])
WALL = states({"wall": 3.0, "h": 50.0, "a": 120.0}, {"wall": (1.5, 6.0), "h": (25.0, 100.0),
                                                      "a": (75.0, 165.0, 97.5, 142.5)},
              [{"wall": 6.0, "a": 165.0}, {"wall": 1.5, "a": 75.0}, {"h": 100.0, "a": 165.0}])


def parts(fit):
    return [(round(c, 9), [tuple(f) for f in factors]) for c, factors in fit.value.parts]


class FitTermsTest(unittest.TestCase):
    def test_a_leg_at_an_angle_is_the_leg_times_the_cosine_and_the_sine(self):
        x = fitted(lambda s: s["leg"] * cos(s["a"]), LEG)
        y = fitted(lambda s: s["leg"] * sin(s["a"]), LEG)
        self.assertEqual(parts(x), [(1.0, [("", "leg", 1.0), ("cos", "a", 1.0)])])
        self.assertEqual(parts(y), [(1.0, [("", "leg", 1.0), ("sin", "a", 1.0)])])

    def test_a_wall_set_back_along_the_half_angle_is_the_wall_times_its_cotangent(self):
        found = fitted(lambda s: s["h"] + s["wall"] * cot(s["a"] / 2), WALL)
        self.assertEqual(parts(found), [(1.0, [("", "h", 1.0)]), (1.0, [("", "wall", 1.0), ("cot", "a", 0.5)])])

    def test_a_product_of_two_lengths(self):
        at = states({"p": 2.0, "q": 3.0}, {"p": (1.0, 4.0), "q": (1.5, 6.0)}, [{"p": 4.0, "q": 6.0},
                                                                             {"p": 1.0, "q": 1.5}])
        found = fitted(lambda s: s["p"] * s["q"] + 1.0, at, ())
        self.assertEqual((parts(found), found.value.const), ([(1.0, [("", "p", 1.0), ("", "q", 1.0)])], 1.0))

    def test_a_value_outside_the_terms_is_not_fitted_and_blames_only_its_own_size(self):
        values = {}
        x = [math.exp(s["a"] / 100.0) + s["leg"] for s in LEG]
        columns = [Column(n, 2, [s[n] for s in LEG], "angle" if n == "a" else "length") for n in ("leg", "a")]
        fit_series(values, {"k": x}, [], columns, lambda at: {n for n in LEG[0] if LEG[at][n] != LEG[0][n]})
        self.assertIsInstance(values["k"], Stuck)
        self.assertEqual(list(values["k"].movers), ["a"])

    def test_a_fit_that_its_states_cannot_check_is_refused(self):
        # Two angle states only: any curve with two numbers goes through them, so nothing checks the fit.
        few = states({"a": 120.0}, {"a": (75.0, 165.0)})
        self.assertEqual(fitted(lambda s: 3 * cot(s["a"] / 2), few).kind, "none")
        # A checking state that disagrees refuses a fit the other states would give.
        x = [s["leg"] * cos(s["a"]) for s in LEG]
        x[-1] += 0.5
        sizes = [Size(n, n == "a", [s[n] for s in LEG]) for n in ("leg", "a")]
        self.assertEqual(fit_terms(x, sizes).kind, "none")

    def test_the_value_round_trips_through_the_motion_file(self):
        value = Terms(2.0, [(1.0, [("", "wall", 1.0), ("cot", "a", 0.5)])], "S")
        back = Motion.from_json(Motion(values={"k": value}).json()).get("k")
        self.assertAlmostEqual(back.value({"wall": 3.0, "a": 120.0}), 2.0 + 3.0 * cot(60.0))
        self.assertEqual(back.names(), ("wall", "a"))


class CurveRowsTest(unittest.TestCase):
    def test_a_curved_size_gets_half_way_rows_and_rows_with_each_partner(self):
        sizes = [{"param": "a", "size": "a", "unit": "deg", "kind": "angle", "value": 120.0, "min": 60.0, "max": 240.0},
                 {"param": "leg", "size": "leg", "unit": "mm", "kind": "length", "value": 12.0, "min": 6.0,
                  "max": 24.0}]
        spans = {"a": {"low": 75.0, "high": 165.0}, "leg": {"low": 6.0, "high": 24.0}}
        rows = plan.check_rows(sizes, ["a"], spans, room=10, partners=["leg"])
        self.assertEqual([r["state"] for r in rows], [
            {"a": 97.5, "leg": 12.0}, {"a": 142.5, "leg": 12.0}, {"a": 75.0, "leg": 6.0}, {"a": 165.0, "leg": 24.0}])
        self.assertEqual(len(plan.check_rows(sizes, ["a"], spans, room=3, partners=["leg"])), 3)


def _tilted():
    """The centred box with an angle size `tilt_deg` (60): its depth is written as 2 * depth_mm * cos(tilt_deg)."""
    capture = load_capture("sketch_rect_centred")
    capture["parameters"]["user"].append({
        "name": "tilt_deg", "expression": "60 deg", "value": math.radians(60.0), "display_value": 60.0, "unit": "deg",
        "comment": "Tilt [50..70]", "is_favorite": False, "kind": "angle", "value_type": "numeric",
        "dependency_parameters": []})
    motion = motion_of("sketch_rect_centred")
    motion.values["1/p0/l0/height"] = Terms(0.0, [(2.0, [("", "depth_mm", 1.0), ("cos", "tilt_deg", 1.0)])],
                                            "Sketch1")
    return capture, motion


class WrittenTest(unittest.TestCase):
    def test_a_curved_value_is_written_as_its_formula_and_its_sizes_stay_free(self):
        capture, motion = _tilted()
        params = capture["parameters"]
        names = [p["name"] for p in params["user"]]
        table = size_table.build(params["user"], names, params["model"])
        result = translate(capture, size_table=table, motion=motion)
        height = steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]["height"]
        env = {n: s["value"] for n, s in result.recipe["sizes"].items() if "value" in s}
        self.assertAlmostEqual(evaluate(height["expr"], env), 60.0, places=6)
        self.assertAlmostEqual(evaluate(height["expr"], dict(env, tilt_deg=50.0)), 120.0 * cos(50.0), places=6)
        self.assertNotIn("tilt_deg", [f["name"] for f in result.loose + result.fixed])
        self.assertEqual(offending_sizes(capture, motion), [])

    def test_a_curved_value_that_reaches_zero_inside_the_range_marks_its_sizes(self):
        capture, motion = _tilted()
        tilt = capture["parameters"]["user"][-1]
        tilt["comment"] = "Tilt [30..120]"
        params = capture["parameters"]
        table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"])
        result = translate(capture, size_table=table, motion=motion)
        self.assertIn("tilt_deg", [f["name"] for f in result.loose + result.fixed])

    def test_a_curved_value_holds_the_size_another_value_cannot_follow(self):
        capture, motion = _tilted()
        motion.values["1/p0/l0/width"] = Stuck(["tilt_deg"], "curve", "Sketch1",
                                               motion.values["1/p0/l0/width"])
        params = capture["parameters"]
        table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"])
        result = translate(capture, size_table=table, motion=motion)
        height = steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]["height"]
        self.assertNotIn("tilt_deg", height["expr"])
        self.assertIn("depth_mm", height["expr"])


if __name__ == "__main__":
    unittest.main()
