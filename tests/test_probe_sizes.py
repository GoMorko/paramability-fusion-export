import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import table, user
from tests.test_probe_plan import MODEL, PARAMS

from lib.export_plan.probe_flow import sizes_to_try
from lib.export_plan.probe_flow.sizes import MAX_EXTRA_SIZES, extra_sizes, kept_sizes
from lib.translator.sizes import probed_sizes


class WhichSizesGetTriesTest(unittest.TestCase):
    def setUp(self):
        self.table = table(PARAMS, ["count", "cube", "off", "height", "wall"], MODEL)

    def test_sizes_that_reach_a_sketch_dimension_or_plane_are_driven(self):
        self.assertEqual(probed_sizes(self.table), ["count", "cube", "height"])

    def test_kept_are_the_free_sizes_of_the_recipe_plus_the_driven_ones(self):
        self.assertEqual(kept_sizes(self.table, ["off"]), ["count", "cube", "off", "height"])
        self.assertEqual(kept_sizes(self.table, []), ["count", "cube", "height"])

    def test_the_ticked_sizes_nothing_ties_to_a_sketch_are_the_guessed_ones(self):
        kept = kept_sizes(self.table, ["off"])
        self.assertEqual(extra_sizes(self.table, kept), ["wall"])

    def test_at_most_a_few_ticked_sizes_are_tried_on_a_guess(self):
        names = ["p%d" % n for n in range(MAX_EXTRA_SIZES + 3)]
        many = table([user(n, "5 mm", 5) for n in names], names)
        self.assertEqual(extra_sizes(many, ["p0"]), names[1:MAX_EXTRA_SIZES + 1])

    def test_the_sizes_to_try_are_the_kept_and_the_guessed_ones_as_probe_dicts(self):
        sizes, extra = sizes_to_try(self.table, PARAMS, ["off"])
        self.assertEqual([s["param"] for s in sizes], ["count", "cube", "off", "height", "wall"])
        self.assertEqual(extra, ["wall"])

    def test_a_size_that_is_neither_kept_nor_ticked_gets_no_try(self):
        sizes, extra = sizes_to_try(table(PARAMS, ["cube"], MODEL), PARAMS, [])
        self.assertEqual([s["param"] for s in sizes], ["cube"])
        self.assertEqual(extra, [])


if __name__ == "__main__":
    unittest.main()
