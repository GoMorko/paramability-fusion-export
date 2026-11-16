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
        self.assertFalse(reach.on_part(dict(FACE, foreign=True)))

    def test_a_plane_whose_base_is_unknown_counts_as_on_the_part(self):
        # Nothing read, a chain deeper than the reader goes, or an entity of another component in the chain.
        self.assertTrue(reach.on_part(plane("p1", [])))
        self.assertTrue(reach.on_part({"entity_type": "ConstructionPlane", "token": "p1", "definition": "Offset"}))
        self.assertTrue(reach.on_part(plane("p1", [ORIGIN_PLANE, {"foreign": True}])))

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

    def test_a_sketch_on_an_origin_plane_is_still(self):
        origin = {"kind": "constructionPlane", "origin": True}
        self.assertEqual(reach.placement_sizes(self.table, self.timeline, self.profile(origin), 2), [])
        self.assertEqual(reach.placement_sizes(None, self.timeline, self.profile({"kind": "face"}), 2), [])

    def test_a_sketch_plane_is_fixed_only_when_no_ticked_size_moves_it(self):
        origin = {"kind": "constructionPlane", "origin": True}
        self.assertTrue(reach.plane_fixed(self.table, self.timeline, self.profile(origin), 2))
        turned = {"kind": "constructionPlane", "token": "p1", "definition": "At angle", "built_on": [{"origin": True}]}
        self.assertFalse(reach.plane_fixed(self.table, self.timeline, self.profile(turned), 2))
        self.assertFalse(reach.plane_fixed(self.table, self.timeline, self.profile({"kind": "face"}), 2))
        self.assertFalse(reach.plane_fixed(self.table, self.timeline, self.profile(origin, borrowed="Lid"), 2))

    def test_a_sketch_without_a_reference_counts_as_on_a_face_unless_it_lies_on_an_origin_plane(self):
        # Fusion gives no reference for some sketches on faces.
        unread = {"sketch": "Sketch9", "frame": FRAME}
        self.assertEqual(reach.placement_sizes(self.table, self.timeline, unread, 2), ["h_mm", "gap_mm"])
        flat = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        self.assertEqual(reach.placement_sizes(self.table, self.timeline, dict(unread, frame=flat), 2), [])
        self.assertEqual(reach.placement_sizes(self.table, self.timeline, dict(unread, on_start_face=True), 2), [])

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


class ReferenceSizesTest(unittest.TestCase):
    """The sizes that may move a plane, axis or face a step uses as a place (`reach.reference_sizes`)."""

    def setUp(self):
        self.table = sized_table([model("d1", "w_mm", 10, kind="constructionPlane", token="p1"),
                                  model("d2", "h_mm", 20, kind="constructionAxis", token="a1")])
        self.timeline = [step(0, "Base", reads=["gap_mm"]), step(1, "Rib", reads=["t_mm"]), step(2, "Split1")]

    def sizes(self, record):
        return reach.reference_sizes(self.table, self.timeline, self.timeline[2], record)

    def test_construction_geometry_made_from_parameters_names_its_own_sizes_through_a_chain(self):
        self.assertEqual(self.sizes(plane("p1", [ORIGIN_PLANE])), ["w_mm"])
        axis = {"entity_type": "ConstructionAxis", "token": "a1", "built_on": [plane("p1", [ORIGIN_PLANE])]}
        self.assertEqual(self.sizes(axis), ["w_mm", "h_mm"])
        # A record of an older capture: its token tells it is construction geometry, but not what it is built on.
        self.assertEqual(self.sizes({"point": [0, 0, 0], "dir": [0, 0, 1], "token": "a1"}),
                         ["h_mm", "gap_mm", "t_mm"])

    def test_part_geometry_may_move_with_every_size_read_before(self):
        self.assertEqual(self.sizes(FACE), ["gap_mm", "t_mm"])
        self.assertEqual(self.sizes({"entity_type": "SketchLine"}), ["gap_mm", "t_mm"])
        # Construction geometry built on the part: the sizes read before it was made, and its own.
        self.assertEqual(self.sizes(plane("p1", [FACE], made_by=1)), ["w_mm", "gap_mm"])

    def test_a_record_that_does_not_say_what_it_is_may_move_with_every_size_read_before(self):
        self.assertEqual(self.sizes({"point": [0, 0, 0], "normal": [1, 0, 0]}), ["gap_mm", "t_mm"])

    def test_a_sketch_line_names_its_sketch_and_what_moves_its_plane(self):
        table = sized_table([model("d1", "w_mm", 10, sketch="Guide"),
                             model("d2", "h_mm", 20, kind="constructionPlane", token="p1")])
        timeline = [step(0, "Base", reads=["gap_mm"]), dict(step(1, "Guide", kind="Sketch"), data={}),
                    step(2, "Rib", reads=["t_mm"]), step(3, "Revolve1")]
        on_plane = plane("p1", [ORIGIN_PLANE], kind="constructionPlane")

        def sizes(**line):
            record = dict({"entity_type": "SketchLine", "sketch": "Guide", "sketch_reference": on_plane,
                           "sketch_projected": False}, **line)
            return reach.reference_sizes(table, timeline, timeline[3], record)
        self.assertEqual(sizes(), ["w_mm", "h_mm"])
        self.assertEqual(sizes(sketch_reference={"kind": "face"}), ["w_mm", "gap_mm"])
        # Projections, or none known: every size read before the sketch may move projected geometry.
        for projected in (True, None):
            self.assertEqual(sizes(sketch_projected=projected), ["w_mm", "h_mm", "gap_mm"])
        # An older capture names the line and its sketch only.
        self.assertEqual(reach.reference_sizes(table, timeline, timeline[3], {
            "point": [0, 0, 0], "dir": [0, 1, 0], "entity": "l1", "sketch_token": "s1", "sketch": "Guide"}),
            ["w_mm", "gap_mm"])

    def test_an_origin_another_component_or_a_place_of_another_record_names_no_size(self):
        for record in (ORIGIN_PLANE, {"origin": True}, dict(FACE, assembly=True), dict(FACE, foreign=True),
                       {"point": [0, 0, 0], "dir": [0, 0, 1], "fixed": True}, None):
            self.assertEqual(self.sizes(record), [], record)
        self.assertEqual(reach.reference_sizes(None, self.timeline, self.timeline[2], FACE), [])


