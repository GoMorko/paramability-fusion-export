"""Picks on pattern and mirror copies, and copied rounds and chamfers, follow sizes."""
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of
from tests.test_translate_sized import TICKED, param, table_of

from lib.params import size_table
from lib.translator import translate
from lib.translator.copy_counts import raised_minimums
from lib.translator.values import Quantity

FLAT = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
POST_TOP = 20.0


def _square(x0, y0, x1, y1):
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return [{"kind": "line", "start": corners[n], "end": corners[(n + 1) % 4]} for n in range(4)]


def _item(index, name, kind, data):
    return {"index": index, "name": name, "type": kind, "suppressed": False, "health": "ok", "message": "",
            "component_root": True, "bodies_after": [{"token": "t1", "name": "Body1"}], "data": data}


def _extrude(index, name, operation, frame, square, distance, params=None):
    return _item(index, name, "ExtrudeFeature", {
        "operation": operation, "profiles": [{"sketch": name, "frame": frame,
                                              "loops": [{"outer": True, "curves": _square(*square)}]}],
        "start": {"kind": "profilePlane"}, "extent_type": "one",
        "side_one": {"kind": "distance", "distance": distance, "taper_deg": 0.0}, "side_two": None,
        "symmetric": None, "thin": False, "participants": [], "end_offset": distance, "params": params or {}})


def _grid(index, sources, spacing, count=2, params=None):
    elements = [{"id": n + 1, "suppressed": False, "frame": dict(FLAT, origin=[n * spacing, 0, 0])} for n in range(count)]
    return _item(index, "R-Pattern1", "RectangularPatternFeature", {
        "entity_type": "features", "sources": sources, "direction_one": [1, 0, 0], "quantity_one": count,
        "distance_one": spacing, "direction_two": None, "quantity_two": 1, "distance_two": 0.0,
        "distance_type": "spacing", "symmetric_one": False, "symmetric_two": False, "elements": elements,
        "params": params or {}})


def _edges_set(kind, points, **values):
    entry = dict({"kind": kind, "input_kinds": ["edge"]}, **values)
    entry["edges"] = [{"token": "e%d" % n, "closed": False, "points": [p]} for n, p in enumerate(points)]
    return entry


def post_capture(*later, post_params=None):
    """A 60 by 20 by 10 plate and a 4 mm post on its top, 10 mm tall, with the tray's parameters, then `later`."""
    capture = load_capture("filter_tray_sized")
    top = dict(FLAT, origin=[0, 0, 10])
    capture["items"] = [
        _extrude(1, "Plate", "newBody", FLAT, (0, 0, 60, 20), 10.0),
        _extrude(2, "Post", "join", top, (4, 4, 8, 8), 10.0,
                 post_params or {"side_one.distance": param("d20", "wall_mm * 5", 10.0)}),
    ] + list(later)
    return capture


def run(capture):
    result = translate(capture, size_table=table_of(capture, TICKED))
    assert result.recipe is not None, result.refusal
    return result


def fixed_names(result):
    return sorted(f["name"] for f in result.fixed)


def counted(ranges=None):
    """(capture, size table): three posts counted by holes_count, and a fillet on the second one."""
    fillet = _item(4, "Fillet1", "FilletFeature", {
        "sets": [_edges_set("constant", [[32, 8, 15]], radius=1.0, continuity="tangent")]})
    grid = _grid(3, [2], 24.0, count=3, params={"distance_one": param("d21", "hole_pitch_mm", 24.0),
                                                "quantity_one": param("d22", "holes_count", 3.0)})
    capture = post_capture(grid, fillet)
    params = capture["parameters"]
    return capture, size_table.build(params["user"], TICKED, params["model"], ranges=ranges)


