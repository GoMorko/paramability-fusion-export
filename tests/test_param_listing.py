import json
import os
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture
from tests.params_fixtures import CUBE, W, reader_dicts
from lib.export_plan.assemble import build_package
from lib.export_plan.recipe_export import plan_single_export
from lib.package import manifest as mf
from lib.params.listing import CAP_REASON, UNIT_REASON, list_parameters


def plain(name, mm_value, comment="", unit="mm"):
    cm = mm_value / 10.0 if unit == "mm" else mm_value
    return dict(name=name, expression=f"{mm_value} mm", value=cm, display_value=mm_value, unit=unit, comment=comment,
                is_favorite=False, kind="length", value_type="numeric", dependency_parameters=[])


def formula(name, expression, mm_value, reads=()):
    p = plain(name, mm_value)
    p.update(expression=expression, kind="derived", dependency_parameters=list(reads))
    return p


def by_label(listing):
    return {e["label"]: e for e in listing.entries}


class ListingTest(unittest.TestCase):
    def test_plain_number_keeps_value_unit_and_comment(self):
        listing = list_parameters([plain("wall", 2, comment="Wall thickness")])
        self.assertEqual(listing.entries, [
            {"name": "wall", "label": "wall", "value": 2.0, "unit": "mm", "comment": "Wall thickness"}])

    def test_translated_formula_reads_other_entries_by_their_listed_names(self):
        listing = list_parameters(reader_dicts(), design_unit="mm")
        entries = by_label(listing)
        self.assertEqual(entries[CUBE]["value"], 18.0)
        self.assertNotIn("expr", entries[CUBE])
        count = entries[W]
        self.assertEqual((count["name"], count["unit"]), ("FilterBox___width__contains_CeramicMedium", ""))
        width = entries["FilterBox_width_mm"]
        self.assertEqual(width["expr"], f"{count['name']} * {CUBE} + 2")
        self.assertAlmostEqual(width["value"], 34.4)
        self.assertEqual(listing.no_formula, [])

    def test_formula_that_cannot_be_translated_is_listed_with_its_value_only(self):
        params = [plain("wall", 2), formula("odd", "wall + 30 deg", 5, reads=["wall"])]
        listing = list_parameters(params)
        self.assertEqual(by_label(listing)["odd"], {"name": "odd", "label": "odd", "value": 5.0, "unit": "mm"})
        self.assertEqual([x["name"] for x in listing.no_formula], ["odd"])

    def test_unit_that_is_not_length_angle_or_count_is_left_out(self):
        speed = plain("speed", 5, unit="mm/s")
        speed["kind"] = "unsupported"
        listing = list_parameters([plain("wall", 2), speed])
        self.assertEqual([e["label"] for e in listing.entries], ["wall"])
        self.assertEqual(listing.left_out, [{"name": "speed", "reason": UNIT_REASON}])

    def test_long_name_is_cut_in_label_and_name(self):
        long = "x" * 80
        entry = list_parameters([plain(long, 2)]).entries[0]
        self.assertEqual((len(entry["label"]), len(entry["name"])), (64, 64))
        self.assertEqual(mf.validate_manifest(mf.build_step_only_manifest("N", "w", parameters=[entry])), [])

    def test_the_list_stops_at_64(self):
        params = [plain(f"p{i}", i + 1) for i in range(70)]
        listing = list_parameters(params)
        names = [e["name"] for e in listing.entries]
        self.assertEqual(len(names), 64)
        self.assertEqual(names[-1], "p63")
        self.assertEqual(len(listing.left_out), 6)
        self.assertEqual(listing.left_out[0]["reason"], CAP_REASON)

    def test_a_formula_reading_a_cut_entry_loses_its_expr(self):
        params = [formula("total", "p69 * 2", 4, reads=["p69"])] + [plain(f"p{i}", i + 1) for i in range(70)]
        listing = list_parameters(params)
        self.assertEqual(len(listing.entries), 64)
        self.assertNotIn("expr", listing.entries[0])
        self.assertEqual(listing.no_formula[0]["name"], "total")


