"""Planes, axes, faces and hole points of another component: the copy keeps them where they are, so every size that
acts on that component is marked, unless no size acts on that component or the capture cannot say where sizes act."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sized import table_of
from tests.translator_helpers import load_capture, verdict_of

from lib.translator import translate

SIZES = ["gap_mm", "depth_mm"]
COVER = {"token": "cmp_cover", "name": "Cover"}


def ref(kind="ConstructionPlane", slot="plane", **extra):
    return dict({"slot": slot, "type": kind, "token": "tok_cover", "component": dict(COVER), "path": "Cover:1"}, **extra)


def run(capture, ticked=SIZES):
    return translate(capture, size_table=table_of(capture, ticked))


def marked(result):
    """{ size: reason } for the sizes that are loose or were left out with a reason."""
    found = {d["name"]: d["reason"] for d in result.dropped if "not used" not in d["reason"]}
    found.update({d["name"]: d["reason"] for d in result.loose})
    return found


def mirror_with(edit):
    capture = load_capture("component_foreign_mirror")
    edit(capture, capture["items"][4]["data"]["plane"])
    return capture


def on_fixture(name, edit):
    """A fixture's items with the sizes of the mirror fixture; its first extrude reads `gap_mm`."""
    capture = load_capture(name)
    capture["parameters"] = load_capture("component_foreign_mirror")["parameters"]
    capture["items"][1]["data"]["params"] = {"side_one.distance": {"name": "d1", "expression": "gap_mm", "value": 10.0}}
    edit(capture)
    return capture


class MirrorPlaneTest(unittest.TestCase):
    def test_a_size_that_acts_on_the_component_of_the_plane_is_marked_and_the_others_are_not(self):
        result = run(load_capture("component_foreign_mirror"))
        self.assertIsNone(result.refusal)
        self.assertEqual(list(marked(result)), ["gap_mm"])
        self.assertIn("Mirror1", marked(result)["gap_mm"])
        self.assertIn("Cover", marked(result)["gap_mm"])
        self.assertEqual(result.fixed, [])

    def test_a_component_no_size_acts_on_marks_nothing(self):
        def edit(c, plane):
            plane["ref"]["component"] = {"token": "cmp_lid", "name": "Lid"}
        result = run(mirror_with(edit))
        self.assertEqual((marked(result), result.notes), ({}, []))

    def test_without_data_on_where_sizes_act_the_step_gets_a_note_and_no_size_is_marked(self):
        def edit(c, plane):
            for p in c["parameters"]["user"]:
                del p["dependents"]
        result = run(mirror_with(edit))
        self.assertEqual(marked(result), {})
        self.assertEqual(verdict_of(result, 4)["verdict"], "translatedWithNote")
        self.assertIn("Cover", verdict_of(result, 4)["note"])

    def test_a_plane_that_names_no_component_gets_a_note_and_no_size_is_marked(self):
        def edit(c, plane):
            plane.pop("ref")
        result = run(mirror_with(edit))
        self.assertEqual(marked(result), {})
        self.assertEqual(verdict_of(result, 4)["verdict"], "translatedWithNote")

    def test_without_a_size_table_nothing_is_marked_or_noted(self):
        result = translate(load_capture("component_foreign_mirror"))
        self.assertEqual(verdict_of(result, 4)["verdict"], "translated")

    def test_a_step_that_a_size_reaches_through_another_component_is_found_too(self):
        def edit(c, plane):
            user = {p["name"]: p for p in c["parameters"]["user"]}
            user["gap_mm"]["dependents"] = [{"name": "d1", "kind": "feature", "component": "cmp_tray",
                                             "feature": "Extrude1"},
                                            {"name": "d5", "kind": "sketchDimension", "component": "cmp_root",
                                             "sketch": "Layout", "sketch_token": "sk_layout"}]
            c["items"][3]["sketch_inputs"] = [{"token": "sk_layout", "name": "Layout"}]
            c["items"][3]["component"] = "cmp_cover"
        self.assertIn("gap_mm", marked(run(mirror_with(edit))))


class AxisTest(unittest.TestCase):
    def pattern(self, **extra):
        def edit(capture):
            axis = capture["items"][4]["data"]["axis"]
            axis.update(assembly=True, ref=ref("ConstructionAxis", "axis"), **extra)
        return run(on_fixture("cpattern_full", edit))

    def test_a_circular_pattern_around_an_axis_of_another_component_marks_its_sizes(self):
        result = self.pattern()
        self.assertIsNone(result.refusal)
        self.assertIn("CircularPattern1", marked(result)["gap_mm"])
        self.assertNotIn("depth_mm", marked(result))

    def test_a_revolve_about_an_axis_of_another_component_marks_its_sizes(self):
        def edit(capture):
            capture["items"][1]["data"]["axis"].update(assembly=True, ref=ref("ConstructionAxis", "axis"))
        result = run(on_fixture("revolve_full", edit))
        self.assertIsNone(result.refusal)
        self.assertIn("Revolve1", marked(result)["gap_mm"])


class HolePointsTest(unittest.TestCase):
    def test_a_hole_on_points_of_another_component_marks_its_sizes(self):
        def edit(capture):
            capture["items"][3]["data"]["position_refs"] = [ref("SketchPoint", "positions.0"),
                                                            ref("SketchPoint", "positions.1")]
        result = run(on_fixture("hole_through", edit))
        self.assertIsNone(result.refusal)
        self.assertIn("Hole1", marked(result)["gap_mm"])
        self.assertEqual(len([d for d in result.loose if d["name"] == "gap_mm"]), 1)


class ReachTest(unittest.TestCase):
    def test_a_face_of_another_component_an_extrude_reaches_to_marks_its_sizes(self):
        def edit(capture):
            side = capture["items"][3]["data"]["side_one"]
            side.update(entity_type="BRepFace", face_point=[3, 3, 12], assembly=True, ref=ref("BRepFace", "side_one"))
        result = run(on_fixture("extrude_to_plane", edit))
        self.assertIsNone(result.refusal)
        self.assertIn("Extrude2", marked(result)["gap_mm"])
