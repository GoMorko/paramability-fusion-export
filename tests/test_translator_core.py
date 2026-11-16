import copy
import json
import re
import unittest

from tests import context  # noqa: F401
from tests import schema_check
from tests.translator_helpers import left_out
from tests.translator_helpers import (
    assert_schema_ok, fixture_path, load_capture, translate_fixture,
)

from lib.translator import CaptureError, Refusal, StepResult, translate

with open(fixture_path("schema_example_v12"), encoding="utf-8") as _f:
    _EXAMPLE = json.load(_f)
_EXTRUDE = _EXAMPLE["features"][0]


def extrude_handler(ctx, step):
    return StepResult.of([copy.deepcopy(_EXTRUDE)])


def join_handler(ctx, step):
    step = copy.deepcopy(_EXTRUDE)
    step["combine"] = "add"
    return StepResult.of([step])


def by_index(table):
    return lambda ctx, step: table[step.index](ctx, step)


class CoreTest(unittest.TestCase):
    def test_empty_timeline_refuses(self):
        result = translate_fixture("core_empty")
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal["index"], None)
        self.assertIn("Nothing in the timeline", result.refusal["reason"])

    def test_unknown_feature_is_left_out_at_that_item(self):
        result = translate_fixture("core_unknown_feature", {"ExtrudeFeature": extrude_handler})
        self.assertIsNotNone(left_out(result))
        self.assertEqual((left_out(result)["index"], left_out(result)["type"]), (2, "EmbossFeature"))
        verdicts = {v["index"]: v["verdict"] for v in result.items}
        self.assertEqual(verdicts[1], "translated")
        self.assertEqual(verdicts[2], "leftOut")

    def test_handler_refusal_names_the_item(self):
        result = translate_fixture("core_unknown_feature", {
            "ExtrudeFeature": extrude_handler,
            "EmbossFeature": lambda ctx, step: Refusal("Not today."),
        })
        self.assertEqual((left_out(result)["index"], left_out(result)["reason"]), (2, "Not today."))

    def test_helper_body_is_skipped_and_kept_pending(self):
        result = translate_fixture("core_helper_body", {"ExtrudeFeature": extrude_handler})
        verdicts = {v["index"]: v["verdict"] for v in result.items}
        self.assertEqual(verdicts[2], "skipped")
        self.assertEqual([s["id"] for s in result.recipe["features"]], ["extrude_1"])
        assert_schema_ok(self, result.recipe)

    def test_suppressed_item_is_skipped_without_steps(self):
        result = translate_fixture("core_suppressed", {"ExtrudeFeature": extrude_handler})
        skipped = [v for v in result.items if v["index"] == 2][0]
        self.assertEqual((skipped["verdict"], skipped["steps"]), ("skipped", []))
        self.assertEqual(len(result.recipe["features"]), 1)

    def test_error_health_refuses(self):
        result = translate_fixture("core_error_health", {"ExtrudeFeature": extrude_handler})
        self.assertIsNone(result.recipe)
        self.assertIn("does not build", result.refusal["reason"])

    def test_a_capture_of_another_version_or_without_items_raises(self):
        with self.assertRaises(CaptureError):
            translate_fixture("core_bad_version")
        capture = load_capture("core_empty")
        del capture["items"]
        with self.assertRaises(CaptureError):
            translate(capture)

    def test_first_step_must_start_a_new_body(self):
        result = translate_fixture("core_suppressed", {"ExtrudeFeature": join_handler})
        self.assertIn("starts in a way", result.refusal["reason"])

    def test_ids_are_unique_and_short_and_labels_cut(self):
        capture = load_capture("core_unknown_feature")
        capture["items"][1]["name"] = "N" * 300
        table = {1: lambda c, s: StepResult.of([copy.deepcopy(_EXTRUDE), join_handler(c, s).steps[0]]),
                 2: join_handler}
        result = translate(capture, {"ExtrudeFeature": by_index(table), "EmbossFeature": by_index(table)})
        ids = [s["id"] for s in result.recipe["features"]]
        self.assertEqual(ids, ["extrude_1", "extrude_1_2", "extrude_2"])
        self.assertTrue(all(len(i) <= 64 for i in ids))
        self.assertEqual(len(result.recipe["features"][0]["label"]), 120)
        self.assertEqual(result.items[1]["steps"], ["extrude_1", "extrude_1_2"])

    def test_notes_make_a_note_verdict(self):
        def noting(ctx, step):
            ctx.note("Measured value used.")
            return extrude_handler(ctx, step)
        result = translate_fixture("core_suppressed", {"ExtrudeFeature": noting})
        self.assertEqual(result.items[1]["verdict"], "translatedWithNote")
        self.assertEqual(result.notes, ["Measured value used."])

    def test_over_cap_refuses(self):
        capture = load_capture("core_empty")
        capture["items"] = [dict(load_capture("core_suppressed")["items"][1], index=i) for i in range(1, 402)]
        table = lambda ctx, step: extrude_handler(ctx, step) if step.index == 1 else join_handler(ctx, step)
        result = translate(capture, {"ExtrudeFeature": table})
        self.assertIn("more than 400", result.refusal["reason"])

class SchemaCheckTest(unittest.TestCase):
    def test_app_example_passes(self):
        self.assertEqual(schema_check.check_recipe(_EXAMPLE), [])

    def test_bad_enum_fails(self):
        bad = copy.deepcopy(_EXAMPLE)
        bad["features"][0]["combine"] = "merge"
        self.assertTrue(schema_check.check_recipe(bad))

    def test_unknown_keyword_raises(self):
        with self.assertRaises(schema_check.UnsupportedKeyword):
            schema_check.validate(1, {"type": "number", "multipleOf": 2})


class HygieneTest(unittest.TestCase):
    def test_no_dashes_in_translator_sources(self):
        import os
        root = os.path.join(context.ADDIN_DIR, "lib", "translator")
        for name in os.listdir(root):
            if name.endswith(".py"):
                with open(os.path.join(root, name), encoding="utf-8") as f:
                    self.assertIsNone(re.search("[%s%s]" % (chr(0x2013), chr(0x2014)), f.read()), name)


if __name__ == "__main__":
    unittest.main()
