import unittest

from tests import context  # noqa: F401
from tests import fakes

fakes.install_adsk_core()
from lib.fusion_ui import recipe_dialog  # noqa: E402
from lib.package.manifest import MAX_PARTS  # noqa: E402


def offer(param, state="size", reason="", now="2 mm", lo=1.0, hi=4.0, value=2.0, **extra):
    plain = state in ("size", "keep")
    return {"param": param, "text": param, "ticked": state == "size", "enabled": plain, "state": state,
            "reason": reason, "now": now, "comment": "", "formula": "", "kind": "length", "value": value,
            "min": lo if plain else None, "max": hi if plain else None, **extra}


def make_dialog(offers, body=None):
    command = fakes.FakeCommand()
    recipe_dialog.build(command, offers, body, "z")
    return command, command.commandInputs


def row(inputs, key, index):
    return inputs.itemById(recipe_dialog.CELL_PREFIX[key] + str(index))


def count_text(inputs):
    return inputs.itemById(recipe_dialog.DETAILS_ID).formattedText


def tick(inputs, offers, index, on):
    """The person clicks a tick: the box changes first, then the change handler runs."""
    box = row(inputs, "tick", index)
    box.value = on
    recipe_dialog.handle_change(inputs, offers, box)


def pick_body(inputs):
    inputs.itemById(recipe_dialog.BODY_ID).picked.append(type("Body", (), {"isSolid": True})())


class BuildTest(unittest.TestCase):
    def test_one_row_per_parameter_under_a_header_with_the_rows_state_in_its_cells(self):
        offers = [offer("wall"), offer("gap", "keep"), offer("pipe", "locked", "Changes a sketch.", lo=None)]
        _, inputs = make_dialog(offers)
        table = inputs.itemById(recipe_dialog.TABLE_ID)
        self.assertEqual(table.rowCount, 4)
        self.assertEqual((row(inputs, "tick", 0).value, row(inputs, "tick", 1).value), (True, False))
        self.assertFalse(row(inputs, "tick", 2).isEnabled)
        self.assertEqual(row(inputs, "min", 0).value, "1")
        self.assertTrue(row(inputs, "min", 0).isEnabled)
        self.assertFalse(row(inputs, "min", 1).isEnabled)
        self.assertEqual(row(inputs, "status", 1).formattedText, "stays 2 mm")
        self.assertEqual(row(inputs, "status", 2).formattedText, "fixed, changes a sketch")
        self.assertEqual(len(table.toolbar), 2)
        self.assertEqual(row(inputs, "tick", 0).text, "")

    def test_no_parameters_gives_a_plain_line_and_no_table(self):
        _, inputs = make_dialog([])
        self.assertIsNone(inputs.itemById(recipe_dialog.TABLE_ID))
        self.assertIn("no user parameters", inputs.itemById(recipe_dialog.INTRO_ID).formattedText)


class LayoutTest(unittest.TestCase):
    def test_a_quote_in_a_name_or_comment_reaches_the_boxes_unescaped_and_markup_escaped(self):
        offers = [offer('w"all<1>', comment='say "hi"')]
        _, inputs = make_dialog(offers)
        self.assertEqual(row(inputs, "name", 0).formattedText, 'w"all&lt;1&gt;')
        recipe_dialog.apply_offers(inputs, offers, offers)
        table = inputs.itemById(recipe_dialog.TABLE_ID)
        table.selectedRow = 1
        recipe_dialog.handle_change(inputs, offers, table)
        shown = inputs.itemById(recipe_dialog.DETAILS_ID).formattedText
        self.assertIn('<b>w"all&lt;1&gt;</b>', shown)
        self.assertIn('Comment: say "hi"', shown)
        self.assertNotIn("&quot;", shown)

    def test_the_details_box_grows_for_a_long_comment_and_a_stop_warning_fits_its_lines(self):
        offers = [offer("wall", comment="c" * 300)]
        _, inputs = make_dialog(offers)
        hint_rows = inputs.itemById(recipe_dialog.DETAILS_ID).numRows
        table = inputs.itemById(recipe_dialog.TABLE_ID)
        table.selectedRow = 1
        recipe_dialog.handle_change(inputs, offers, table)
        self.assertGreater(inputs.itemById(recipe_dialog.DETAILS_ID).numRows, hint_rows)
        recipe_dialog.show_stop(inputs, {"lines": ["Copied with a note: x."], "stops": False, "tooltip": "",
                                         "index": None})
        self.assertEqual(inputs.itemById(recipe_dialog.WARN_ID).numRows, 1)