class PickOnCopyTest(unittest.TestCase):
    def test_an_edge_on_a_pattern_copy_follows_the_spacing_and_the_length(self):
        fillet = _item(4, "Fillet1", "FilletFeature", {
            "sets": [_edges_set("constant", [[32, 8, 15]], radius=1.0, continuity="tangent")]})
        result = run(post_capture(_grid(3, [2], 24.0, params={"distance_one": param("d21", "hole_pitch_mm", 24.0)}),
                                  fillet))
        self.assertEqual(result.fixed, [])
        (step,) = steps_of(result.recipe, "round")
        self.assertEqual(step["edges"]["near"], [[{"expr": "8 + hole_pitch_mm"}, 8,
                                                  {"expr": "0.5 * (wall_mm * 5) + 10"}]])
        assert_schema_ok(self, result.recipe)

    def _counted(self, ranges=None):
        capture, table = counted(ranges)
        return translate(capture, size_table=table)

    def test_a_pick_on_a_copy_raises_the_smallest_count_so_the_copy_stays(self):
        result = self._counted()
        self.assertEqual(result.fixed, [])
        self.assertEqual([(r["name"], r["min"]) for r in result.raised], [("holes_count", 2)])
        self.assertIn("R-Pattern1", result.raised[0]["reason"])
        self.assertEqual(result.recipe["sizes"]["holes_count"]["min"], 2)
        self.assertEqual(steps_of(result.recipe, "round")[0]["edges"]["near"][0][0], {"expr": "8 + hole_pitch_mm"})

    def test_the_default_range_from_the_dialog_still_raises_the_count(self):
        result = self._counted({"holes_count": (1.0, 6.0)})
        self.assertEqual(fixed_names(result), [])
        self.assertEqual([(r["name"], r["min"]) for r in result.raised], [("holes_count", 2)])

    def test_an_edge_on_a_mirror_copy_is_mirrored_with_its_formula(self):
        mirror = _item(3, "Mirror1", "MirrorFeature", {
            "entity_type": "features", "sources": [2], "plane": {"point": [30, 0, 0], "normal": [1, 0, 0]},
            "combine": False})
        fillet = _item(4, "Fillet1", "FilletFeature", {
            "sets": [_edges_set("constant", [[52, 8, 15]], radius=1.0, continuity="tangent")]})
        result = run(post_capture(mirror, fillet))
        self.assertEqual(result.fixed, [])
        self.assertEqual(steps_of(result.recipe, "round")[0]["edges"]["near"],
                         [[52, 8, {"expr": "0.5 * (wall_mm * 5) + 10"}]])


class CopiedFinishTest(unittest.TestCase):
    def test_copied_rounds_follow_the_spacing_and_keep_the_count(self):
        fillet = _item(3, "Fillet1", "FilletFeature", {
            "sets": [_edges_set("constant", [[4, 4, 15]], radius=1.0, continuity="tangent")]})
        grid = _grid(4, [3], 24.0, count=3, params={"distance_one": param("d21", "hole_pitch_mm", 24.0),
                                                    "quantity_one": param("d22", "holes_count", 3.0)})
        result = run(post_capture(fillet, grid))
        self.assertEqual(fixed_names(result), ["holes_count"])
        _, copies = steps_of(result.recipe, "round")
        z = {"expr": "0.5 * (wall_mm * 5) + 10"}
        self.assertEqual(copies["edges"]["near"], [[{"expr": "4 + hole_pitch_mm"}, 4, z],
                                                   [{"expr": "4 + (2 * hole_pitch_mm)"}, 4, z]])
        assert_schema_ok(self, result.recipe)

    def test_a_mirrored_uneven_chamfer_mirrors_the_face_of_its_first_distance(self):
        chamfer = _item(3, "Chamfer1", "ChamferFeature", {"corner_type": "chamfer", "sets": [
            _edges_set("twoDistances", [[6, 4, POST_TOP]], distance=1.0, distance_two=2.0)]})
        edge = chamfer["data"]["sets"][0]["edges"][0]
        edge["sides"], edge["cut_normals"] = [[[0, 0, 1], [0, -1, 0]]], [[0, -1, 2]]
        mirror = _item(4, "Mirror1", "MirrorFeature", {
            "entity_type": "features", "sources": [3], "plane": {"point": [0, 10, 0], "normal": [0, 1, 0]},
            "combine": False})
        recipe = translate(post_capture(chamfer, mirror)).recipe
        source, mirrored = steps_of(recipe, "bevel")
        self.assertEqual((source["sizeOn"], source["otherSize"]), ([0, -0.707106781, -0.707106781], 2))
        self.assertEqual(mirrored["sizeOn"], [0, 0.707106781, -0.707106781])
        self.assertEqual(mirrored["edges"]["near"], [[6, 16, POST_TOP]])
        assert_schema_ok(self, recipe)


if __name__ == "__main__":
    unittest.main()


class RaisedMinimumTest(unittest.TestCase):
    """A count formula with rounding, as in the owner's filter box: `ceil(width_count) * 2` copies."""

    def table(self, ranges=None):
        width = {"name": "width_count", "expression": "1.8", "value": 1.8, "unit": "", "kind": "count",
                 "value_type": "numeric", "is_favorite": True, "dependency_parameters": []}
        return size_table.build([width], ["width_count"], ranges=ranges)

    def count(self):
        return Quantity(4.0, "ceil(width_count) * 2", ("width_count",))

    def test_the_minimum_rises_just_past_where_a_copy_would_go(self):
        self.assertEqual(raised_minimums(self.table(), self.count(), 4), {"width_count": 1.01})
        self.assertEqual(raised_minimums(self.table(), self.count(), 2), {})

    def test_a_typed_range_or_a_count_that_falls_cannot_be_helped(self):
        self.assertIsNone(raised_minimums(self.table({"width_count": (0.5, 3.6)}), self.count(), 4))
        falling = Quantity(4.0, "8 - ceil(width_count) * 2", ("width_count",))
        self.assertIsNone(raised_minimums(self.table(), falling, 4))
