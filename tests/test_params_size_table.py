import unittest

from tests import context  # noqa: F401
from lib.params import size_table
from lib.params.size_table import CONSTANT, DERIVED, FIXED, FREE, NOT_OFFERED
from tests.params_fixtures import CUBE, D, H, W, hobby_dicts, reader_dicts

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

    def test_fixed_size_becomes_a_number_and_is_listed(self):
        t = table().with_fixed({CUBE: "Cube stays fixed for now: it changes Sketch3."})
        self.assertEqual(t.entry(CUBE).state, FIXED)
        self.assertNotIn(CUBE, t.sizes)
        self.assertEqual(t.fixed, [{"name": CUBE, "reason": "Cube stays fixed for now: it changes Sketch3."}])
        self.assertEqual(t.sizes["FilterBox_width_mm"]["expr"], f"{NEW_W} * 18 + 2")
        self.assertNotIn(CUBE, t.ticked)

    def test_a_typed_range_is_told_from_the_default_one_per_end(self):
        size = table().sizes[NEW_W]
        self.assertFalse(table().typed_range(W))
        self.assertTrue(table(ranges={W: (0.5, 3)}).typed_range(W))
        self.assertEqual(table(ranges={W: (size["min"], size["max"])}).typed_ends(W), (False, False))
        self.assertEqual(table(ranges={W: (size["min"], 9.0)}).typed_ends(W), (False, True))

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

    def test_count_kind_and_step_for_pattern_quantities(self):
        params = [dict(name="holes", expression="3", value=3.0, unit="", comment="", is_favorite=True, kind="count")]
        model = [dict(name="d5", expression="holes", value=3.0, unit="", role="Quantity",
                      dependency_parameters=["holes"], kind="derived")]
        t = size_table.build(params, ["holes"], model_params=model)
        self.assertEqual(t.sizes["holes"], {"kind": "count", "value": 3.0, "min": 1.0, "max": 6.0, "label": "holes", "step": 1})

    def test_a_count_is_found_by_the_pattern_quantity_it_drives_whatever_the_role_text(self):
        params = [dict(name="holes", expression="3", value=3.0, unit="", comment="", is_favorite=True, kind="count"),
                  dict(name="ratio", expression="1.5", value=1.5, unit="", comment="", is_favorite=True, kind="count")]
        model = [dict(name="d5", expression="holes", value=3.0, unit="", role="Other", dependency_parameters=["holes"],
                      kind="derived")]
        refs = [{"name": "d5", "expression": "holes", "value": 3.0}]
        t = size_table.build(params, ["holes", "ratio"], model_params=model, quantity_params=refs)
        self.assertEqual(t.sizes["holes"]["kind"], "count")
        self.assertEqual(t.sizes["ratio"]["kind"], "number")
        self.assertEqual(size_table.build(params, ["holes"], model_params=model).sizes["holes"]["kind"], "number")


class HobbyProjectTest(unittest.TestCase):
    """Intermediate parameters (counts made lengths, setup values, chains) never break the formulas that read them."""

    def test_every_parameter_but_the_weight_translates_with_the_counts_ticked(self):
        t = size_table.build(hobby_dicts(), ["cols", "rows"])
        states = {e.name: e.state for e in t.entries}
        self.assertEqual(states["weight"], NOT_OFFERED)
        self.assertEqual(t.entry("weight").reason, size_table.UNIT_REASON)
        self.assertTrue(all(s != NOT_OFFERED for n, s in states.items() if n != "weight"), states)
        self.assertEqual(t.sizes["cols_mm"]["expr"], "cols")
        self.assertEqual(t.sizes["spacing"]["expr"], "cols_mm + rows + lip")
        self.assertEqual(t.sizes["lip"]["expr"], "inner > 100 ? 3 : 2")
        self.assertEqual(t.entry("wall").state, CONSTANT)

    def test_unticked_intermediates_are_written_as_numbers(self):
        t = size_table.build(hobby_dicts(), ["layers"])
        self.assertEqual(t.sizes["wall"]["expr"], "layers * 0.4")
        self.assertEqual(t.sizes["inner"]["expr"], "167.5 - wall * 2")
        self.assertEqual(t.entry("width").state, CONSTANT)

    def test_a_feature_value_reading_the_chain_through_a_model_parameter(self):
        model = [dict(name="d7", expression="lip * cols", value=1.2, unit="mm", kind="derived")]
        tr = size_table.build(hobby_dicts(), ["cols"], model_params=model).translate(
            "d7 + 1", expected=13.0, dim="length", unit="mm")
        self.assertEqual((tr.formula, tr.dim, tr.reads), ("lip * cols + 1", "length", ("cols",)))

    def test_a_plain_number_formula_in_a_length_is_read_in_the_parameter_unit(self):
        params = hobby_dicts() + [dict(name="gap_in", expression="cols / 8", value=1.27, unit="in", comment="",
                                       is_favorite=False, kind="derived", dependency_parameters=["cols"])]
        t = size_table.build(params, ["cols"])
        self.assertEqual(t.sizes["gap_in"]["expr"], "cols / 8 * 25.4")

    def test_a_unit_built_from_lengths_is_a_number_formulas_can_read(self):
        params = [dict(name="w", expression="10 mm", value=1.0, unit="mm", comment="", is_favorite=True,
                       kind="length"),
                  dict(name="area", expression="200 mm^2", value=2.0, unit="mm^2", comment="", is_favorite=False,
                       kind="unsupported"),
                  dict(name="depth", expression="area / w", value=2.0, unit="mm", comment="", is_favorite=False,
                       kind="derived")]
        t = size_table.build(params, ["w", "area"])
        self.assertEqual((t.entry("area").state, t.entry("area").value), (CONSTANT, 200.0))
        self.assertEqual(t.sizes["depth"]["expr"], "200 / w")

    def test_derived_formulas_past_the_size_cap_are_written_where_they_are_read(self):
        t = size_table.build(hobby_dicts(), ["cols", "rows"], max_sizes=4)
        self.assertEqual(len(t.sizes), 4)
        self.assertEqual(t.entry("lip").state, DERIVED)
        self.assertIsNone(t.size_name("lip"))
        self.assertEqual(t.sizes["cols_mm"]["expr"], "cols")
        tr = t.translate("lip * 2", expected=6.0)
        self.assertEqual((tr.formula, tr.value), ("(width - 1.2 * 2 > 100 ? 3 : 2) * 2", 6.0))


if __name__ == "__main__":
    unittest.main()
