import copy
import json
import os
import unittest

from tests import context  # noqa: F401
from lib.package import manifest as mf
from tests.schema_check import load_schema, validate

PARAMS = [{"name": "width", "label": "Clip width", "unit": "mm"}, {"name": "angle", "unit": "deg"}]
ROWS = [
    {"name": "Small", "values": {"width": 20, "angle": 30}},
    {"name": "Large", "values": {"width": 40, "angle": 30}},
]
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema", "v1.json")


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
            self.skipTest("tests/schema/v1.json not copied from the app yet")
        with open(FIXTURE, encoding="utf-8") as f:
            self.assertEqual(mf.validate_manifest(json.load(f)), [])


SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema")
PACKAGE_SCHEMA = os.path.join(SCHEMA_DIR, "paramability.recipePackage.v1.schema.json")
PACKAGE_SCHEMA_V2 = os.path.join(SCHEMA_DIR, "paramability.recipePackage.v2.schema.json")
GAPS_SCHEMA = os.path.join(SCHEMA_DIR, "paramability.recipeGaps.v3.schema.json")
LISTED = [{"name": "wall", "label": "wall", "value": 2, "unit": "mm", "comment": "Wall [1..6]"},
          {"name": "outer", "label": "outer", "value": 84, "unit": "mm", "expr": "wall * 2"}]


def parts_manifest(names=("Tray", "Cover")):
    parts = [{"name": name, "step": mf.part_step_path(i), "recipe": mf.part_recipe_path(i),
              "loose": [{"name": "wall", "reason": "%s: wall may give unexpected results: it moves a joint." % name}]}
             for i, name in enumerate(names, start=1)]
    parts[-1] = {"name": names[-1], "step": mf.part_step_path(len(names)), "note": "Added as a fixed shape."}
    return mf.build_parts_manifest(
        "Planter", "w", parts, notes=["2 parts, 1 size."], parameters=LISTED,
        fixed=[{"name": "gap", "reason": "gap stays fixed for now."}])


class PartsManifestTest(unittest.TestCase):
    def test_a_parts_manifest_follows_the_rules_and_the_schema_copy(self):
        manifest = parts_manifest()
        self.assertEqual(mf.validate_manifest(manifest), [])
        self.assertEqual(validate(manifest, load_schema(PACKAGE_SCHEMA)), [])
        self.assertEqual(manifest["parts"][0]["recipe"], "parts/01/recipe.json")
        self.assertNotIn("recipe", manifest["parts"][1])
        self.assertNotIn("loose", manifest["parts"][1])

    def test_part_names_must_differ_ignoring_case(self):
        manifest = parts_manifest(("Tray", "TRAY"))
        self.assertTrue(mf.validate_manifest(manifest))

    def test_the_number_of_parts_and_the_name_length_are_limited_by_both_the_rules_and_the_schema(self):
        schema = load_schema(PACKAGE_SCHEMA)
        for what, edit in (
                ("none", lambda m: m.update(parts=[])),
                ("too many", lambda m: m.update(parts=[dict(m["parts"][0], name="P%d" % i,
                                                            step=mf.part_step_path(i), recipe=None)
                                                       for i in range(1, mf.MAX_PARTS + 2)])),
                ("long name", lambda m: m["parts"][0].update(name="x" * (mf.MAX_PART_NAME + 1)))):
            manifest = parts_manifest()
            edit(manifest)
            with self.subTest(what):
                self.assertTrue(mf.validate_manifest(manifest))
                self.assertTrue(validate(manifest, schema))

    def test_two_parts_cannot_share_a_file(self):
        manifest = parts_manifest()
        manifest["parts"][1]["step"] = manifest["parts"][0]["step"]
        self.assertTrue(mf.validate_manifest(manifest))


class GapsManifestTest(unittest.TestCase):
    def recipe(self, **options):
        return mf.build_recipe_manifest("Part", "w", notes=["1 step copied."], **options)

    def test_a_recipe_that_names_a_gaps_file_is_version_2_and_one_without_stays_version_1(self):
        with_gaps, without = self.recipe(gaps="gaps.json"), self.recipe()
        self.assertEqual((with_gaps["version"], with_gaps["gaps"]), (2, "gaps.json"))
        self.assertEqual((without["version"], "gaps" in without), (1, False))
        for manifest, schema in ((with_gaps, PACKAGE_SCHEMA_V2), (without, PACKAGE_SCHEMA)):
            self.assertEqual(mf.validate_manifest(manifest), [])
            self.assertEqual(validate(manifest, load_schema(schema)), [])

    def test_a_version_that_does_not_match_the_gaps_is_refused(self):
        for what, edit in (("gaps in version 1", lambda m: m.update(version=1)),
                           ("version 2 without gaps", lambda m: m.pop("gaps"))):
            manifest = self.recipe(gaps="gaps.json")
            edit(manifest)
            with self.subTest(what):
                self.assertTrue(mf.validate_manifest(manifest))

    def test_gaps_need_a_safe_unique_json_path_in_a_recipe(self):
        for path in ("../gaps.json", "gaps.txt", "recipe.json", "part.step"):
            with self.subTest(path):
                self.assertTrue(mf.validate_manifest(self.recipe(gaps=path)))

    def test_gaps_on_a_package_that_has_no_recipe_are_refused(self):
        step_only = mf.build_step_only_manifest("Part", "w")
        step_only.update(gaps="gaps.json", version=2)
        self.assertTrue(mf.validate_manifest(step_only))
        rows = good()
        rows["gaps"] = "gaps.json"
        self.assertTrue(mf.validate_manifest(rows))

    def test_a_parts_package_names_the_gaps_file_of_each_part_and_only_for_a_part_with_a_recipe(self):
        parts = [{"name": "Tray", "step": mf.part_step_path(1), "recipe": mf.part_recipe_path(1),
                  "gaps": mf.part_gaps_path(1)},
                 {"name": "Cover", "step": mf.part_step_path(2), "recipe": mf.part_recipe_path(2)}]
        manifest = mf.build_parts_manifest("Planter", "w", parts, notes=["2 parts."])
        self.assertEqual((manifest["version"], manifest["parts"][0]["gaps"]), (2, "parts/01/gaps.json"))
        self.assertEqual(mf.validate_manifest(manifest), [])
        self.assertEqual(validate(manifest, load_schema(PACKAGE_SCHEMA_V2)), [])
        broken = {**manifest, "parts": [dict(parts[0], recipe=None), manifest["parts"][1]]}
        self.assertTrue(mf.validate_manifest(broken))
        self.assertTrue(mf.validate_manifest({**manifest, "gaps": "gaps.json"}))
        self.assertTrue(mf.validate_manifest({**manifest, "version": 1}))


