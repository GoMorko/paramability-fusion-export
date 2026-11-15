import unittest

from tests import context  # noqa: F401
from lib.params import labels, size_table


def p(name, comment="", unit="mm", value=2.0):
    return dict(name=name, value=value, unit=unit, comment=comment, is_favorite=False, kind="length")


class CommentLabelTest(unittest.TestCase):
    def test_a_short_comment_is_the_label(self):
        self.assertEqual(labels.comment_label("pipe wall thickness"), "Pipe wall thickness")

    def test_the_first_sentence_and_no_range_hint(self):
        self.assertEqual(labels.comment_label("Plate length. Range 30 to 100 mm"), "Plate length")
        self.assertEqual(labels.comment_label("Wall [1..6]"), "Wall")
        self.assertEqual(labels.comment_label("Hole at 19.5 mm\nsecond line"), "Hole at 19.5 mm")

    def test_a_long_description_is_not_a_label(self):
        self.assertEqual(labels.comment_label("Amount of ceramic cubes that the filter box should fit in X"), "")
        self.assertEqual(labels.comment_label("[1..6]"), "")
        self.assertEqual(labels.comment_label(None), "")


class NameWordsTest(unittest.TestCase):
    def test_names_become_plain_words_without_the_unit(self):
        for name, unit, want in (
                ("BaseCup_midExtrude_offset__mm", "mm", "Base cup mid extrude offset"),
                ("FilterBox_$_width__contains_CeramicMedium", "", "Filter box width contains ceramic medium"),
                ("_CeramicMedium__Cube_width_unitless", "", "Ceramic medium cube width"),
                ("wall_thickness", "mm", "Wall thickness"),
                ("T1_Width", "mm", "T1 width"),
                ("WALL_COUNT", "", "Wall count"),
                ("Hole_in", "in", "Hole")):
            self.assertEqual(labels.name_words(name, unit), want, name)


class AssignTest(unittest.TestCase):
    def test_comment_first_then_name(self):
        got = labels.assign([("a", "Box width", "mm"), ("Hole_depth_mm", "", "mm")])
        self.assertEqual(got, {"a": "Box width", "Hole_depth_mm": "Hole depth"})

    def test_sizes_that_would_read_alike_do_not(self):
        got = labels.assign([("T1_Width", "Box width", "mm"), ("T2_Width", "Box width", "mm"), ("Depth", "", "mm")])
        self.assertEqual(got, {"T1_Width": "T1 width", "T2_Width": "T2 width", "Depth": "Depth"})
        same = labels.assign([("a_b", "", "mm"), ("a$b", "", "mm")])
        self.assertEqual(same, {"a_b": "A b (a_b)", "a$b": "A b (a$b)"})

    def test_labels_made_alike_by_the_cut_to_the_label_length_are_told_apart(self):
        long = "x" * (labels.defaults.LABEL_MAX + 10)
        for pairs in ((long + "_a", long + "_b"), ("x" * 100 + "_a", "x" * 100 + "$a")):
            got = labels.assign([(name, "", "mm") for name in pairs])
            self.assertEqual(len({text.lower() for text in got.values()}), 2)
            self.assertTrue(all(0 < len(text) <= labels.defaults.LABEL_MAX for text in got.values()))


class TableLabelTest(unittest.TestCase):
    def test_the_recipe_size_gets_the_words_and_the_entry_keeps_the_fusion_name(self):
        params = [p("FilterBox_width_mm", "Outer width"), p("Pipe_wall_mm")]
        table = size_table.build(params, ["FilterBox_width_mm", "Pipe_wall_mm"])
        self.assertEqual(table.sizes["FilterBox_width_mm"]["label"], "Outer width")
        self.assertEqual(table.sizes["Pipe_wall_mm"]["label"], "Pipe wall")
        self.assertEqual(table.entry("Pipe_wall_mm").label, "Pipe_wall_mm")

    def test_only_the_sizes_count_for_alike_labels(self):
        params = [p("T1_Width", "Box width"), p("T2_Width", "Box width")]
        self.assertEqual(size_table.build(params, ["T1_Width"]).sizes["T1_Width"]["label"], "Box width")
        both = size_table.build(params, ["T1_Width", "T2_Width"])
        self.assertEqual([both.sizes[n]["label"] for n in ("T1_Width", "T2_Width")], ["T1 width", "T2 width"])


if __name__ == "__main__":
    unittest.main()
