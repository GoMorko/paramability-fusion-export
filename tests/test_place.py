import copy
import glob
import json
import os
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe, load_schema
from tests.translator_helpers import FIXTURES, assert_schema_ok, load_capture, steps_of, translate_fixture

from lib.translator import CaptureError, translate
from lib.translator import place
from lib.translator.values import Sized

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
        turned = place.place(sample_recipe(), place.TURN_Z_UP)["features"][2]["origin"]
        self.assertEqual(json.dumps(turned), "[1.0, -3.0, 2.0]")
        flat = {"features": [{"kind": "hole", "origin": [1, 2, 0]}]}
        self.assertEqual(json.dumps(place.place(flat, place.TURN_Z_UP)["features"][0]["origin"]), "[1.0, 0.0, 2.0]")

    def test_input_recipe_is_kept(self):
        recipe = translate_fixture("extrude_plate").recipe
        before = copy.deepcopy(recipe)
        place.place(recipe, place.TURN_Z_UP)
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
            if kind in place.NOT_WRITTEN:
                continue
            listed = {tuple(p) for p in place.POSITIONS.get(kind, [])} | {tuple(p) for p in place.DIRECTIONS.get(kind, [])}
            self.assertEqual(paths, listed, kind)
            self.assertFalse({tuple(p) for p in place.POSITIONS.get(kind, [])} & {tuple(p) for p in place.DIRECTIONS.get(kind, [])})
        self.assertEqual(kinds, set(place.POSITIONS) | set(place.DIRECTIONS) | set(place.NOT_WRITTEN))


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
        turned = place.place(recipe, place.TURN_Z_UP)
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
        self.assertEqual(place.place(place.place(recipe, place.TURN_Z_UP), place.TURN_Z_UP.inverse()), recipe)


def hole_at(*origin, direction=(0.0, 0.0, 1.0)):
    return {"features": [{"kind": "hole", "origin": list(origin), "direction": list(direction), "diameter": 4}]}


def sized(expr, n, *reads):
    value = Sized(expr=expr)
    value.n, value.reads = n, reads
    return value


QUARTER_ABOUT_X = {"origin": [10, 0, 0], "x": [1, 0, 0], "y": [0, 0, 1], "z": [0, -1, 0]}


class MoveTest(unittest.TestCase):
    def test_a_moved_part_keeps_plain_formulas(self):
        frame = {"origin": [100, 50, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        recipe = hole_at(1, 2, sized("0.5 * h", 16, "h"))
        out = place.place(recipe, place.from_frame(frame))["features"][0]["origin"]
        self.assertEqual(out, [101.0, 52.0, {"expr": "0.5 * h"}])
        self.assertEqual(out[2].reads, ("h",))

    def test_a_turned_part_writes_affine_formulas_and_directions_ignore_the_move(self):
        move = place.from_frame(QUARTER_ABOUT_X)
        out = place.place(hole_at(1, 2, sized("h", 30, "h"), direction=(0.0, 0.0, 1.0)), move)["features"][0]
        self.assertEqual(out["origin"], [11.0, {"expr": "-h"}, 2.0])
        self.assertEqual(out["direction"], [0.0, -1.0, 0.0])

    def test_move_then_turn_is_one_pass_and_inverts(self):
        move = place.from_frame(QUARTER_ABOUT_X).then(place.TURN_Z_UP)
        recipe = hole_at(1, 2, 3)
        out = place.place(recipe, move)["features"][0]["origin"]
        self.assertEqual(out, [11.0, -2.0, -3.0])
        self.assertEqual(place.place(place.place(recipe, move), move.inverse()), recipe)

    def test_identity_returns_a_copy(self):
        recipe = hole_at(1, 2, 3)
        out = place.place(recipe, place.move_for({"up_axis": "z", "target": {}}))
        self.assertEqual(out, recipe)
        self.assertIsNot(out, recipe)

    def test_rounding_noise_in_a_turn_is_snapped(self):
        frame = {"origin": [0, 0, 0], "x": [6e-17, 1, 0], "y": [-1, 6e-17, 0], "z": [0, 0, 1]}
        out = place.place(hole_at(5, 0, 0), place.from_frame(frame))["features"][0]["origin"]
        self.assertEqual(out, [0.0, 5.0, 0.0])

    def test_frames_that_are_not_a_rotation_are_named(self):
        good = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        self.assertIsNone(place.frame_problem(good))
        self.assertIn("scaled", place.frame_problem({**good, "x": [2, 0, 0]}))
        self.assertIn("mirrored", place.frame_problem({**good, "z": [0, 0, -1]}))
        self.assertIn("numbers", place.frame_problem({**good, "origin": [0, 0]}))


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
            self.assertEqual(place.place(turned.recipe, place.TURN_Z_UP.inverse()), flat.recipe, name)
        self.assertGreater(checked, 5)


if __name__ == "__main__":
    unittest.main()
