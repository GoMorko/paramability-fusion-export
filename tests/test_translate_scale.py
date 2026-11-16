"""Scale features written as `scale` steps (lib/translator/bodies/scale.py)."""
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import left_out, load_capture, steps_of

from lib.capture_model import gap_hints
from lib.geometry import rigid
from lib.orca_translate import translate as orca_translate
from lib.params import size_table
from lib.translator import place, translate

SCALE = 2  # timeline index of Scale1 in the fixture


def sized(capture):
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"], "mm")
    return translate(capture, size_table=table)


def marked(result):
    return sorted({d["name"] for d in result.loose + result.fixed + [d for d in result.dropped if d.get("used")]})


def scaled(edit):
    """The fixture with the data of its Scale changed by `edit`."""
    capture = load_capture("scale_uniform")
    edit(capture["items"][SCALE]["data"])
    return capture


def per_axis(data, factors, center=(0.0, 0.0, 0.0)):
    """The Scale rewritten with one factor per axis about `center`, with the body measured as Fusion would."""
    before = data["bodies"][0]["box_before"]
    data.update(uniform=False, factor=None, factors=list(factors), params={})
    data["after"] = [{"box": {k: [c + f * (v - c) for v, c, f in zip(before[k], center, factors)] for k in ("min", "max")},
                      "volume": 8000.0 * factors[0] * factors[1] * factors[2]}]


def scale_step(result):
    return steps_of(result.recipe, "scale")[0]


class WrittenScaleTest(unittest.TestCase):
    def test_a_uniform_factor_follows_its_size(self):
        result = sized(load_capture("scale_uniform"))
        self.assertEqual(marked(result), [])
        self.assertEqual(result.recipe["version"], 17)
        self.assertEqual([s["kind"] for s in result.recipe["features"]], ["extrude", "scale"])
        self.assertEqual((scale_step(result)["factor"], scale_step(result)["point"]), ({"expr": "grow_factor"}, [0.0, 0.0, 0.0]))
        self.assertEqual(check_recipe(result.recipe), [])

    def test_one_factor_per_axis_is_written_as_a_list(self):
        result = translate(scaled(lambda data: per_axis(data, [1.0, 2.0, 0.5])))
        self.assertEqual(scale_step(result)["factor"], [1.0, 2.0, 0.5])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_factors_per_axis_follow_sizes_and_turn_with_a_y_up_design(self):
        def grow_z(data):
            per_axis(data, [1.0, 2.0, 1.5])
            data["params"] = {"factors.2": {"name": "d2", "expression": "grow_factor", "value": 1.5}}
        capture = scaled(grow_z)
        capture["up_axis"] = "y"
        self.assertEqual(scale_step(sized(capture))["factor"], [1.0, {"expr": "grow_factor"}, 2.0])

    def test_a_point_off_the_origin_is_written_and_the_sizes_that_may_move_it_are_marked(self):
        corner = [40.0, 20.0, 10.0]

        def about_corner(data):
            per_axis(data, [1.5, 1.5, 1.5], corner)
            data.update(uniform=True, factor=1.5, factors=None)
            data["point"] = {"entity_type": "BRepVertex", "point": corner, "body": {"token": "t1", "name": "Body1"}}
        capture = scaled(about_corner)
        capture["parameters"]["model"] = capture["parameters"]["model"][:1]
        result = sized(capture)
        self.assertEqual(scale_step(result)["point"], corner)
        self.assertEqual(marked(result), ["plate_h_mm"])

    def test_a_point_in_a_turned_component_is_moved_with_the_part(self):
        capture = scaled(lambda data: data.update(point={"origin": True, "point": [0.0, 0.0, 0.0]}))
        capture["target"]["placement"] = {"frame": {"origin": [5, 0, 0], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}}
        self.assertEqual(scale_step(translate(capture))["point"], [5.0, 0.0, 0.0])

    def test_a_scale_of_a_tool_body_stays_inside_the_tool(self):
        capture = load_capture("combine_join")
        box = {"min": [0, 0, 0], "max": [1, 1, 1]}
        tool = [{"token": "t2", "name": "Body2"}]
        capture["items"][4]["index"] = 5
        capture["items"].insert(4, {
            "index": 4, "name": "Scale1", "type": "ScaleFeature", "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": tool, "data": {
                "input_kind": "bodies", "bodies": [dict(tool[0], box_before=box, volume_before=1.0)],
                "point": {"origin": True, "point": [0.0, 0.0, 0.0]}, "uniform": True, "factor": 1.0, "factors": None,
                "after": [{"box": box, "volume": 1.0}]}})
        features = translate(capture).recipe["features"]
        self.assertEqual([s["kind"] for s in features], ["extrude", "toolBody"])
        self.assertEqual([s["kind"] for s in features[1]["features"]], ["extrude", "scale"])


class LeftOutScaleTest(unittest.TestCase):
    def assert_left_out(self, capture):
        result = translate(capture)
        self.assertEqual(left_out(result)["index"], SCALE)
        self.assertEqual(result.gaps[0]["hint"], gap_hints.HINTS[gap_hints.SCALE])
        self.assertEqual(steps_of(result.recipe, "scale"), [])

    def test_a_scale_of_sketches_is_left_out(self):
        self.assert_left_out(scaled(lambda data: data.update(input_kind="sketches")))

    def test_a_scale_the_measured_body_does_not_agree_with_is_left_out(self):
        self.assert_left_out(scaled(lambda data: data["after"][0].update(volume=20000.0)))
        self.assert_left_out(scaled(lambda data: data["point"].update(point=[40.0, 0.0, 0.0])))

    def test_an_unreadable_point_or_factor_is_left_out(self):
        self.assert_left_out(scaled(lambda data: data.update(point={"kind": "other", "type": "none"})))
        self.assert_left_out(scaled(lambda data: data.update(uniform=None)))

    def test_factors_per_axis_in_a_component_turned_at_an_angle_are_left_out(self):
        capture = scaled(lambda data: per_axis(data, [1.0, 2.0, 0.5]))
        half = 0.5 ** 0.5
        capture["target"]["placement"] = {"frame": {"origin": [0, 0, 0], "x": [half, half, 0], "y": [-half, half, 0],
                                                    "z": [0, 0, 1]}}
        self.assert_left_out(capture)

    def test_a_factor_out_of_the_range_of_the_app_is_left_out(self):
        self.assert_left_out(scaled(lambda data: per_axis(data, [1.0, 1.0, 0.0001])))

    def test_the_orca_copy_leaves_a_scale_out(self):
        result = orca_translate(load_capture("scale_uniform"))
        self.assertEqual([g["cause"] for g in result.left_out], [gap_hints.SCALE])


class PlaceFactorsTest(unittest.TestCase):
    def test_a_turn_off_the_axes_keeps_only_equal_factors(self):
        turn = rigid.Move([[0.6, -0.8, 0.0], [0.8, 0.6, 0.0], [0.0, 0.0, 1.0]])
        equal = {"features": [{"kind": "scale", "factor": [2.0, 2.0, 2.0], "point": [0, 0, 0]}]}
        self.assertEqual(place.place(equal, turn)["features"][0]["factor"], [2.0, 2.0, 2.0])
        with self.assertRaises(ValueError):
            place.place({"features": [{"kind": "scale", "factor": [1.0, 2.0, 2.0]}]}, turn)


if __name__ == "__main__":
    unittest.main()
