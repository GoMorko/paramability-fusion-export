"""Picks on pattern and mirror copies, and copied rounds and chamfers, follow sizes."""
import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of
from tests.test_translate_sized import CUBE, TICKED, param, table_of

from lib.geometry import vec
from lib.params import size_table
from lib.params.expressions import evaluate
from lib.translator import translate
from lib.translator.copy_counts import stays_at_least
from lib.translator.values import Quantity

FLAT = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
POST_TOP = 20.0


def _square(x0, y0, x1, y1):
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return [{"kind": "line", "start": corners[n], "end": corners[(n + 1) % 4]} for n in range(4)]


def copy_item(index, name, kind, data):
    return {"index": index, "name": name, "type": kind, "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}], "data": data}


def copy_extrude(index, name, operation, frame, square, distance, params=None):
    return copy_item(index, name, "ExtrudeFeature", {
        "operation": operation, "profiles": [{"sketch": name, "frame": frame,
                                              "loops": [{"outer": True, "curves": _square(*square)}]}],
        "start": {"kind": "profilePlane"}, "extent_type": "one",
        "side_one": {"kind": "distance", "distance": distance, "taper_deg": 0.0}, "side_two": None,
        "symmetric": None, "thin": False, "participants": [], "end_offset": distance, "params": params or {}})


def _grid(index, sources, spacing, count=2, params=None):
    elements = [{"id": n + 1, "suppressed": False, "frame": dict(FLAT, origin=[n * spacing, 0, 0])} for n in range(count)]
    return copy_item(index, "R-Pattern1", "RectangularPatternFeature", {
        "entity_type": "features", "sources": sources, "direction_one": [1, 0, 0], "quantity_one": count,
        "distance_one": spacing, "direction_two": None, "quantity_two": 1, "distance_two": 0.0,
        "distance_type": "spacing", "symmetric_one": False, "symmetric_two": False, "elements": elements,
        "params": params or {}})


def edges_set(kind, points, **values):
    entry = dict({"kind": kind, "input_kinds": ["edge"]}, **values)
    entry["edges"] = [{"token": "e%d" % n, "closed": False, "points": [p]} for n, p in enumerate(points)]
    return entry


def post_capture(*later, post_params=None):
    """A 60 by 20 by 10 plate and a 4 mm post on its top, 10 mm tall, with the tray's parameters, then `later`."""
    capture = load_capture("filter_tray_sized")
    top = dict(FLAT, origin=[0, 0, 10])
    capture["items"] = [
        copy_extrude(1, "Plate", "newBody", FLAT, (0, 0, 60, 20), 10.0),
        copy_extrude(2, "Post", "join", top, (4, 4, 8, 8), 10.0,
                 post_params or {"side_one.distance": param("d20", "wall_mm * 5", 10.0)}),
    ] + list(later)
    return capture


def run(capture):
    result = translate(capture, size_table=table_of(capture, TICKED))
    assert result.recipe is not None, result.refusal
    return result


def loose_names(result):
    return sorted(f["name"] for f in result.loose)


def counted(ranges=None):
    """(capture, size table): three posts counted by holes_count, and a fillet on the second one."""
    fillet = copy_item(4, "Fillet1", "FilletFeature", {
        "sets": [edges_set("constant", [[32, 8, 15]], radius=1.0, continuity="tangent")]})
    grid = _grid(3, [2], 24.0, count=3, params={"distance_one": param("d21", "hole_pitch_mm", 24.0),
                                                "quantity_one": param("d22", "holes_count", 3.0)})
    capture = post_capture(grid, fillet)
    params = capture["parameters"]
    return capture, size_table.build(params["user"], TICKED, params["model"], ranges=ranges)


class PickOnCopyTest(unittest.TestCase):
    def test_an_edge_on_a_pattern_copy_follows_the_spacing_and_the_length(self):
        fillet = copy_item(4, "Fillet1", "FilletFeature", {
            "sets": [edges_set("constant", [[32, 8, 15]], radius=1.0, continuity="tangent")]})
        result = run(post_capture(_grid(3, [2], 24.0, params={"distance_one": param("d21", "hole_pitch_mm", 24.0)}),
                                  fillet))
        self.assertEqual((result.fixed, result.loose), ([], []))
        (step,) = steps_of(result.recipe, "round")
        self.assertEqual(step["edges"]["near"], [[{"expr": "8 + hole_pitch_mm"}, 8,
                                                  {"expr": "0.5 * (wall_mm * 5) + 10"}]])
        assert_schema_ok(self, result.recipe)

    def test_a_pick_on_a_copy_keeps_the_count_range_and_marks_the_size_loose(self):
        capture, table = counted()
        result = translate(capture, size_table=table)
        self.assertEqual(result.fixed, [])
        self.assertEqual(result.recipe["sizes"]["holes_count"]["min"], 1.0)
        reasons = {f["name"]: f["reason"] for f in result.loose}
        self.assertIn("Fillet1 picks copy 2 of R-Pattern1", reasons["holes_count"])
        self.assertTrue(reasons["holes_count"].startswith("holes_count may give unexpected results"))
        self.assertEqual(steps_of(result.recipe, "round")[0]["edges"]["near"][0][0], {"expr": "8 + hole_pitch_mm"})

    def test_an_edge_on_a_mirror_copy_is_mirrored_with_its_formula(self):
        mirror = copy_item(3, "Mirror1", "MirrorFeature", {
            "entity_type": "features", "sources": [2], "plane": {"point": [30, 0, 0], "normal": [1, 0, 0]},
            "combine": False})
        fillet = copy_item(4, "Fillet1", "FilletFeature", {
            "sets": [edges_set("constant", [[52, 8, 15]], radius=1.0, continuity="tangent")]})
        result = run(post_capture(mirror, fillet))
        self.assertEqual((result.fixed, result.loose), ([], []))
        self.assertEqual(steps_of(result.recipe, "round")[0]["edges"]["near"],
                         [[52, 8, {"expr": "0.5 * (wall_mm * 5) + 10"}]])


class CopiedFinishTest(unittest.TestCase):
    def test_copied_rounds_follow_the_spacing_and_keep_the_count(self):
        fillet = copy_item(3, "Fillet1", "FilletFeature", {
            "sets": [edges_set("constant", [[4, 4, 15]], radius=1.0, continuity="tangent")]})
        grid = _grid(4, [3], 24.0, count=3, params={"distance_one": param("d21", "hole_pitch_mm", 24.0),
                                                    "quantity_one": param("d22", "holes_count", 3.0)})
        result = run(post_capture(fillet, grid))
        self.assertEqual((result.fixed, result.loose), ([], []))
        self.assertNotIn("holes_count", result.recipe["sizes"])
        _, copies = steps_of(result.recipe, "round")
        z = {"expr": "0.5 * (wall_mm * 5) + 10"}
        self.assertEqual(copies["edges"]["near"], [[{"expr": "4 + hole_pitch_mm"}, 4, z],
                                                   [{"expr": "4 + (2 * hole_pitch_mm)"}, 4, z]])
        assert_schema_ok(self, result.recipe)

    def test_a_mirrored_uneven_chamfer_mirrors_the_face_of_its_first_distance(self):
        chamfer = copy_item(3, "Chamfer1", "ChamferFeature", {"corner_type": "chamfer", "sets": [
            edges_set("twoDistances", [[6, 4, POST_TOP]], distance=1.0, distance_two=2.0)]})
        edge = chamfer["data"]["sets"][0]["edges"][0]
        edge["sides"], edge["cut_normals"] = [[[0, 0, 1], [0, -1, 0]]], [[0, -1, 2]]
        mirror = copy_item(4, "Mirror1", "MirrorFeature", {
            "entity_type": "features", "sources": [3], "plane": {"point": [0, 10, 0], "normal": [0, 1, 0]},
            "combine": False})
        recipe = translate(post_capture(chamfer, mirror)).recipe
        source, mirrored = steps_of(recipe, "bevel")
        self.assertEqual((source["sizeOn"], source["otherSize"]), ([0, -0.707106781, -0.707106781], 2))
        self.assertEqual(mirrored["sizeOn"], [0, 0.707106781, -0.707106781])
        self.assertEqual(mirrored["edges"]["near"], [[6, 16, POST_TOP]])
        assert_schema_ok(self, recipe)


class CopyCountTest(unittest.TestCase):
    """A count formula with rounding, as in the owner's filter box: `ceil(width_count) * 2` copies."""

    def table(self, ranges=None):
        width = {"name": "width_count", "expression": "1.8", "value": 1.8, "unit": "", "kind": "count",
                 "value_type": "numeric", "is_favorite": True, "dependency_parameters": []}
        return size_table.build([width], ["width_count"], ranges=ranges)

    def count(self):
        return Quantity(4.0, "ceil(width_count) * 2", ("width_count",))

    def test_a_count_must_stay_at_least_the_copy_a_pick_needs_over_the_whole_range(self):
        falling = Quantity(4.0, "8 - ceil(width_count) * 2", ("width_count",))
        for label, count, needed, holds in (("dips below the need", self.count(), 4, False),
                                            ("never dips", self.count(), 2, True),
                                            ("falls at the big end", falling, 4, False),
                                            ("follows no size", Quantity(4.0), 9, True)):
            with self.subTest(label):
                self.assertEqual(stays_at_least(self.table(), count, needed), holds)


def _mirror(index, plane, entity_type="features", combine=False, box=None):
    return copy_item(index, "Mirror1", "MirrorFeature", {
        "entity_type": entity_type, "sources": [2], "plane": plane, "combine": combine, "target_box_before": box})


def turned_copy(about, degrees, vertical=False):
    """An element frame that turns by `degrees` about the line through `about` along x (or along z)."""
    cos, sin = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    frame = ({"origin": [0, 0, 0], "x": [cos, sin, 0], "y": [-sin, cos, 0], "z": [0, 0, 1]} if vertical else
             {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, cos, sin], "z": [0, -sin, cos]})
    return dict(frame, origin=vec.sub(about, vec.frame_apply(frame, about)))


