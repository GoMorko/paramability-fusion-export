"""Geometry of other components in the Orca copy (`orca_translate/other_components.py`): planes, faces, axes,
directions and sketch outlines of another component are written where the capture places them, and the sizes that
act on that component are marked, so none of them reads as unused. What cannot be placed stays left out.

Fixtures: `component_foreign_mirror` (a mirror across a plane of Cover; gap_mm acts on Cover and on the part),
`component_ref_reach` (a boss that reaches to a face of Cover; gap_mm and ear_mm act on Cover, lid_mm on another
component), `component_ref_hole` (a hole on a sketch point of Cover) and `sweep_borrowed` (a sweep of an outline of
the sketch Rim of Lid, which rim_mm drives)."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture, split_by_plane, table_of
from tests.probe_helpers import user
from tests.translator_helpers import verdict_of

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import FeatureType
from lib.orca_translate import translate
from lib.orca_translate.context import Context
from lib.orca_translate.sketch_sizes import profile_sizes
from lib.orca_translate.sketches import graph_for
from lib.params import size_table
from lib.design_model.reach import placement_sizes

COVER = {"token": "cmp_cover", "name": "Cover"}


def run(capture):
    return translate(capture, table_of(capture))


def outcomes(result):
    return {p["name"]: p["outcome"] for p in result.parameters}


def left_cause(result, index):
    return next(g["cause"] for g in result.left_out if g["index"] == index)


def acting_on_cover(capture, name="cover_mm"):
    """Add a user parameter that acts on Cover only (it drives a plane there)."""
    found = dict(user(name, "4 mm", 4), dependents=[{"name": "d_cover", "kind": "constructionPlane",
                                                      "component": COVER["token"], "feature": "CoverPlane"}])
    capture.setdefault("parameters", {}).setdefault("user", []).append(found)
    capture["parameters"].setdefault("model", [])
    return capture


def of_cover(record, slot, kind, **geometry):
    """`record` as the reader gives an axis or plane of Cover brought into the part's coordinates."""
    ref = dict({"slot": slot, "type": kind, "token": "tok_" + slot, "component": dict(COVER), "path": "Cover:1"},
               **geometry)
    return dict(record, assembly=True, ref=ref)


def unplaced(record):
    """The same record when its place could not be brought in: it stays foreign."""
    out = {k: v for k, v in record.items() if k not in ("assembly", "point", "normal", "dir")}
    out["foreign"] = True
    return out


class MirrorPlaneTest(unittest.TestCase):
    def test_a_mirror_across_a_plane_of_another_component_is_copied_and_marks_the_sizes_on_it(self):
        result = run(fixture("component_foreign_mirror"))
        self.assertEqual(verdict_of(result, 4)["verdict"], "copied")
        (mirror,) = [f for f in result.recipe.features if f.type == FeatureType.MIRROR]
        self.assertEqual(mirror.plane.normal, (1.0, 0.0, 0.0))
        self.assertAlmostEqual(mirror.plane.origin[0], result.place.point([0, 0, 0])[0])
        # gap_mm also drives the plane of Cover: the copy follows it in Extrude1 only.
        self.assertEqual(outcomes(result), {"gap_mm": "partly", "depth_mm": "variable"})

    def test_without_data_on_where_sizes_act_the_mirror_is_copied_with_a_note(self):
        capture = fixture("component_foreign_mirror")
        for p in capture["parameters"]["user"]:
            p.pop("dependents")
        result = run(capture)
        self.assertEqual(verdict_of(result, 4)["verdict"], "copied")
        self.assertEqual(outcomes(result)["gap_mm"], "variable")
        self.assertEqual(len(result.notes), 1)

    def test_a_mirror_whose_copies_stay_apart_marks_nothing(self):
        capture = fixture("component_foreign_mirror")
        capture["items"][4]["data"].update(entity_type="bodies", combine=False,
                                           source_bodies=[dict(capture["target"])])
        result = run(capture)
        self.assertEqual(verdict_of(result, 4)["verdict"], "skipped")
        self.assertEqual(outcomes(result)["gap_mm"], "variable")

    def test_a_mirror_plane_that_could_not_be_placed_is_left_out(self):
        capture = fixture("component_foreign_mirror")
        data = capture["items"][4]["data"]
        data["plane"] = unplaced(data["plane"])
        result = run(capture)
        self.assertEqual(left_cause(result, 4), gap_hints.OTHER_COMPONENT)


