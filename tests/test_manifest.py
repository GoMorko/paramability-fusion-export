import copy
import json
import os
import unittest

from tests import context
from lib.package import manifest as mf

PARAMS = [{"name": "width", "label": "Clip width", "unit": "mm"}, {"name": "angle", "unit": "deg"}]
ROWS = [
    {"name": "Small", "values": {"width": 20, "angle": 30}},
    {"name": "Large", "values": {"width": 40, "angle": 30}},
]
FIXTURE = os.path.join(context.ADDIN_DIR, "lib", "schema", "v1.json")


def good():
    return mf.build_value_rows_manifest("Cable clip", "w", PARAMS, ROWS, default_index=1, choice_name="Size",
                                        notes=["2 sizes exported."])


class ManifestTest(unittest.TestCase):
    def test_value_rows_shape(self):
        m = good()
        self.assertEqual(m["rows"][0]["step"], "rows/01.step")
        self.assertEqual(m["rows"][1]["step"], "rows/02.step")
        self.assertNotIn("default", m["rows"][0])
        self.assertTrue(m["rows"][1]["default"])
        self.assertEqual(mf.validate_manifest(m), [])

    def test_step_only_valid(self):
        m = mf.build_step_only_manifest("Part", "w")
        self.assertEqual(m["part"], "part.step")
        self.assertEqual(mf.validate_manifest(m), [])

    def test_recipe_valid_and_checks(self):
        m = {"schema": mf.SCHEMA, "version": 1, "kind": "recipe", "name": "R", "part": "part.step",
             "recipe": "recipe.json", "checks": [{"values": {"width": 20}, "step": "checks/w.step"}]}
        self.assertEqual(mf.validate_manifest(m), [])
        m["checks"][0]["values"] = {}
        self.assertEqual(len(mf.validate_manifest(m)), 1)

    def assert_refused(self, mutate):
        m = good()
        mutate(m)
        self.assertTrue(mf.validate_manifest(m))

    def test_refusals(self):
        self.assert_refused(lambda m: m.update(kind="other"))
        self.assert_refused(lambda m: m.update(name="  "))
        self.assert_refused(lambda m: m.update(name="x" * 121))
        self.assert_refused(lambda m: m.update(upAxis="x"))
        self.assert_refused(lambda m: m.update(writer="x" * 201))
        self.assert_refused(lambda m: m.update(notes=["a"] * 6))
        self.assert_refused(lambda m: m.update(choiceName=""))
        self.assert_refused(lambda m: m.update(rows=m["rows"][:1]))
        self.assert_refused(lambda m: m["rows"][0].update(step="../x.step"))
        self.assert_refused(lambda m: m["rows"][0].update(step="rows/a b.step"))
        self.assert_refused(lambda m: m["rows"][0].update(step="rows/a.obj"))
        self.assert_refused(lambda m: m["rows"][1].update(step="rows/01.step"))
        self.assert_refused(lambda m: m["rows"][1].update(name="small"))
        self.assert_refused(lambda m: m["rows"][0]["values"].update(depth=1))
        self.assert_refused(lambda m: m["rows"][0]["values"].update(width=float("inf")))
        self.assert_refused(lambda m: m["rows"][0]["values"].update(width=2e6))
        self.assert_refused(lambda m: m["rows"][0].update(default=True))
        self.assert_refused(lambda m: m["parameters"].append({"name": "width", "unit": "mm"}))
        self.assert_refused(lambda m: m["parameters"][0].update(unit="cm"))

    def test_all_three_default_absent_is_valid(self):
        m = mf.build_value_rows_manifest("N", "w", PARAMS, ROWS)
        self.assertEqual(mf.validate_manifest(m), [])

    def test_app_fixture_validates_when_present(self):
        if not os.path.exists(FIXTURE):
            self.skipTest("lib/schema/v1.json not copied from the app yet")
        with open(FIXTURE, encoding="utf-8") as f:
            self.assertEqual(mf.validate_manifest(json.load(f)), [])


if __name__ == "__main__":
    unittest.main()