def _circular(index, axis, count=4):
    elements = [{"id": n + 1, "suppressed": False,
                 "frame": turned_copy(axis["point"], 360.0 * n / count, axis["dir"] == [0, 0, 1])}
                for n in range(count)]
    return copy_item(index, "C-Pattern1", "CircularPatternFeature", {
        "entity_type": "features", "sources": [2], "axis": axis, "quantity": count, "total_angle_deg": 360.0,
        "symmetric": False, "elements": elements})


def _at(recipe_value, wall):
    """A written number or formula at the size wall_mm = `wall`."""
    return evaluate(recipe_value["expr"], {"wall_mm": wall}) if isinstance(recipe_value, dict) else recipe_value


TOP_FACE = {"point": [6, 6, POST_TOP], "normal": [0, 0, 1], "entity_type": "BRepFace",
            "face_point": [6, 6, POST_TOP], "surface": "Plane"}


class MovedReferenceTest(unittest.TestCase):
    """A mirror plane or turning axis on a face or edge that a size moves."""

    def mirrored_plane(self, plane):
        capture = post_capture(_mirror(3, plane))
        table = table_of(capture, TICKED)
        result = translate(capture, size_table=table)
        self.assertIsNotNone(result.recipe, result.refusal)
        return result, steps_of(result.recipe, "mirror")[0]["plane"]["origin"]

    def test_a_mirror_plane_on_a_moving_face_follows_it_and_so_does_a_pick_on_the_copy(self):
        fillet = copy_item(4, "Fillet1", "FilletFeature", {
            "sets": [edges_set("constant", [[6, 8, 2 * POST_TOP - 10]], radius=1.0, continuity="tangent")]})
        result = run(post_capture(_mirror(3, TOP_FACE), fillet))
        self.assertEqual((result.fixed, result.loose), ([], []))
        (mirror,) = steps_of(result.recipe, "mirror")
        self.assertEqual([_at(c, 3.0) for c in mirror["plane"]["origin"]], [6, 6, 25])
        self.assertEqual([_at(c, 3.0) for c in steps_of(result.recipe, "round")[0]["edges"]["near"][0]], [6, 8, 40])
        assert_schema_ok(self, result.recipe)

    def test_a_plane_on_a_face_nothing_places_marks_the_sizes_it_may_move_with(self):
        lost = dict(TOP_FACE, face_point=[100, 100, 5])
        result, origin = self.mirrored_plane(lost)
        self.assertEqual((loose_names(result), origin), (["wall_mm"], [6, 6, POST_TOP]))
        self.assertIn("Mirror1", result.loose[0]["reason"])

    def test_an_origin_plane_and_an_unread_plane_stay_where_they_are(self):
        for label, plane in (("origin", {"point": [30, 0, 0], "normal": [1, 0, 0], "origin": True}),
                             ("older capture", {"point": [30, 0, 0], "normal": [1, 0, 0]})):
            with self.subTest(label):
                result, origin = self.mirrored_plane(plane)
                self.assertEqual(((result.fixed, result.loose), origin), (([], []), [30, 0, 0]))

    def test_a_construction_plane_built_on_a_moving_face(self):
        built = {"point": [6, 6, POST_TOP + 5], "normal": [0, 0, 1], "token": "cp1", "entity_type": "ConstructionPlane",
                 "definition": "ConstructionPlaneOffsetDefinition", "built_on": [
                     {"entity_type": "BRepFace", "face_point": [6, 6, POST_TOP], "surface": "Plane"}]}
        _, origin = self.mirrored_plane(built)
        self.assertEqual([_at(c, 3.0) for c in origin], [6, 6, 30])

        midplane = dict(built, definition="ConstructionPlaneMidplaneDefinition", point=[6, 6, 10], built_on=[
            {"entity_type": "BRepFace", "face_point": [6, 6, POST_TOP], "surface": "Plane"},
            {"entity_type": "BRepFace", "face_point": [30, 10, 0], "surface": "Plane"}])
        _, origin = self.mirrored_plane(midplane)
        self.assertEqual([_at(c, 3.0) for c in origin], [6, 6, 12.5])

    def test_a_construction_plane_that_cannot_be_followed_or_does_not_move(self):
        face = {"entity_type": "BRepFace", "face_point": [6, 6, POST_TOP], "surface": "Plane"}
        tilted = {"point": [6, 6, 30], "normal": [0, 0, 1], "token": "cp1", "entity_type": "ConstructionPlane",
                  "definition": "ConstructionPlaneAtAngleDefinition", "built_on": [face]}
        result, _ = self.mirrored_plane(tilted)
        self.assertEqual(loose_names(result), ["wall_mm"])
        from_origin = dict(tilted, built_on=[{"origin": True}])
        result, origin = self.mirrored_plane(from_origin)
        self.assertEqual(((result.fixed, result.loose), origin), (([], []), [6, 6, 30]))

    def test_a_turning_axis_on_a_moving_edge_follows_it_and_so_does_a_pick_on_the_copy(self):
        axis = {"point": [6, 4, POST_TOP], "dir": [1, 0, 0], "entity_type": "BRepEdge",
                "edge_points": [[6, 4, POST_TOP]]}
        fillet = copy_item(4, "Fillet1", "FilletFeature", {
            "sets": [edges_set("constant", [[6, 0, 2 * POST_TOP - 10]], radius=1.0, continuity="tangent")]})
        result = run(post_capture(_circular(3, axis), fillet))
        self.assertEqual((result.fixed, result.loose), ([], []))
        (pattern,) = steps_of(result.recipe, "pattern")
        self.assertEqual([_at(c, 3.0) for c in pattern["polar"]["axisPoint"]], [6, 4, 25])
        self.assertEqual([_at(c, 3.0) for c in steps_of(result.recipe, "round")[0]["edges"]["near"][0]], [6, 0, 40])

    def test_a_turning_axis_that_cannot_be_placed_or_is_an_origin_axis(self):
        lost = {"point": [6, 4, POST_TOP], "dir": [1, 0, 0], "entity_type": "BRepEdge", "edge_points": [[90, 90, 90]]}
        origin = {"point": [6, 4, POST_TOP], "dir": [1, 0, 0], "origin": True}
        for label, axis, expected in (("lost edge", lost, ["wall_mm"]), ("origin axis", origin, [])):
            with self.subTest(label):
                result = run(post_capture(_circular(3, axis)))
                self.assertEqual(loose_names(result), expected)
                self.assertEqual(steps_of(result.recipe, "pattern")[0]["polar"]["axisPoint"], [6, 4, POST_TOP])

    def test_the_axis_of_a_round_wall_stays_while_it_only_grows_taller(self):
        axis = {"point": [6, 6, 10], "dir": [0, 0, 1], "entity_type": "BRepFace", "surface": "Cylinder",
                "face_point": [8, 6, 15]}
        boss = copy_item(2, "Post", "ExtrudeFeature", {
            "operation": "join", "profiles": [{"sketch": "Post", "frame": dict(FLAT, origin=[0, 0, 10]), "loops": [
                {"outer": True, "curves": [{"kind": "circle", "center": [6, 6], "radius": 2.0}]}]}],
            "start": {"kind": "profilePlane"}, "extent_type": "one",
            "side_one": {"kind": "distance", "distance": 10.0, "taper_deg": 0.0}, "side_two": None,
            "symmetric": None, "thin": False, "participants": [], "end_offset": 10.0,
            "params": {"side_one.distance": param("d20", "wall_mm * 5", 10.0)}})
        capture = post_capture(_circular(3, axis))
        capture["items"][1] = boss
        result = run(capture)
        self.assertEqual((loose_names(result), steps_of(result.recipe, "pattern")[0]["polar"]["axisPoint"]),
                         ([], [6, 6, 10]))
        capture = post_capture(_circular(3, dict(axis, face_point=[50, 50, 15])))
        capture["items"][1] = boss
        self.assertEqual(loose_names(run(capture)), ["wall_mm"])


