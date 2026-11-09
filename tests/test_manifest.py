import copy
import json
import os
import unittest

from tests import context
from lib.package import manifest as mf
from tests.schema_check import load_schema, validate

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


PACKAGE_SCHEMA = os.path.join(context.ADDIN_DIR, "lib", "schema", "paramability.recipePackage.v1.schema.json")
LISTED = [{"name": "wall", "label": "wall", "value": 2, "unit": "mm", "comment": "Wall [1..6]"},
          {"name": "outer", "label": "outer", "value": 84, "unit": "mm", "expr": "wall * 2"}]


class SchemaCopyTest(unittest.TestCase):
    """The writers' manifests fit the app's schema copy, so a cap that drifts from the app is noticed here."""

    def setUp(self):
        self.schema = load_schema(PACKAGE_SCHEMA)

    def test_every_manifest_kind_fits_the_schema(self):
        manifests = [
            good(),
            mf.build_step_only_manifest("Part", "w", parameters=LISTED, notes=["Added as a fixed shape."]),
            mf.build_recipe_manifest(
                "Part", "w", notes=["1 step copied."], parameters=LISTED,
                checks=[{"values": {"wall": 4}, "step": "checks/01.step"}],
                fixed=[{"name": "gap", "reason": "gap stays fixed for now."}]),
        ]
        for manifest in manifests:
            self.assertEqual(mf.validate_manifest(manifest), [])
            self.assertEqual(validate(manifest, self.schema), [], manifest["kind"])

    def test_a_long_comment_is_refused_by_both(self):
        manifest = mf.build_step_only_manifest("Part", "w", parameters=[
            {"name": "wall", "value": 2, "unit": "mm", "comment": "x" * (mf.MAX_PARAMETER_COMMENT + 1)}])
        self.assertTrue(mf.validate_manifest(manifest))
        self.assertTrue(validate(manifest, self.schema))


if __name__ == "__main__":
    unittest.main()