class TickTest(unittest.TestCase):
    def test_unticking_a_row_greys_its_range_and_shows_what_stays(self):
        offers = [offer("wall")]
        _, inputs = make_dialog(offers)
        tick(inputs, offers, 0, False)
        self.assertFalse(row(inputs, "min", 0).isEnabled)
        self.assertEqual(row(inputs, "status", 0).formattedText, "stays 2 mm")
        self.assertIn("0 of 64", count_text(inputs))

    def test_a_tick_over_the_limit_is_undone_and_the_limit_is_said(self):
        offers = [offer("p%d" % i) for i in range(recipe_dialog.MAX_TICKED)] + [offer("extra", "keep")]
        _, inputs = make_dialog(offers)
        tick(inputs, offers, len(offers) - 1, True)
        self.assertFalse(row(inputs, "tick", len(offers) - 1).value)
        self.assertIn("up to 64", count_text(inputs))
        tick(inputs, offers, 0, False)
        self.assertIn("63 of 64", count_text(inputs))

    def test_the_buttons_tick_what_the_body_uses_and_untick_all(self):
        offers = [offer("a"), offer("b", "keep"), offer("c", "locked", lo=None)]
        _, inputs = make_dialog(offers)
        recipe_dialog.handle_change(inputs, offers, fakes.FakeInput(recipe_dialog.CLEAR_ID))
        self.assertEqual(recipe_dialog.read_form(inputs, offers)["ticked"], [])
        recipe_dialog.handle_change(inputs, offers, fakes.FakeInput(recipe_dialog.TICK_USED_ID))
        self.assertEqual(recipe_dialog.read_form(inputs, offers)["ticked"], ["a"])

    def test_the_details_follow_the_row_that_was_touched(self):
        offers = [offer("a"), offer("c", "locked", "Changes a sketch.", lo=None)]
        _, inputs = make_dialog(offers)
        inputs.itemById(recipe_dialog.TABLE_ID).selectedRow = 2
        recipe_dialog.handle_change(inputs, offers, fakes.FakeInput("pm_other"))
        self.assertIn("Changes a sketch.", inputs.itemById(recipe_dialog.DETAILS_ID).formattedText)
        tick(inputs, offers, 0, False)
        self.assertIn("Stays a fixed number", inputs.itemById(recipe_dialog.DETAILS_ID).formattedText)


class DoubtfulTest(unittest.TestCase):
    def test_a_doubtful_size_says_so_and_stays_a_size(self):
        offers = [offer("wall", doubt="wall may give unexpected results: it moves a joint."), offer("gap")]
        _, inputs = make_dialog(offers)
        self.assertEqual(row(inputs, "status", 0).formattedText, "size, may be unexpected")
        self.assertEqual(row(inputs, "status", 1).formattedText, "size")
        self.assertEqual(set(recipe_dialog.read_form(inputs, offers)),
                         {"bodies", "body", "ticked", "ranges", "range_problem", "up_axis", "faster_tries",
                          "light_undo"})


class FasterTriesTest(unittest.TestCase):
    def test_the_experiment_boxes_start_off_and_the_form_reads_them(self):
        for key, box in (("faster_tries", recipe_dialog.FASTER_ID), ("light_undo", recipe_dialog.LIGHT_UNDO_ID)):
            with self.subTest(key):
                _, inputs = make_dialog([offer("wall")])
                self.assertFalse(recipe_dialog.read_form(inputs, [offer("wall")])[key])
                inputs.itemById(box).value = True
                self.assertTrue(recipe_dialog.read_form(inputs, [offer("wall")])[key])


