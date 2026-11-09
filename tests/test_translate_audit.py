"""The end of walk audit: a size that a copied step reads always ends in a state the person is told about."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sketch_motion import BOX, BOX_SIZES, motion_of
from tests.translator_helpers import load_capture

from lib.params import size_table
from lib.translator import translate
from lib.translator.extrude import handle as extrude_handle
from lib.translator.result import Refusal
from lib.translator.values import numbers_of

TRAY = "filter_tray_sized"
COUNT = "FilterBox_$_height__contains_CeramicMedium"
CUBE = "_CeramicMedium__Cube_width_mm"


def forgetful_extrude(item, ctx):
    """An extrude handler that writes every length as a number and records nothing about the sizes behind it."""
    with ctx.recording():  # what the real handler records is dropped
        outcome = extrude_handle(item, ctx)
    if not isinstance(outcome, Refusal):
        for entry in outcome.entries:
            entry.step = numbers_of(entry.step)
    return outcome


def tray_result(handlers=None):
    capture = load_capture(TRAY)
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"],
                             capture.get("design_units", "mm"))
    return translate(capture, handlers=handlers, size_table=table)


class AuditTest(unittest.TestCase):
    def test_a_handler_that_forgets_its_sizes_leaves_them_loose_or_dropped_with_a_reason_naming_the_step(self):
        result = tray_result({"ExtrudeFeature": forgetful_extrude})
        # The cube width is also read by the hole spacing, so it stays a free size with a warning.
        self.assertEqual([f["name"] for f in result.loose], [CUBE])
        self.assertIn("Extrude1", result.loose[0]["reason"])
        self.assertIn(CUBE, result.recipe["sizes"])
        # Nothing else reads the cube count, so it is not a size.
        (dropped,) = [d for d in result.dropped if d["name"] == COUNT]
        self.assertTrue(dropped["used"])
        self.assertIn("Extrude1", dropped["reason"])
        self.assertNotIn(COUNT, result.recipe["sizes"])

    def test_the_real_handlers_leave_nothing_to_the_audit_and_an_unread_size_is_dropped_as_unused(self):
        result = tray_result()
        self.assertEqual((result.fixed, result.loose), ([], []))
        (dropped,) = result.dropped
        self.assertEqual((dropped["name"], dropped["used"]), ("turn_deg", False))
        self.assertIn("not used by any copied step", dropped["reason"])

    def test_a_size_that_moves_a_measured_sketch_by_nothing_is_dropped_as_changing_nothing(self):
        def still(values):
            values.pop("5/positions/0/0")

        capture = load_capture(BOX)
        params = capture["parameters"]
        table = size_table.build(params["user"], BOX_SIZES, params["model"], capture.get("design_units", "mm"))
        result = translate(capture, size_table=table, motion=motion_of(BOX, still))
        self.assertEqual(result.loose, [])
        (dropped,) = result.dropped
        self.assertEqual((dropped["name"], dropped["used"]), ("pipe_offset_mm", False))
        self.assertIn("changing it changes nothing", dropped["reason"])


if __name__ == "__main__":
    unittest.main()
