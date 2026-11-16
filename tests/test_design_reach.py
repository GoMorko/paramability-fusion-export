"""Reachability in the shared layer (`design_model/reach.py`): which ticked sizes may move a sketch, a plane, a face or
a joint. The functions read the size table and the capture only; what a copy does about those sizes is not tested
here."""
import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import model, table, user

from lib.design_model import reach

FRAME = {"origin": [0, 0, 5], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
PARAMS = [user("w_mm", "10 mm", 10), user("h_mm", "20 mm", 20), user("gap_mm", "3 mm", 3), user("t_mm", "5 mm", 5)]
NAMES = [p["name"] for p in PARAMS]


def sized_table(models, ticked=None, links=()):
    found = table(PARAMS, ticked or NAMES, models)
    return found.with_links(list(links)) if links else found


def step(index, name, kind="ExtrudeFeature", reads=None, **more):
    """A timeline item of the body's component whose `data.params` read the given expressions."""
    params = {"p%d" % n: {"name": "d_%s_%d" % (name, n), "expression": text, "value": 1}
              for n, text in enumerate(reads or [])}
    return dict({"index": index, "name": name, "type": kind, "suppressed": False, "in_target_component": True,
                 "data": {"params": params}}, **more)


def plane(token, built_on=(), definition="Offset from plane", **more):
    return dict({"entity_type": "ConstructionPlane", "token": token, "definition": definition,
                 "built_on": list(built_on)}, **more)


FACE = {"entity_type": "BRepFace", "token": "f1"}
ORIGIN_PLANE = {"entity_type": "ConstructionPlane", "origin": True, "built_on": []}


class ModelParameterReachTest(unittest.TestCase):
    def test_a_joint_names_the_ticked_sizes_it_reads_and_only_those_asked(self):
        found = sized_table([model("j1", "gap_mm * 2", 6, kind="joint"), model("d1", "w_mm", 10)])
        self.assertEqual(set(reach.joint_reasons(found)), {"gap_mm"})
        self.assertEqual(reach.joint_reasons(found, ["w_mm"]), {})

    def test_a_sketch_dimension_is_found_by_its_maker_or_by_its_role_when_the_maker_is_the_sketch(self):
        named = model("d1", "w_mm", 10, sketch="Sketch1")
        by_role = dict(model("d2", "h_mm", 20, kind="other", sketch="Sketch1"), role="Linear Dimension-2")
        other = model("d3", "gap_mm", 3, kind="other", sketch="Sketch1")
        found = sized_table([named, by_role, other])
        self.assertEqual(reach.sketch_params(found, "Sketch1"), ["d1", "d2"])
        self.assertEqual(reach.sketch_params(found, ""), [])
        self.assertEqual(reach.sketch_sizes(found, "Sketch1"), ["w_mm", "h_mm"])

    def test_a_sketch_drawn_around_another_component_reads_the_sizes_that_may_reach_it(self):
        link = {"param": "gap_mm", "sketch": "Sketch1", "component": "Lid", "via": "x"}
        found = sized_table([model("d1", "w_mm", 10, sketch="Sketch1")], links=[link])
        self.assertEqual(reach.linked_sizes(found, "Sketch1"), ["gap_mm"])
        self.assertEqual(reach.linked_sizes(found, "Sketch2"), [])
        self.assertEqual(reach.sketch_sizes(found, "Sketch1"), ["w_mm", "gap_mm"])

    def test_construction_sizes_are_all_of_a_kind_or_those_of_one_token(self):
        found = sized_table([model("d1", "w_mm", 10, kind="constructionPlane", token="p1"),
                             model("d2", "h_mm", 20, kind="constructionPlane", token="p2"),
                             model("d3", "gap_mm", 3, kind="constructionAxis", token="a1")])
        self.assertEqual(reach.construction_sizes(found, "constructionPlane"), ("w_mm", "h_mm"))
        self.assertEqual(reach.construction_sizes(found, "constructionPlane", "p2"), ("h_mm",))
        self.assertEqual(reach.construction_sizes(found, "constructionAxis"), ("gap_mm",))

    def test_the_sizes_the_probe_must_measure_reach_a_dimension_a_plane_or_another_component(self):
        link = {"param": "t_mm", "sketch": "Sketch1", "component": "Lid", "via": "x"}
        found = sized_table([model("d1", "w_mm", 10, sketch="Sketch1"),
                             model("d2", "h_mm", 20, kind="constructionPlane", token="p1"),
                             model("d3", "gap_mm", 3, kind="feature")], links=[link])
        self.assertEqual(reach.probed_sizes(found), ["w_mm", "h_mm", "t_mm"])

    def test_a_sketch_text_height_is_found_by_the_reader_note_a_maker_or_an_unknown_maker(self):
        text = {"text": True, "sketch": "Label", "text_params": ["d9"]}
        item = {"index": 1, "name": "Emboss1", "type": "EmbossFeature", "data": {"profiles": [text]}}
        found = sized_table([model("d9", "h_mm", 20, kind="other")])
        self.assertEqual(reach.text_sizes(found, {"items": [item]}), {"h_mm": "Label"})
        unknown = dict(text, text_params=[], text_params_unknown=True)
        by_maker = sized_table([model("d9", "w_mm", 10, kind="sketchText", sketch="Label")])
        self.assertEqual(reach.text_sizes(by_maker, {"items": [dict(item, data={"profiles": [unknown]})]}),
                         {"w_mm": "Label"})
        self.assertEqual(reach.text_sizes(found, {"items": [dict(item, data={"profiles": [{"sketch": "Label"}]})]}),
                         {})


class OffsetPlaneTest(unittest.TestCase):
    def setUp(self):
        self.models = [model("d1", "w_mm", 10, kind="constructionPlane", token="p1")]

    def test_the_own_distance_of_an_offset_plane_is_the_one_parameter_it_made(self):
        found = sized_table(self.models)
        self.assertEqual(reach.offset_param(found, plane("p1", [FACE]))["name"], "d1")

    def test_a_plane_with_a_second_size_or_no_single_base_or_no_offset_has_no_own_distance(self):
        two = sized_table(self.models + [model("d2", "h_mm", 20, kind="constructionPlane", token="p1")])
        self.assertIsNone(reach.offset_param(two, plane("p1", [FACE])))
        found = sized_table(self.models)
        self.assertIsNone(reach.offset_param(found, plane("p1", [FACE, FACE])))
        self.assertIsNone(reach.offset_param(found, plane("p1", [FACE], definition="Angle")))
        self.assertIsNone(reach.offset_param(found, dict(plane("p1", [FACE]), token="")))
        self.assertIsNone(reach.offset_param(None, plane("p1", [FACE])))

    def test_a_plane_sits_on_the_part_through_a_face_but_not_through_the_origin(self):
        self.assertTrue(reach.on_part(FACE))
        self.assertTrue(reach.on_part(plane("p1", [plane("p0", [FACE])])))
        self.assertFalse(reach.on_part(ORIGIN_PLANE))
        self.assertFalse(reach.on_part(plane("p1", [ORIGIN_PLANE])))
        self.assertFalse(reach.on_part(plane("p1", [])))
        self.assertFalse(reach.on_part(dict(FACE, foreign=True)))

    def test_the_offset_planes_a_step_places_are_followed_through_a_chain(self):
        found = sized_table(self.models)
        capture = {"items": [{"index": 1, "data": {"start": plane("p9", [plane("p1", [FACE])])}}]}
        self.assertEqual(reach.placed_offsets(found, capture), {"d1"})


class ConstructionFixesTest(unittest.TestCase):
    def setUp(self):
        self.table = sized_table([model("d1", "w_mm", 10, kind="constructionPlane", token="p1"),
                                  model("d2", "h_mm", 20, kind="constructionAxis", token="a1")])

    def fixes(self, data):
        return reach.construction_fixes(self.table, {"name": "Mirror1", "data": data})

    def test_a_plane_or_axis_the_step_uses_names_its_sizes(self):
        found = self.fixes({"plane": {"entity_type": "ConstructionPlane", "token": "p1", "built_on": []},
                            "axis": {"entity_type": "ConstructionAxis", "token": "a1"}})
        self.assertEqual([names for names, _ in found], [("w_mm",), ("h_mm",)])

    def test_an_offset_plane_the_step_places_by_its_own_distance_is_left_out(self):
        record = plane("p1", [FACE])
        self.assertEqual(self.fixes({"start": record}), [])
        self.assertEqual(len(self.fixes({"profile_plane": record})), 1)

    def test_a_record_without_a_token_stands_for_every_one_of_its_kind(self):
        found = self.fixes({"normal": [0, 0, 1], "token": "", "other": {"entity_type": "ConstructionPlane"}})
        self.assertEqual([names for names, _ in found], [("w_mm",)])

    def test_geometry_of_another_component_names_no_sizes_here(self):
        self.assertEqual(self.fixes({"plane": {"entity_type": "ConstructionPlane", "token": "p1", "assembly": True}}),
                         [])


class SketchPlaneTest(unittest.TestCase):
    def setUp(self):
        self.models = [model("d1", "w_mm", 10, kind="constructionPlane", token="p1")]
        self.timeline = [step(0, "Base", reads=["h_mm"]), step(1, "Cut", reads=["gap_mm"]),
                         step(2, "Boss", reads=["t_mm"])]
        self.table = sized_table(self.models)

    def profile(self, reference, **more):
        return dict({"sketch": "Sketch9", "frame": FRAME, "reference": reference}, **more)

    def test_a_sketch_on_a_face_may_move_with_every_size_read_before_it(self):
        found = reach.placement_sizes(self.table, self.timeline, self.profile({"kind": "face"}), 2)
        self.assertEqual(found, ["h_mm", "gap_mm"])

    def test_a_sketch_on_an_origin_plane_or_an_unknown_one_is_still(self):
        origin = {"kind": "constructionPlane", "origin": True}
        self.assertEqual(reach.placement_sizes(self.table, self.timeline, self.profile(origin), 2), [])
        self.assertEqual(reach.placement_sizes(self.table, self.timeline, {"sketch": "Sketch9"}, 2), [])
        self.assertEqual(reach.placement_sizes(None, self.timeline, self.profile({"kind": "face"}), 2), [])

    def test_a_sketch_of_another_component_or_on_a_body_face_names_no_size(self):
        for more in ({"foreign": True}, {"borrowed": "Lid"}, {"face": True}):
            self.assertEqual(reach.placement_sizes(self.table, self.timeline, self.profile({"kind": "face"}, **more), 2),
                             [])

    def test_a_construction_plane_adds_its_own_sizes_and_bounds_the_steps_by_its_making(self):
        reference = {"kind": "constructionPlane", "token": "p1", "made_by": 1, "definition": "Offset from plane",
                     "built_on": [FACE]}
        found = reach.placement_sizes(self.table, self.timeline, self.profile(reference), 2)
        self.assertEqual(found, ["w_mm", "h_mm"])

    def test_a_construction_plane_of_an_older_capture_counts_as_on_the_part_unless_its_frame_lies_on_an_origin(self):
        old = {"kind": "constructionPlane", "token": "p1"}
        self.assertEqual(reach.placement_sizes(self.table, self.timeline, self.profile(old), 2),
                         ["w_mm", "h_mm", "gap_mm"])
        flat = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        self.assertEqual(reach.placement_sizes(self.table, self.timeline, self.profile(old, frame=flat), 2),
                         ["w_mm"])

    def test_suppressed_steps_and_steps_of_other_components_are_not_read(self):
        timeline = [dict(self.timeline[0], suppressed=True), dict(self.timeline[1], in_target_component=False),
                    dict(self.timeline[2], in_target_component=False, helper_of="Base")]
        self.assertEqual(reach.placement_sizes(self.table, timeline, self.profile({"kind": "face"}), 3), ["t_mm"])

    def test_the_sizes_the_probe_must_try_are_those_of_every_profile(self):
        capture = {"items": self.timeline}
        profiles = [(1, self.profile({"kind": "face"})), (2, self.profile({"kind": "face"}))]
        self.assertEqual(reach.placement_driven(capture, self.table, profiles), ["h_mm", "gap_mm"])

    def test_a_face_outline_or_a_hole_without_a_sketch_may_change_with_every_size_read_before_the_step(self):
        cut = self.timeline[2]
        self.assertEqual(reach.sketch_plane_sizes(self.table, self.timeline, cut, {"face": True}),
                         ["h_mm", "gap_mm"])
        self.assertEqual(reach.hole_plane_sizes(self.table, self.timeline, cut, {}), ["h_mm", "gap_mm"])
        self.assertEqual(reach.sketch_plane_sizes(None, self.timeline, cut, {"face": True}), [])

    def test_the_holes_of_a_sketch_follow_its_reference_and_one_not_read_counts_as_on_a_face(self):
        cut = step(3, "Hole", kind="HoleFeature")
        data = {"sketch": "Sketch9", "sketch_frame": FRAME}
        self.assertEqual(reach.hole_plane_sizes(self.table, self.timeline, cut, data), ["h_mm", "gap_mm", "t_mm"])
        origin = dict(data, reference={"kind": "constructionPlane", "origin": True})
        self.assertEqual(reach.hole_plane_sizes(self.table, self.timeline, cut, origin), [])


class FaceReachTest(unittest.TestCase):
    def reach_record(self, **more):
        return dict({"kind": "toEntity", "token": "f1", "entity_type": "BRepFace",
                     "plane": {"point": [0, 0, 5], "normal": [0, 0, 1]}}, **more)

    def item(self, **record):
        return step(2, "Boss", data={"start": self.reach_record(**record)})

    def test_a_flat_face_or_plane_of_the_part_that_a_step_reaches_to_may_move(self):
        found = reach.moving_reaches(self.item())
        self.assertEqual([(slot, rec["token"]) for slot, rec in found], [("start", "f1")])
        built = self.item(entity_type="ConstructionPlane", built_on=[FACE], definition="Offset from plane")
        self.assertEqual(len(reach.moving_reaches(built)), 1)

    def test_a_reach_the_probe_cannot_find_again_or_that_cannot_move_is_left_out(self):
        for edit in ({"token": ""}, {"foreign": True}, {"assembly": True}, {"kind": "distance"}, {"plane": None},
                     {"plane": {"point": [0, 0], "normal": [0, 0, 1]}},
                     {"entity_type": "ConstructionPlane", "origin": True}, {"entity_type": "BRepEdge"}):
            self.assertEqual(reach.moving_reaches(self.item(**edit)), [], edit)
        for edit in ({"suppressed": True}, {"in_target_component": False}):
            self.assertEqual(reach.moving_reaches(dict(self.item(), **edit)), [])
        self.assertEqual(reach.moving_reaches(dict(self.item(), data={"read_error": "x", "start": {}})), [])

    def test_a_face_may_move_with_the_sizes_read_before_the_step_and_a_plane_with_its_own_too(self):
        found = sized_table([model("d1", "w_mm", 10, kind="constructionPlane", token="p1")])
        timeline = [step(0, "Base", reads=["h_mm"]), step(1, "Cut", reads=["gap_mm"]), step(2, "Boss", reads=["t_mm"])]
        boss = timeline[2]
        self.assertEqual(reach.reach_sizes(found, timeline, boss, FACE), ["h_mm", "gap_mm"])
        made_at_one = plane("p1", [FACE], made_by=1)
        self.assertEqual(reach.reach_sizes(found, timeline, boss, made_at_one), ["w_mm", "h_mm"])
        self.assertEqual(reach.reach_sizes(None, timeline, boss, FACE), [])
        capture = {"items": timeline[:2] + [dict(boss, data={"start": self.reach_record()})]}
        self.assertEqual(reach.reach_driven(capture, found), ["h_mm", "gap_mm"])


class ProfileAndStepSizesTest(unittest.TestCase):
    def setUp(self):
        self.models = [model("d1", "w_mm", 10, sketch="Sketch1"), model("d2", "h_mm", 20, sketch="Sketch2"),
                       dict(model("d3", "gap_mm", 3, kind="other", sketch=""), role="")]
        self.link = {"param": "t_mm", "sketch": "Sketch1", "component": "Lid", "via": "x"}
        self.table = sized_table(self.models, links=[self.link])

    def test_the_sizes_of_a_sketch_are_its_dimensions_and_the_geometry_it_is_drawn_around(self):
        self.assertEqual(reach.profile_sizes(self.table, {"sketch": "Sketch1"}), ["w_mm", "t_mm"])

    def test_with_the_sketch_graph_the_dimensions_of_the_graph_are_read_instead_of_the_model_parameters(self):
        record = {"dimensions": [{"param": "d2"}, {"param": None, "reads": ["gap_mm"]}, "x"]}
        self.assertEqual(reach.profile_sizes(self.table, {"sketch": "Sketch1"}, record), ["h_mm", "gap_mm", "t_mm"])

    def test_an_outline_of_another_component_gives_no_sizes_even_when_a_sketch_shares_its_name(self):
        for other in ({"sketch": "Sketch1", "foreign": True}, {"sketch": "Sketch1", "borrowed": "Lid"}):
            self.assertEqual(reach.profile_sizes(self.table, other), [])
        self.assertEqual(reach.profile_sizes(None, {"sketch": "Sketch1"}), [])

    def test_a_step_reads_its_own_values_the_sketches_of_its_outlines_and_their_graphs(self):
        data = {"params": {"extent": {"name": "d3", "expression": "gap_mm", "value": 3}},
                "profiles": [{"sketch": "Sketch1"}]}
        item = {"index": 3, "name": "Extrude1", "type": "ExtrudeFeature", "data": data}
        self.assertEqual(reach.step_sizes(self.table, {}, item), ["w_mm", "gap_mm", "t_mm"])
        graphs = {"sketch_graphs": [{"sketch": "Sketch1", "dimensions": [{"param": "d2"}]}, {"sketch": "Other"}]}
        self.assertEqual(reach.step_sizes(self.table, graphs, item), ["w_mm", "h_mm", "gap_mm", "t_mm"])
        self.assertEqual(reach.step_sizes(None, graphs, item), [])

    def test_the_sketch_of_a_hole_step_and_the_dimensions_of_a_borrowed_outline_count(self):
        hole = {"index": 3, "name": "Hole1", "type": "HoleFeature", "data": {"sketch": "Sketch2"}}
        self.assertEqual(reach.step_sizes(self.table, {}, hole), ["h_mm"])
        borrowed = {"sketch": "Sketch1", "borrowed": "Lid",
                    "sketch_params": [{"name": "d7", "reads": ["gap_mm"]}, {"name": "d8"}, "x"]}
        item = {"index": 3, "name": "Sweep1", "type": "SweepFeature", "data": {"profiles": [borrowed]}}
        self.assertEqual(reach.step_sizes(self.table, {}, item), ["gap_mm"])

    def test_an_item_reads_the_values_of_a_step_a_sketch_and_the_planes_it_made(self):
        sketch = {"index": 0, "name": "Sketch1", "type": "Sketch"}
        made = model("d2", "h_mm", 20, kind="constructionPlane")
        made["created_by"]["name"] = "Plane1"
        found = sized_table([model("d1", "w_mm", 10, sketch="Sketch1"), made])
        self.assertEqual(reach.item_reads(found, sketch), {"w_mm"})
        self.assertEqual(reach.item_reads(found, {"index": 1, "name": "Plane1", "type": "ConstructionPlane"}),
                         {"h_mm"})
        self.assertEqual(reach.item_reads(found, step(2, "Pad", reads=["gap_mm * 2"])), {"gap_mm"})


if __name__ == "__main__":
    unittest.main()