class CutsManifestTest(unittest.TestCase):
    CUTS = [{"name": "slope", "reason": "Slope: the range stops at 0.5, since Fusion did not rebuild the design at 5 (Chamfer3)."}]

    def test_a_recipe_lists_its_cut_sizes_apart_from_the_loose_ones_and_follows_the_schema_copy(self):
        manifest = mf.build_recipe_manifest("Part", "w", notes=["1 step copied."], cuts=self.CUTS)
        self.assertEqual((manifest["version"], manifest["cuts"], "loose" in manifest), (1, self.CUTS, False))
        self.assertEqual(mf.validate_manifest(manifest), [])
        self.assertEqual(validate(manifest, load_schema(PACKAGE_SCHEMA)), [])
        self.assertEqual(validate({**manifest, "version": 2}, load_schema(PACKAGE_SCHEMA_V2)), [])
        self.assertNotIn("cuts", mf.build_recipe_manifest("Part", "w", notes=["1 step copied."]))
        long = mf.build_recipe_manifest("Part", "w", cuts=[{"name": "slope", "reason": "x" * 201}])
        self.assertTrue(mf.validate_manifest(long))
        self.assertTrue(validate({**long, "version": 2}, load_schema(PACKAGE_SCHEMA_V2)))

    def test_a_part_lists_its_cut_sizes(self):
        parts = [{"name": "Tray", "step": mf.part_step_path(1), "recipe": mf.part_recipe_path(1), "cuts": self.CUTS}]
        manifest = mf.build_parts_manifest("Planter", "w", parts, notes=["1 part."])
        self.assertEqual(manifest["parts"][0]["cuts"], self.CUTS)
        self.assertEqual(mf.validate_manifest(manifest), [])
        self.assertEqual(validate({**manifest, "version": 2}, load_schema(PACKAGE_SCHEMA_V2)), [])


class UntranslatedParameterManifestTest(unittest.TestCase):
    ENTRY = {"name": "odd", "label": "odd", "value": 5.0, "unit": "mm", "expression": "wall + 30 deg",
             "untranslated": "It adds a length and an angle."}

    def test_a_parameter_with_fusion_text_follows_the_schema_copy_and_long_text_is_refused_by_both(self):
        manifest = mf.build_recipe_manifest("Part", "w", notes=["1 step copied."], parameters=[self.ENTRY])
        self.assertEqual(mf.validate_manifest(manifest), [])
        schema = load_schema(PACKAGE_SCHEMA_V2)
        self.assertEqual(validate({**manifest, "version": 2}, schema), [])
        for key, size in (("expression", 301), ("untranslated", 201)):
            long = {**manifest, "parameters": [{**self.ENTRY, key: "x" * size}]}
            self.assertTrue(mf.validate_manifest(long), key)
            self.assertTrue(validate({**long, "version": 2}, schema), key)


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
                fixed=[{"name": "gap", "reason": "gap stays fixed for now."}],
                loose=[{"name": "wall", "reason": "wall may give unexpected results: it moves a joint."}]),
        ]
        for manifest in manifests:
            self.assertEqual(mf.validate_manifest(manifest), [])
            self.assertEqual(validate(manifest, self.schema), [], manifest["kind"])

    def test_a_long_loose_reason_and_a_long_comment_are_refused_by_both(self):
        too_long = (
            mf.build_recipe_manifest("Part", "w", loose=[{"name": "wall", "reason": "x" * 201}]),
            mf.build_step_only_manifest("Part", "w", parameters=[
                {"name": "wall", "value": 2, "unit": "mm", "comment": "x" * (mf.MAX_PARAMETER_COMMENT + 1)}]),
        )
        for manifest in too_long:
            with self.subTest(kind=manifest["kind"]):
                self.assertTrue(mf.validate_manifest(manifest))
                self.assertTrue(validate(manifest, self.schema))


if __name__ == "__main__":
    unittest.main()
