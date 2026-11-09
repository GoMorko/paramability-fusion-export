"""Loose sizes: a size that some value cannot follow stays free with a warning, and that value keeps its number."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sketch_motion import BOX, BOX_SIZES, expr, motion_of
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of

from lib.params import size_table
from lib.translator import translate


def run(motion, loose=True, edit_model=None, plain=False):
    capture = load_capture(BOX)
    params = capture["parameters"]
    if edit_model:
        edit_model(params["model"])
    table = size_table.build(params["user"], BOX_SIZES, params["model"], capture.get("design_units", "mm"))
    return translate(capture, size_table=table, motion=motion, loose=loose, plain=plain)


def free(result):
    return sorted(n for n, size in result.recipe["sizes"].items() if "value" in size)


def outer(result):
    return steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]


class LooseTest(unittest.TestCase):
    def test_a_stuck_value_keeps_its_number_and_its_sizes_stay_free_with_the_reason(self):
        def edit(values):
            values["1/p0/l0/width"] = {"stuck": ["box_count", "cube_mm"], "cause": "curve", "sketch": "Sketch1"}

        strict, loose = run(motion_of(BOX, edit), loose=False), run(motion_of(BOX, edit))
        self.assertEqual(sorted(f["name"] for f in strict.fixed), ["box_count", "cube_mm"])
        self.assertEqual(loose.fixed, [])
        self.assertEqual({f["name"]: f["reason"] for f in loose.loose}["cube_mm"],
                         "cube_mm may give unexpected results: it moves Sketch1 along a curve, which cannot be "
                         "copied yet.")
        self.assertIn("cube_mm", free(loose))
        self.assertEqual((outer(loose)["width"], expr(outer(loose)["height"])), (80.0, "depth_mm"))
        hole = steps_of(loose.recipe, "hole")[0]["origin"][0]
        self.assertEqual(expr(hole), "-0.5 * box_width_mm + pipe_offset_mm")
        assert_schema_ok(self, loose.recipe)

    def test_a_stuck_value_follows_the_sizes_that_still_move_it(self):
        def edit(values):
            values["1/p0/l0/width"] = {"stuck": ["pipe_offset_mm"], "cause": "shape", "sketch": "Sketch1",
                                       "rest": values["1/p0/l0/width"]}

        result = run(motion_of(BOX, edit))
        self.assertEqual([f["name"] for f in result.loose], ["pipe_offset_mm"])
        self.assertEqual(expr(outer(result)["width"]), "box_width_mm")
        self.assertIn("pipe_offset_mm", free(result))

    def test_a_loose_size_that_no_formula_reads_is_listed_as_fixed(self):
        result = run(None)
        self.assertEqual(result.loose, [])
        self.assertIn("depth_mm stays fixed: it changes a sketch", {f["name"]: f["reason"] for f in result.fixed}[
            "depth_mm"])
        self.assertNotIn("depth_mm", free(result))
        self.assertFalse([n for n in result.notes if "depth_mm is not used" in n])

    def test_a_plain_translation_drops_a_doubtful_size_no_formula_reads_instead_of_fixing_it(self):
        result = run(None, plain=True)
        self.assertEqual(result.fixed, [])
        self.assertNotIn("depth_mm", free(result))
        self.assertIn("depth_mm is not used by any copied step, so it is not a size.", result.notes)

    def test_a_size_that_moves_a_joint_stays_free_with_the_reason(self):
        def joint(model):
            depth = next(m for m in model if "depth_mm" in m.get("expression", ""))
            model.append(dict(depth, name="joint_offset", created_by={"kind": "joint"}))

        result = run(motion_of(BOX), edit_model=joint)
        self.assertEqual({f["name"]: f["reason"] for f in result.loose},
                         {"depth_mm": "depth_mm may give unexpected results: it moves a joint."})
        self.assertEqual(expr(outer(result)["height"]), "depth_mm")
        self.assertEqual([f["name"] for f in run(motion_of(BOX), loose=False, edit_model=joint).fixed], ["depth_mm"])


if __name__ == "__main__":
    unittest.main()
