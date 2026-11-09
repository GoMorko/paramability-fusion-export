import copy
import glob
import json
import os
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe, load_schema
from tests.translator_helpers import FIXTURES, assert_schema_ok, load_capture, steps_of, translate_fixture

from lib.translator import CaptureError, translate
from lib.translator import zup

POS_VEC_REFS = ("#/$defs/Pos3", "#/$defs/Vec3")
TWO_D_ONLY = ("#/$defs/SketchLoop",)


def schema_paths(node, defs, trail=(), seen=()):
    """Property paths under `node` that end in a Pos3 or Vec3. "[]" marks a list."""
    found = set()
    if not isinstance(node, dict):
        return found
    ref = node.get("$ref")
    if ref in POS_VEC_REFS:
        return {trail}
    if ref in TWO_D_ONLY or (ref and ref in seen):
        return found
    if ref:
        return schema_paths(defs[ref.split("/")[-1]], defs, trail, seen + (ref,))
    for branch in node.get("anyOf", []):
        found |= schema_paths(branch, defs, trail, seen)
    for name, sub in node.get("properties", {}).items():
        found |= schema_paths(sub, defs, trail + (name,), seen)
    if "items" in node:
        found |= schema_paths(node["items"], defs, trail + ("[]",), seen)
    return found


def with_up(name, axis):
    capture = load_capture(name)
    capture["up_axis"] = axis
    return capture


class TurnTest(unittest.TestCase):
    def test_plate_drawn_on_xz(self):
        result = translate_fixture("zup_plate_yup")
        self.assertIsNone(result.refusal)
        assert_schema_ok(self, result.recipe)
        step = steps_of(result.recipe, "extrude")[0]
        self.assertEqual(step["sketch"]["on"], {"origin": [5.0, -3.0, 2.0], "normal": [0.0, 0.0, 1.0], "xDir": [1.0, 0.0, 0.0]})
        self.assertEqual(step["sketch"]["outer"], {"kind": "rect", "center": [20.0, 10.0], "width": 40.0, "height": 20.0})

    def test_z_up_capture_is_not_turned(self):
        capture = load_capture("zup_plate_yup")
        capture["up_axis"] = "z"
        on = steps_of(translate(capture).recipe, "extrude")[0]["sketch"]["on"]
        self.assertEqual(on["origin"], [5.0, 2.0, 3.0])

    def test_no_negative_zero(self):
        self.assertEqual(json.dumps(zup.turn_point([1, 2, 0])), "[1, 0.0, 2]")

    def test_input_recipe_is_kept(self):
        recipe = translate_fixture("extrude_plate").recipe
        before = copy.deepcopy(recipe)
        zup.turn_z_up(recipe)
        self.assertEqual(recipe, before)


class FieldTableTest(unittest.TestCase):
    def test_table_matches_every_position_and_direction_in_the_schema(self):
        schema = load_schema()
        defs = schema["$defs"]
        steps = schema["properties"]["features"]["items"]["anyOf"]
        kinds = set()
        for step in steps:
            kind = step["properties"]["kind"]["const"]
            kinds.add(kind)
            paths = schema_paths(step, defs)
            if kind in zup.FIELDS:
                self.assertEqual(paths, {tuple(p) for p in zup.FIELDS[kind]}, kind)
            else:
                self.assertIn(kind, zup.NOT_WRITTEN)
        self.assertEqual(kinds, set(zup.FIELDS) | set(zup.NOT_WRITTEN))


