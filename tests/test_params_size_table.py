import unittest

from tests import context  # noqa: F401
from lib.params import size_table
from lib.params.size_table import CONSTANT, DERIVED, FIXED, FREE, NOT_OFFERED
from tests.params_fixtures import CUBE, D, H, RAW, W, reader_dicts

TICKED = [W, H, D, CUBE]
NEW_W = "FilterBox___width__contains_CeramicMedium"


def table(ticked=TICKED, **kw):
    return size_table.build(reader_dicts(), ticked, **kw)


class FilterBoxTableTest(unittest.TestCase):
    def test_counts_and_cube_are_free_sizes_with_renamed_dollar_names(self):
        t = table()
        self.assertEqual(t.ticked, TICKED)
        self.assertEqual(t.sizes[NEW_W], {"kind": "number", "value": 1.8, "min": 0.9, "max": 3.6, "label": W})
        self.assertEqual(t.sizes[CUBE]["kind"], "length")
        self.assertEqual((t.sizes[CUBE]["value"], t.sizes[CUBE]["min"], t.sizes[CUBE]["max"]), (18.0, 9.0, 36.0))
        self.assertEqual(t.renames[W], NEW_W)
        self.assertNotIn(CUBE, t.renames)

    def test_formulas_become_derived_sizes_in_the_app_grammar(self):
        t = table()
        self.assertEqual(t.sizes["FilterBox_width_mm"]["expr"], f"{NEW_W} * {CUBE} + 2")
        self.assertEqual(t.sizes["FilterBox_height_mm"]["expr"], "FilterBox___height__contains_CeramicMedium * " + CUBE)
        self.assertEqual(t.entry("FilterBox_depth_mm").state, DERIVED)
        report = t.report()["derived"]["FilterBox_width_mm"]
        self.assertAlmostEqual(report["value"], 34.4)
        self.assertAlmostEqual(report["fusion_value"], 34.4)

    def test_plain_unticked_parameters_are_constants(self):
        t = table()
        e = t.entry("FilterBox__PipeTop_offsetFromCenter_mm")
        self.assertEqual((e.state, e.value), (CONSTANT, 0.05))
        self.assertNotIn("FilterBox__PipeTop_offsetFromCenter_mm", t.sizes)

    def test_translate_a_model_parameter_formula_over_sizes(self):
        t = table()
        tr = t.translate("FilterBox_width_mm - 2 mm", expected=32.4)
        self.assertEqual(tr.formula, "FilterBox_width_mm - 2")
        self.assertEqual(tr.dim, "length")
        self.assertAlmostEqual(tr.value, 32.4)
        self.assertEqual(set(tr.reads), {W, CUBE})

    def test_translate_refuses_a_formula_that_misses_the_fusion_value(self):
        tr = table().translate("FilterBox_width_mm - 2 mm", expected=30.0)
        self.assertFalse(tr.ok)
        self.assertEqual(set(tr.reads), {W, CUBE})

    def test_unticked_names_become_numbers_and_a_formula_without_sizes_has_no_reads(self):
        t = table(ticked=[])
        self.assertEqual(t.sizes, {})
        tr = t.translate("FilterBox_width_mm * 2")
        self.assertEqual((tr.formula, tr.reads), ("34.4 * 2", ()))
        self.assertAlmostEqual(tr.value, 68.8)

    def test_depends_follows_derived_parameters_to_ticked_ones(self):
        t = table(ticked=[W, CUBE])
        self.assertEqual(t.depends("FilterBox_width_mm"), {W, CUBE})
        self.assertEqual(t.depends("FilterBox_height_mm"), {CUBE})
        self.assertEqual(t.depends(W), {W})
        self.assertEqual(t.depends("FilterBox__PipeTop_offsetFromCenter_mm"), frozenset())
        self.assertEqual(t.depends("nothing"), frozenset())

    def test_unticking_the_cube_makes_height_follow_only_the_count(self):
        t = table(ticked=[H])
        self.assertEqual(t.sizes["FilterBox_height_mm"]["expr"], "FilterBox___height__contains_CeramicMedium * 18")

    def test_fixed_size_becomes_a_number_and_is_listed(self):
        t = table().with_fixed({CUBE: "Cube stays fixed for now: it changes Sketch3."})
        self.assertEqual(t.entry(CUBE).state, FIXED)
        self.assertNotIn(CUBE, t.sizes)
        self.assertEqual(t.fixed, [{"name": CUBE, "reason": "Cube stays fixed for now: it changes Sketch3."}])
        self.assertEqual(t.sizes["FilterBox_width_mm"]["expr"], f"{NEW_W} * 18 + 2")
        self.assertNotIn(CUBE, t.ticked)

    def test_fixing_every_input_turns_derived_sizes_into_numbers(self):
        t = table(ticked=[W]).with_fixed({W: "x"})
        self.assertEqual(t.sizes, {})
        self.assertEqual(t.entry("FilterBox_width_mm").state, CONSTANT)

    def test_model_parameter_is_inlined_and_cycles_refuse(self):
        model = [dict(name="d12", expression=f"FilterBox_height_mm - 2 mm", value=1.96, unit="mm", kind="derived"),
                 dict(name="loop_a", expression="loop_b", value=1, unit="mm", kind="derived"),
                 dict(name="loop_b", expression="loop_a", value=1, unit="mm", kind="derived")]
        t = table(model_params=model)
        tr = t.translate("d12 / 2", expected=9.8)
        self.assertEqual(tr.formula, "(FilterBox_height_mm - 2) / 2")
        self.assertFalse(t.translate("loop_a").ok)

    def test_unsupported_function_keeps_the_dependencies(self):
        params = [dict(name="a", expression="10 mm", value=1.0, unit="mm", comment="", is_favorite=True, kind="length"),
                  dict(name="b", expression="sin(a)", value=0.0, unit="", comment="", is_favorite=False,
                       kind="derived", dependency_parameters=["a"])]
        t = size_table.build(params, ["a"])
        self.assertEqual(t.entry("b").state, NOT_OFFERED)
        tr = t.translate("b * 2 mm")
        self.assertFalse(tr.ok)
        self.assertEqual(tr.reads, ("a",))

    def test_value_check_rejects_a_bare_number_in_the_wrong_unit(self):
        # A design in inches: Fusion reads "wall + 5" as 5 in, here the formula would give 5 mm.
        params = [dict(name="wall", expression="2 mm", value=0.2, unit="mm", comment="", is_favorite=True, kind="length"),
                  dict(name="bare", expression="wall + 5", value=0.2 + 12.7, unit="mm", comment="",
                       is_favorite=False, kind="derived")]
        self.assertEqual(size_table.build(params, ["wall"], design_unit="in").entry("bare").state, DERIVED)
        self.assertEqual(size_table.build(params, ["wall"], design_unit="mm").entry("bare").state, NOT_OFFERED)

    def test_more_than_64_sizes_keep_the_first_64(self):
        params = [dict(name=f"p{i}", expression="1 mm", value=0.1, unit="mm", comment="", is_favorite=True,
                       kind="length") for i in range(70)]
        t = size_table.build(params, [p["name"] for p in params])
        self.assertEqual(len(t.sizes), 64)
        self.assertEqual(t.entry("p64").state, CONSTANT)

    def test_unsupported_unit_and_text_are_not_offered(self):
        params = [dict(name="mass", expression="5 kg", value=5.0, unit="kg", comment="", is_favorite=True,
                       kind="unsupported")]
        t = size_table.build(params, ["mass"])
        self.assertEqual(t.entry("mass").state, NOT_OFFERED)
        self.assertEqual(t.sizes, {})

    def test_count_kind_and_step_for_pattern_quantities(self):
        params = [dict(name="holes", expression="3", value=3.0, unit="", comment="", is_favorite=True, kind="count")]
        model = [dict(name="d5", expression="holes", value=3.0, unit="", role="Quantity",
                      dependency_parameters=["holes"], kind="derived")]
        t = size_table.build(params, ["holes"], model_params=model)
        self.assertEqual(t.sizes["holes"], {"kind": "count", "value": 3.0, "min": 1.0, "max": 6.0, "label": "holes", "step": 1})

    def test_favourite_model_parameter_is_treated_as_a_user_parameter(self):
        model = [dict(name="d3", expression="4 mm", value=0.4, unit="mm", is_favorite=True, kind="length")]
        t = size_table.build([], ["d3"], model_params=model)
        self.assertEqual(t.sizes["d3"]["value"], 4.0)

    def test_raw_fixture_values_match_the_screenshot(self):
        self.assertEqual(len(RAW), 9)


if __name__ == "__main__":
    unittest.main()