class BodyMirrorOverRangesTest(unittest.TestCase):
    """The body mirror needs the part on one side of the plane at every size, not only at the measured ones."""

    PLATE_BOX = {"min": [0, 0, 0], "max": [60, 20, POST_TOP]}

    def result(self, plane_z, *middle):
        pocket = copy_extrude(3, "Pocket", "cut", {"origin": [0, 0, 10], "x": [1, 0, 0], "y": [0, -1, 0], "z": [0, 0, -1]},
                          (20, 5, 30, 15), 8.0, {"side_one.distance": param("d30", "wall_mm * 4", 8.0)})
        plane = {"point": [0, 0, plane_z], "normal": [0, 0, 1], "origin": True}
        capture = post_capture(pocket, *middle, _mirror(4 + len(middle), plane, "bodies", True, self.PLATE_BOX))
        return translate(capture, size_table=table_of(capture, TICKED))

    def test_a_cut_a_size_can_push_across_the_plane_marks_that_size(self):
        near = self.result(0.0)
        self.assertEqual(loose_names(near), ["wall_mm"])
        self.assertIn("Mirror1", near.loose[0]["reason"])
        self.assertEqual(loose_names(self.result(-20.0)), [])

    def test_a_step_the_check_cannot_measure_marks_the_sizes_it_reads(self):
        grid = _grid(4, [2], 24.0, params={"distance_one": param("d21", "hole_pitch_mm", 24.0)})
        result = self.result(-20.0, grid)
        self.assertEqual(loose_names(result), sorted([CUBE, "wall_mm"]))


if __name__ == "__main__":
    unittest.main()