class ManifestParametersTest(unittest.TestCase):
    def stepped(self, parameters):
        return mf.build_step_only_manifest("N", "w", parameters=parameters)

    def test_empty_list_leaves_the_key_out(self):
        self.assertNotIn("parameters", self.stepped([]))

    def test_refused_shapes(self):
        good = {"name": "a", "label": "a", "value": 1, "unit": "mm"}
        self.assertEqual(mf.validate_manifest(self.stepped([good])), [])
        for bad in ({"name": ""}, {**good, "unit": "cm"}, {**good, "value": float("nan")}, {**good, "label": "x" * 65},
                    {**good, "comment": "x" * 201}, {**good, "expr": ""}):
            self.assertTrue(mf.validate_manifest(self.stepped([bad])), bad)
        self.assertTrue(mf.validate_manifest(self.stepped([good, dict(good)])))
        many = [{"name": f"p{i}"} for i in range(65)]
        self.assertTrue(mf.validate_manifest(self.stepped(many)))


class PackagesCarryTheListTest(unittest.TestCase):
    PARAMS = [plain("wall", 2), formula("outer", "wall * 2 + 1 mm", 5, reads=["wall"]), plain("a$b", 3)]

    def step(self, tmp):
        path = os.path.join(tmp, "part.step")
        with open(path, "wb") as f:
            f.write(b"ISO-10303-21;")
        return path

    def test_a_body_in_a_component_still_lists_the_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            listing = list_parameters(self.PARAMS)
            manifest, files, report = plan_single_export(
                RuntimeError("not read"), self.step(tmp), "Part", "w", "z", in_component=True, listing=listing)
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertEqual([p["name"] for p in manifest["parameters"]], ["wall", "outer", "a_b"])
        self.assertEqual(manifest["parameters"][1]["expr"], "wall * 2 + 1")
        self.assertEqual(report["parameters"]["listed"], 3)
        self.assertEqual(json.loads(files["report.json"])["parameters"]["left_out"], [])
        self.assertEqual(mf.validate_manifest(manifest), [])

    def test_a_recipe_package_carries_the_list_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, _, report = plan_single_export(
                load_capture("extrude_plate"), self.step(tmp), "Part", "w", "z", listing=list_parameters(self.PARAMS))
        self.assertEqual(manifest["kind"], "recipe")
        self.assertEqual(len(manifest["parameters"]), 3)
        self.assertEqual(report["parameters"]["listed"], 3)

    def test_without_a_list_the_manifest_has_no_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, _, report = plan_single_export(
                RuntimeError("x"), self.step(tmp), "Part", "w", "z", in_component=True)
        self.assertNotIn("parameters", manifest)
        self.assertNotIn("parameters", report)

    def test_size_rows_keep_their_columns_list_and_fusion_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            step = self.step(tmp)
            results = [{"name": "S", "values": {"a$b": 3.0}, "step_file": step},
                       {"name": "L", "values": {"a$b": 6.0}, "step_file": step}]
            manifest, _ = build_package("Clip", "w", results, ["a$b"], self.PARAMS, 0, "Size", "z")
        self.assertEqual(manifest["kind"], "valueRows")
        self.assertEqual(manifest["parameters"], [{"name": "a$b", "unit": "mm"}])
        self.assertEqual(manifest["rows"][1]["values"], {"a$b": 6.0})

    def test_one_size_is_a_step_only_package_with_the_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = [{"name": "S", "values": {"wall": 2.0}, "step_file": self.step(tmp)}]
            manifest, _ = build_package("Clip", "w", results, ["wall"], self.PARAMS, 0, "Size", "z")
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertEqual(len(manifest["parameters"]), 3)


if __name__ == "__main__":
    unittest.main()