class AxesAndPlanesTest(unittest.TestCase):
    """A pattern direction or axis, a revolve axis and a split plane of another component."""

    def cases(self):
        rect = acting_on_cover(fixture("rpattern_row"))
        rect["items"][4]["data"]["direction_one_place"] = of_cover({"dir": [1, 0, 0]}, "direction_one",
                                                                   "ConstructionAxis", dir=[1, 0, 0])
        circ = acting_on_cover(fixture("cpattern_part"))
        axis = circ["items"][4]["data"]["axis"]
        circ["items"][4]["data"]["axis"] = of_cover(axis, "axis", "ConstructionAxis", point=axis["point"],
                                                    dir=axis["dir"])
        rev = acting_on_cover(fixture("revolve_full"))
        axis = rev["items"][1]["data"]["axis"]
        rev["items"][1]["data"]["axis"] = of_cover(axis, "axis", "ConstructionAxis", point=axis["point"],
                                                   dir=axis["dir"])
        split = acting_on_cover(split_by_plane("t1"))
        plane = split["items"][2]["data"]["tool"]["plane"]
        split["items"][2]["data"]["tool"]["plane"] = of_cover(plane, "plane", "ConstructionPlane",
                                                              point=plane["point"], normal=plane["normal"])
        return {"pattern direction": (rect, 4, ("direction_one_place",)),
                "pattern axis": (circ, 4, ("axis",)), "revolve axis": (rev, 1, ("axis",)),
                "split plane": (split, 2, ("tool", "plane"))}

    def test_each_is_copied_where_it_is_and_the_sizes_on_its_component_are_fixed(self):
        for name, (capture, index, _) in self.cases().items():
            result = run(capture)
            self.assertEqual(verdict_of(result, index)["verdict"], "copied", name)
            self.assertEqual(outcomes(result)["cover_mm"], "fixed", name)

    def test_each_one_that_could_not_be_placed_is_left_out(self):
        for name, (capture, index, path) in self.cases().items():
            holder = capture["items"][index]["data"]
            for key in path[:-1]:
                holder = holder[key]
            holder[path[-1]] = unplaced(holder[path[-1]])
            if name == "pattern direction":
                holder["direction_one"] = None
            result = run(capture)
            self.assertEqual(left_cause(result, index), gap_hints.OTHER_COMPONENT, name)


class ReachAndHoleTest(unittest.TestCase):
    def test_an_extrude_to_a_face_of_another_component_reaches_its_place_in_the_part(self):
        result = run(fixture("component_ref_reach"))
        self.assertEqual(verdict_of(result, 3)["verdict"], "copied")
        boss = next(f for f in result.recipe.features if f.name == "Extrude2")
        # The sketch sits at z = 10 and the face of Cover at z = 25 in the part's coordinates.
        self.assertAlmostEqual(boss.distance, 15.0)
        self.assertEqual(outcomes(result), {"gap_mm": "fixed", "ear_mm": "fixed", "lid_mm": "unused"})

    def test_an_extrude_to_a_curved_face_of_another_component_is_left_out(self):
        capture = fixture("component_ref_reach")
        capture["items"][3]["data"]["side_one"]["plane"] = None
        result = run(capture)
        self.assertEqual(left_cause(result, 3), gap_hints.OTHER_COMPONENT)

    def test_a_hole_on_a_point_of_another_component_marks_the_sizes_on_it(self):
        result = run(fixture("component_ref_hole"))
        self.assertEqual(verdict_of(result, 3)["verdict"], "copied")
        self.assertEqual(outcomes(result), {"gap_mm": "fixed", "ear_mm": "fixed", "lid_mm": "unused"})