class SeveralBodiesTest(unittest.TestCase):
    def test_up_to_the_part_limit_of_bodies_can_be_picked_and_the_form_lists_them(self):
        offers = [offer("wall")]
        _, inputs = make_dialog(offers)
        self.assertEqual(inputs.itemById(recipe_dialog.BODY_ID).limits, (1, MAX_PARTS))
        pick_body(inputs)
        pick_body(inputs)
        form = recipe_dialog.read_form(inputs, offers)
        self.assertEqual(len(form["bodies"]), 2)
        self.assertIsNone(form["body"])
        self.assertTrue(recipe_dialog.inputs_valid(inputs, offers))

    def test_one_picked_body_is_the_form_body(self):
        offers = [offer("wall")]
        _, inputs = make_dialog(offers)
        pick_body(inputs)
        form = recipe_dialog.read_form(inputs, offers)
        self.assertIs(form["body"], form["bodies"][0])

    def test_a_pick_with_something_that_is_not_a_solid_body_is_not_valid(self):
        offers = [offer("wall")]
        _, inputs = make_dialog(offers)
        pick_body(inputs)
        inputs.itemById(recipe_dialog.BODY_ID).picked.append(type("Face", (), {"isSolid": False})())
        self.assertFalse(recipe_dialog.inputs_valid(inputs, offers))


class RangeTest(unittest.TestCase):
    def test_a_typed_range_goes_into_the_form_and_ok_needs_a_body(self):
        offers = [offer("wall")]
        _, inputs = make_dialog(offers)
        row(inputs, "max", 0).value = "6"
        self.assertEqual(recipe_dialog.read_form(inputs, offers)["ranges"], {"wall": (1.0, 6.0)})
        self.assertFalse(recipe_dialog.inputs_valid(inputs, offers))
        pick_body(inputs)
        self.assertTrue(recipe_dialog.inputs_valid(inputs, offers))

    def test_a_bad_range_is_named_and_blocks_ok(self):
        offers = [offer("wall")]
        _, inputs = make_dialog(offers)
        pick_body(inputs)
        row(inputs, "min", 0).value = "3"
        recipe_dialog.handle_change(inputs, offers, row(inputs, "min", 0))
        self.assertIn("must sit between", count_text(inputs))
        self.assertFalse(recipe_dialog.inputs_valid(inputs, offers))

    def test_a_row_that_is_not_ticked_is_not_checked(self):
        offers = [offer("wall")]
        _, inputs = make_dialog(offers)
        row(inputs, "min", 0).value = "nonsense"
        tick(inputs, offers, 0, False)
        self.assertEqual(recipe_dialog.read_form(inputs, offers)["range_problem"], "")


class ApplyOffersTest(unittest.TestCase):
    def test_new_body_updates_ticks_enabled_state_and_texts(self):
        offers = [offer("width"), offer("depth", "locked", "Old reason", lo=None)]
        _, inputs = make_dialog(offers)
        fresh = [offer("width", "locked", "Changes a sketch.", lo=None), offer("depth", "size")]
        recipe_dialog.apply_offers(inputs, offers, fresh)
        self.assertEqual((row(inputs, "tick", 0).value, row(inputs, "tick", 0).isEnabled), (False, False))
        self.assertEqual((row(inputs, "tick", 1).value, row(inputs, "tick", 1).isEnabled), (True, True))
        self.assertEqual(row(inputs, "status", 0).formattedText, "fixed, changes a sketch")
        self.assertEqual(offers, fresh)

    def test_typed_ranges_go_back_to_the_defaults_for_the_new_body(self):
        offers = [offer("wall")]
        _, inputs = make_dialog(offers)
        row(inputs, "max", 0).value = "9"
        recipe_dialog.apply_offers(inputs, offers, [offer("wall", hi=5.0)])
        self.assertEqual(row(inputs, "max", 0).value, "5")

    def test_one_failing_row_leaves_the_others_updated_and_its_entry_old(self):
        offers = [offer("a"), offer("b")]
        _, inputs = make_dialog(offers)

        class Broken(fakes.FakeCheckbox):
            @property
            def isEnabled(self):
                return True

            @isEnabled.setter
            def isEnabled(self, _):
                if getattr(self, "armed", False):
                    raise RuntimeError("boom")

        broken = Broken("pm_tick_0", "", True)
        broken.armed = True
        inputs.items["pm_tick_0"] = broken
        fresh = [offer("a", "locked", "x", lo=None), offer("b", "keep")]
        recipe_dialog.apply_offers(inputs, offers, fresh)
        self.assertEqual(offers[0]["state"], "size")
        self.assertEqual(offers[1], fresh[1])
        self.assertFalse(row(inputs, "tick", 1).value)


if __name__ == "__main__":
    unittest.main()