class DirectionAndHoleEndTest(unittest.TestCase):
    """What may turn a pattern direction (`reach.direction_sizes`) and move the faces a hole goes through
    (`reach.hole_end_sizes`)."""

    def setUp(self):
        self.table = sized_table([model("d1", "w_mm", 10, kind="constructionAxis", token="a1"),
                                  model("d2", "t_mm", 5, sketch="Guide"), model("d3", "h_mm", 20, sketch="Holes")])

    def pattern(self, **data):
        return step(3, "Pattern1", kind="RectangularPatternFeature", data=data)

    def test_a_direction_of_the_part_its_sketch_line_or_another_component(self):
        timeline = [step(0, "Base", reads=["gap_mm"])]
        own = {"own": True, "entity_type": "ConstructionAxis", "token": "a1", "built_on": [{"origin": True}]}
        guide = {"sketch": "Guide", "reference": {"kind": "constructionPlane", "origin": True}, "projected": False}
        cases = ((self.pattern(direction_one_place=own), ["w_mm"], "ConstructionAxis"),
                 (self.pattern(direction_one_place={"own": True, "entity_type": "BRepEdge"}), ["gap_mm"], "BRepEdge"),
                 (self.pattern(direction_one_sketch=guide), ["t_mm"], "SketchLine"),
                 (self.pattern(direction_one_sketch=dict(guide, reference={"kind": "face"})), ["gap_mm", "t_mm"],
                  "SketchLine"),
                 (self.pattern(direction_one_place={"assembly": True, "ref": {}}), [], None))
        for item, names, kind in cases:
            self.assertEqual(reach.direction_sizes(self.table, timeline + [item], item, "one"), names, item)
            self.assertEqual(reach.direction_kind(item, "one"), kind)

    def test_a_direction_whose_source_is_unknown_may_turn_with_every_size_read_before(self):
        timeline = [step(0, "Base", reads=["gap_mm"])]
        used = {"direction_one": [1, 0, 0], "quantity_one": 3}
        for item in (self.pattern(direction_one_place={"unknown": True}, **used), self.pattern(**used)):
            self.assertEqual(reach.direction_sizes(self.table, timeline + [item], item, "one"), ["gap_mm"], item)
        # A direction with one copy along it places nothing.
        unused = self.pattern(direction_one=[1, 0, 0], quantity_one=1)
        self.assertEqual(reach.direction_sizes(self.table, timeline + [unused], unused, "one"), [])

    def test_the_sizes_that_place_the_holes_move_their_ends_too(self):
        # On a part that is not equally thick everywhere, a hole that moves comes out at another face.
        base = step(0, "Base", reads=["gap_mm"])
        sketch = dict(step(1, "Holes", kind="Sketch"), data={})
        hole = step(3, "Hole1", kind="HoleFeature")
        data = {"sketch": "Holes"}
        self.assertEqual(reach.hole_end_sizes(self.table, [base, sketch, hole], hole, data), ["h_mm", "gap_mm"])
        self.assertEqual(reach.hole_end_sizes(None, [base, sketch, hole], hole, data), [])


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