def with_own_rim(capture):
    """`sweep_borrowed` with a sketch of the part also named Rim, whose dimension own_mm drives."""
    capture["parameters"]["user"].append(user("own_mm", "8 mm", 8))
    capture["parameters"]["model"].append({
        "name": "d9", "expression": "own_mm", "value": 0.8, "unit": "mm", "kind": "derived", "role": "",
        "dependency_parameters": ["own_mm"],
        "created_by": {"kind": "sketchDimension", "token": "tok_d9", "name": "", "sketch": "Rim", "component": ""}})
    capture["sketch_graphs"] = [{"sketch": "Rim", "token": "own_rim", "dimensions": [{"param": "d9"}]}]
    return capture


class BorrowedOutlineTest(unittest.TestCase):
    def test_a_sweep_of_an_outline_of_another_component_is_copied_as_numbers(self):
        result = run(fixture("sweep_borrowed"))
        self.assertEqual(verdict_of(result, 1)["verdict"], "copied")
        self.assertEqual(outcomes(result)["rim_mm"], "fixed")

    def test_the_outline_is_not_taken_for_a_sketch_of_the_part_with_the_same_name(self):
        capture = with_own_rim(fixture("sweep_borrowed"))
        capture["items"][1]["data"]["profiles"][0].pop("sketch_token")
        result = run(capture)
        self.assertEqual(verdict_of(result, 1)["verdict"], "copied")
        self.assertEqual(outcomes(result)["own_mm"], "unused")

    def test_an_outline_without_a_known_place_is_left_out_with_the_sizes_of_its_own_sketch(self):
        capture = with_own_rim(fixture("sweep_borrowed"))
        capture["items"][1]["data"]["profiles"][0]["placement"] = {"error": "no match"}
        result = run(capture)
        self.assertEqual(verdict_of(result, 1)["verdict"], "leftOut")
        self.assertEqual((outcomes(result)["rim_mm"], outcomes(result)["own_mm"]), ("fixed", "unused"))

    def test_a_tool_body_built_from_an_outline_of_another_component_is_copied(self):
        capture = fixture("combine_tool_two_steps")
        profile = capture["items"][3]["data"]["profiles"][0]
        profile.update(foreign=True, native_frame=copy.deepcopy(profile["frame"]), component={"token": "cLid",
                       "name": "Lid"}, placement={"frame": {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0],
                                                            "z": [0, 0, 1]}},
                       sketch_params=[{"name": "d7", "expression": "lid_mm", "reads": ["lid_mm"]}])
        capture.setdefault("parameters", {"user": [], "model": []})["user"].append(user("lid_mm", "5 mm", 5))
        capture["parameters"].setdefault("model", [])
        result = run(capture)
        self.assertEqual(verdict_of(result, 6)["verdict"], "copied")
        self.assertEqual(outcomes(result)["lid_mm"], "fixed")


class SketchMatchGuardTest(unittest.TestCase):
    """An outline of another component's sketch is never matched to one of the part's sketches by name."""

    def test_no_graph_and_no_sizes_for_a_borrowed_or_foreign_outline(self):
        capture = with_own_rim(fixture("sweep_borrowed"))
        own = {"sketch": "Rim"}
        self.assertIsNotNone(graph_for(capture, own))
        ctx = Context(capture, table_of(capture), None)
        self.assertEqual(profile_sizes(ctx, own), ("own_mm",))
        for other in (dict(own, borrowed="Lid"), dict(own, foreign=True)):
            self.assertIsNone(graph_for(capture, other))
            self.assertEqual(profile_sizes(ctx, other), ())

    def test_the_sketch_plane_of_an_outline_of_another_component_names_no_sizes_of_the_part(self):
        table = size_table.build([user("w_mm", "5 mm", 5)], ["w_mm"], [])
        timeline = [{"index": 0, "type": "ExtrudeFeature", "in_target_component": True,
                     "data": {"params": {"extent.distance": {"name": "d1", "expression": "w_mm", "value": 5}}}}]
        profile = {"reference": {"kind": "face"}, "sketch": "Rim",
                   "frame": {"origin": [0, 0, 5], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}}
        self.assertEqual(placement_sizes(table, timeline, profile, 1), ["w_mm"])
        self.assertEqual(placement_sizes(table, timeline, dict(profile, borrowed="Lid"), 1), [])


if __name__ == "__main__":
    unittest.main()
