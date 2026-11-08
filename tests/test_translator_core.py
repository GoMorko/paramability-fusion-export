import copy
import json
import re
import unittest

from tests import context  # noqa: F401
from tests import schema_check
from tests.translator_helpers import (
    assert_schema_ok, fixture_path, load_capture, steps_of, translate_fixture,
)

from lib.translator import CaptureError, Refusal, translate
from lib.translator.context import Context

with open(fixture_path("schema_example_v10"), encoding="utf-8") as _f:
    _EXAMPLE = json.load(_f)
_EXTRUDE = _EXAMPLE["features"][0]


def extrude_handler(item, ctx):
    return [copy.deepcopy(_EXTRUDE)]


def join_handler(item, ctx):
    step = copy.deepcopy(_EXTRUDE)
    step["combine"] = "add"
    return [step]


def by_index(table):
    return lambda item, ctx: table[item["index"]](item, ctx)


class CoreTest(unittest.TestCase):
    def test_empty_timeline_refuses(self):
        result = translate_fixture("core_empty")
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal["reason"], "Nothing in the timeline makes this body.")

    def test_unknown_feature_stops_the_walk_at_that_item(self):
        result = translate_fixture("core_unknown_feature", {"ExtrudeFeature": extrude_handler})
        self.assertIsNone(result.recipe)
        self.assertEqual((result.refusal["index"], result.refusal["type"]), (2, "EmbossFeature"))
        self.assertIn("emboss", result.refusal["reason"])
        verdicts = {v["index"]: v["verdict"] for v in result.items}
        self.assertEqual(verdicts[1], "translated")
        self.assertEqual(verdicts[2], "unsupported")

    def test_handler_refusal_names_the_item(self):
        result = translate_fixture("core_unknown_feature", {
            "ExtrudeFeature": extrude_handler,
            "EmbossFeature": lambda item, ctx: Refusal("Not today."),
        })
        self.assertEqual(result.refusal["reason"], "Not today.")

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
        self.assertEqual(result.refusal["reason"], "This step does not build in Fusion.")

    def test_bad_version_raises(self):
        with self.assertRaises(CaptureError):
            translate_fixture("core_bad_version")

    def test_missing_keys_raise(self):
        capture = load_capture("core_empty")
        del capture["items"]
        with self.assertRaises(CaptureError):
            translate(capture)

    def test_first_step_must_start_a_new_body(self):
        result = translate_fixture("core_suppressed", {"ExtrudeFeature": join_handler})
        self.assertEqual(result.refusal["reason"], "The body starts in a way that cannot be copied.")

    def test_ids_are_unique_and_short_and_labels_cut(self):
        capture = load_capture("core_unknown_feature")
        capture["items"][1]["name"] = "N" * 300
        table = {1: lambda i, c: [copy.deepcopy(_EXTRUDE), join_handler(i, c)[0]],
                 2: join_handler}
        result = translate(capture, {"ExtrudeFeature": by_index(table), "EmbossFeature": by_index(table)})
        ids = [s["id"] for s in result.recipe["features"]]
        self.assertEqual(ids, ["extrude_1", "extrude_1_2", "extrude_2"])
        self.assertTrue(all(len(i) <= 64 for i in ids))
        self.assertEqual(len(result.recipe["features"][0]["label"]), 120)
        self.assertEqual(result.items[1]["steps"], ["extrude_1", "extrude_1_2"])

    def test_notes_make_a_note_verdict(self):
        def noting(item, ctx):
            ctx.note("Measured value used.")
            return extrude_handler(item, ctx)
        result = translate_fixture("core_suppressed", {"ExtrudeFeature": noting})
        self.assertEqual(result.items[1]["verdict"], "translatedWithNote")
        self.assertEqual(result.notes, ["Measured value used."])

    def test_envelope_and_schema(self):
        result = translate_fixture("core_suppressed", {"ExtrudeFeature": extrude_handler})
        self.assertEqual({k: result.recipe[k] for k in ("schema", "version")}, {"schema": "paramability.recipe", "version": 10})
        self.assertNotIn("sizes", result.recipe)
        assert_schema_ok(self, result.recipe)

    def test_over_cap_refuses(self):
        capture = load_capture("core_empty")
        capture["items"] = [dict(load_capture("core_suppressed")["items"][1], index=i) for i in range(1, 402)]
        table = lambda item, ctx: [copy.deepcopy(_EXTRUDE)] if item["index"] == 1 else join_handler(item, ctx)
        result = translate(capture, {"ExtrudeFeature": table})
        self.assertIn("more than 400", result.refusal["reason"])

    def test_context_steps_of(self):
        ctx = Context(load_capture("core_empty"))
        ctx.add_steps({"index": 4, "name": "A"}, [{"kind": "hole"}])
        ctx.add_steps({"index": 4, "name": "A"}, [{"kind": "hole"}])
        self.assertEqual(ctx.steps_of(4), ["hole_4", "hole_4_2"])
        self.assertEqual(ctx.steps_of(9), [])


class SchemaCheckTest(unittest.TestCase):
    def test_app_example_passes(self):
        self.assertEqual(schema_check.check_recipe(_EXAMPLE), [])

    def test_wrong_version_fails(self):
        bad = dict(_EXAMPLE, version=11)
        self.assertTrue(schema_check.check_recipe(bad))

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