def sample_recipe():
    placement = {"origin": [1.0, 2.0, 3.0], "normal": [0.0, 1.0, 0.0], "xDir": [1.0, 0.0, 0.0]}
    near = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    return {"schema": "paramability.recipe", "version": 12, "features": [
        {"id": "e", "kind": "extrude", "combine": "new", "extent": "oneSide", "distance": 5,
         "sketch": {"on": dict(placement), "outer": {"kind": "circle", "center": [1.0, 2.0], "radius": 3.0}}},
        {"id": "r", "kind": "revolve", "combine": "add", "axis": {"point": [0, 0], "dir": [0, 1]},
         "sketch": {"on": dict(placement), "outer": {"kind": "circle", "center": [1.0, 2.0], "radius": 3.0}}},
        {"id": "h", "kind": "hole", "origin": [1.0, 2.0, 3.0], "direction": [0.0, -1.0, 0.0], "diameter": 4, "depth": 5},
        {"id": "f", "kind": "round", "size": 1, "edges": {"near": near}},
        {"id": "b", "kind": "bevel", "size": 1, "edges": {"near": near}, "sizeOn": [0.0, 1.0, 0.0]},
        {"id": "s", "kind": "shell", "thickness": 1, "openFaces": {"near": near}},
        {"id": "p", "kind": "pattern", "of": ["h"], "linear": {"dir": [1.0, 0.0, 0.0], "count": 2, "step": 5},
         "linear2": {"dir": [0.0, 0.0, 1.0], "count": 2, "step": 5}},
        {"id": "q", "kind": "pattern", "of": ["h"], "polar": {"axisPoint": [1.0, 2.0, 3.0], "axis": [0.0, 1.0, 0.0], "count": 3}},
        {"id": "m", "kind": "mirror", "of": ["h"], "plane": {"origin": [1.0, 2.0, 3.0], "normal": [0.0, 0.0, 1.0]}},
    ]}


class SampleTurnTest(unittest.TestCase):
    def test_every_written_field_turns_and_nothing_else(self):
        recipe = sample_recipe()
        assert_schema_ok(self, recipe)
        turned = zup.turn_z_up(recipe)
        assert_schema_ok(self, turned)
        by_id = {s["id"]: s for s in turned["features"]}
        self.assertEqual(by_id["e"]["sketch"]["on"], {"origin": [1.0, -3.0, 2.0], "normal": [0.0, 0.0, 1.0], "xDir": [1.0, 0.0, 0.0]})
        self.assertEqual(by_id["e"]["sketch"]["outer"], recipe["features"][0]["sketch"]["outer"])
        self.assertEqual(by_id["r"]["axis"], {"point": [0, 0], "dir": [0, 1]})
        self.assertEqual(by_id["h"]["origin"], [1.0, -3.0, 2.0])
        self.assertEqual(by_id["h"]["direction"], [0.0, 0.0, -1.0])
        self.assertEqual(by_id["f"]["edges"]["near"], [[1.0, -3.0, 2.0], [4.0, -6.0, 5.0]])
        self.assertEqual(by_id["b"]["sizeOn"], [0.0, 0.0, 1.0])
        self.assertEqual(by_id["s"]["openFaces"]["near"], [[1.0, -3.0, 2.0], [4.0, -6.0, 5.0]])
        self.assertEqual(by_id["p"]["linear"]["dir"], [1.0, 0.0, 0.0])
        self.assertEqual(by_id["p"]["linear2"]["dir"], [0.0, -1.0, 0.0])
        self.assertEqual(by_id["q"]["polar"], {"axisPoint": [1.0, -3.0, 2.0], "axis": [0.0, 0.0, 1.0], "count": 3})
        self.assertEqual(by_id["m"]["plane"], {"origin": [1.0, -3.0, 2.0], "normal": [0.0, -1.0, 0.0]})
        self.assertEqual(by_id["p"]["of"], ["h"])

    def test_turning_back_gives_the_original(self):
        recipe = sample_recipe()
        self.assertEqual(zup.turn_back(zup.turn_z_up(recipe)), recipe)


class FixturesTest(unittest.TestCase):
    def test_every_fixture_turns_and_returns(self):
        checked = 0
        for path in sorted(glob.glob(os.path.join(FIXTURES, "*.json"))):
            name = os.path.splitext(os.path.basename(path))[0]
            if name.startswith("schema_"):
                continue
            try:
                flat = translate(with_up(name, "z"))
                turned = translate(with_up(name, "y"))
            except CaptureError:
                continue
            if flat.recipe is None:
                self.assertIsNone(turned.recipe, name)
                continue
            checked += 1
            self.assertEqual(check_recipe(turned.recipe), [], name)
            self.assertEqual(zup.turn_back(turned.recipe), flat.recipe, name)
        self.assertGreater(checked, 5)


if __name__ == "__main__":
    unittest.main()
