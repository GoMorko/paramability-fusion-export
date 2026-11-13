"""Patterns of bodies, and Combines that take them (lib/translator/repeat/body_copies.py)."""
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import left_out
from tests.translator_helpers import load_capture, steps_of

from lib.geometry import vec
from lib.params import size_table
from lib.params.expressions import evaluate
from lib.translator import translate
from lib.translator.repeat import body_copies
from lib.translator.step_walk import all_steps

ROW = "pattern_bodies_combine"
SUBSET = "pattern_bodies_subset"
FINISH = "pattern_target_finish"


def sized(capture):
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"], "mm")
    return translate(capture, size_table=table)


def marked(result):
    return sorted({d["name"] for d in result.loose + result.fixed + [d for d in result.dropped if d.get("used")]})


def kinds(result):
    return [s["kind"] for s in result.recipe["features"]]


def pattern_item(capture):
    return next(i for i in capture["items"] if (i.get("data") or {}).get("entity_type") == "bodies")


class MatchTest(unittest.TestCase):
    SOURCE = {"token": "a", "points": [[0, 0, 0], [1, 0, 0]]}

    def data(self, result_points):
        frame = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        return {"source_bodies": [self.SOURCE], "result_bodies": [{"token": "b", "points": result_points}], "elements": [
            {"id": 1, "suppressed": False, "frame": dict(frame, origin=[0, 0, 0])},
            {"id": 2, "suppressed": False, "frame": dict(frame, origin=[5, 0, 0])}]}

    def test_a_copy_is_paired_with_the_element_that_lands_on_it_in_any_order(self):
        (found,) = body_copies.match(self.data([[6, 0, 0], [5, 0, 0]]))
        self.assertEqual((found.result["token"], found.source["token"]), ("b", "a"))
        self.assertEqual(found.motion.numbers([0, 0, 0]), [5.0, 0.0, 0.0])

    def test_a_copy_no_element_lands_on_does_not_match(self):
        self.assertIsNone(body_copies.match(self.data([[7, 0, 0], [8, 0, 0]])))

    def test_a_result_that_is_the_source_is_not_a_copy(self):
        data = self.data([[5, 0, 0], [6, 0, 0]])
        data["result_bodies"].append(dict(self.SOURCE))
        self.assertEqual(len(body_copies.match(data)), 1)


class WholePatternTest(unittest.TestCase):
    def test_the_sources_become_tools_and_the_layout_one_step(self):
        result = sized(load_capture(ROW))
        self.assertEqual(kinds(result), ["extrude", "toolBody", "pattern"])
        tool, pattern = result.recipe["features"][1:]
        self.assertEqual(pattern["of"], [tool["id"]])
        self.assertEqual((pattern["linear"]["count"], pattern["linear"]["step"]), ({"expr": "row_n"}, {"expr": "pitch_mm"}))
        self.assertEqual(tool["combine"], "add")
        self.assertEqual(marked(result), ["row_n"])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_a_forgotten_value_of_the_pattern_is_loose(self):
        capture = load_capture(ROW)
        pattern_item(capture)["data"]["params"]["forgotten"] = {"name": "d9", "expression": "peg_len_mm", "value": 6.0}
        self.assertIn("peg_len_mm", marked(sized(capture)))

    def test_two_combines_of_one_kept_pattern_have_distinct_ids(self):
        capture = load_capture(ROW)
        combine = capture["items"][-1]
        combine["data"].update(keep_tools=True, volume_before=None, volume_after=None)
        capture["items"].append(dict(combine, index=6, name="Combine2"))
        ids = [s["id"] for s in all_steps(translate(capture).recipe["features"])]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_mirror_of_bodies_is_a_mirror_of_the_tool(self):
        capture = load_capture(ROW)
        item = pattern_item(capture)
        source = item["data"]["source_bodies"][0]
        image = {"token": "t3", "name": "Body3", "points": [[-p[0], p[1], p[2]] for p in source["points"]]}
        item.update(type="MirrorFeature", bodies_after=[{"token": "t3", "name": "Body3"}])
        item["data"] = {"entity_type": "bodies", "sources": [], "source_bodies": [source], "result_bodies": [image], "combine": False,
                        "plane": {"point": [0, 0, 0], "normal": [1, 0, 0], "origin": True}}
        capture["items"][-1]["data"].update(tools=[{"token": "t2", "name": "Body2"}, {"token": "t3", "name": "Body3"}],
                                            volume_before=None, volume_after=None)
        result = translate(capture)
        self.assertEqual(kinds(result), ["extrude", "toolBody", "mirror"])
        self.assertEqual(check_recipe(result.recipe), [])


class CopyByCopyTest(unittest.TestCase):
    def test_a_subset_is_one_tool_per_copy_and_the_count_is_marked(self):
        result = sized(load_capture(SUBSET))
        tools = steps_of(result.recipe, "toolBody")
        self.assertEqual([[s["kind"] for s in t["features"]] for t in tools], [["extrude"], ["extrude", "move"], ["extrude", "move"]])
        self.assertEqual([t["features"][1]["turn"]["angleDeg"] for t in tools[1:]], [60.0, 180.0])
        self.assertEqual(marked(result), ["ring_n"])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_a_copy_changed_from_another_component_refuses(self):
        capture = load_capture(ROW)
        combine = capture["items"].pop()
        capture["items"].append(dict(capture["items"][3], index=5, name="Elsewhere", in_target_component=False,
                                     bodies_after=[{"token": "t3", "name": "Body3"}], data={}))
        combine["index"] = 6
        capture["items"].append(combine)
        self.assertIn("Elsewhere", left_out(translate(capture))["reason"])

    def test_an_uneven_layout_falls_back_to_one_tool_per_copy(self):
        capture = load_capture(ROW)
        data = pattern_item(capture)["data"]
        offset = [45, 0, 0]
        data["elements"][2]["frame"]["origin"] = offset
        source = data["source_bodies"][0]["points"]
        data["result_bodies"][1]["points"] = [vec.add(p, offset) for p in source]
        result = sized(capture)
        self.assertEqual(kinds(result), ["extrude", "toolBody", "toolBody", "toolBody"])
        self.assertIn("pitch_mm", marked(result))

    def test_a_copy_changed_after_the_pattern_keeps_its_own_steps(self):
        capture = load_capture(ROW)
        combine = capture["items"].pop()
        later = {"index": 5, "name": "Offset1", "type": "OffsetFacesFeature", "suppressed": False, "health": "ok", "message": "",
                 "in_target_component": True, "bodies_after": [{"token": "t3", "name": "Body3"}], "data": {
                     "distance": 1.0, "faces_after": [{"point": [28, 10, 15], "normal": [0, 0, 1]}], "faces": [{
                         "token": "f1", "frame": {"origin": [28, 10, 14], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]},
                         "space": "sketch", "sides": "square", "meets_offset": False, "loops": [{"outer": True, "curves": [
                             {"kind": "circle", "center": [0, 0], "radius": 3}]}]}]}}
        combine["index"] = 6
        combine["data"].update(volume_before=None, volume_after=None)
        capture["items"] += [later, combine]
        result = translate(capture)
        self.assertEqual([[s["kind"] for s in t["features"]] for t in steps_of(result.recipe, "toolBody")],
                         [["extrude"], ["extrude", "move", "offsetFaces"], ["extrude", "move"]])

    def test_an_exported_body_that_is_a_copy_starts_with_its_source(self):
        capture = load_capture(SUBSET)
        capture["target"] = dict(capture["target"], token="t3", name="Body3")
        del capture["items"][-1]
        self.assertEqual(kinds(translate(capture)), ["extrude", "move"])

    def test_an_intersect_of_copies_is_not_repeated(self):
        capture = load_capture(ROW)
        capture["items"][-1]["data"].update(operation="intersect", intersect_model="every", volume_before=None, volume_after=None)
        self.assertEqual(kinds(translate(capture)), ["extrude", "toolBody", "toolBody", "toolBody"])


class TargetIsASourceTest(unittest.TestCase):
    def test_finished_steps_are_gathered_into_one_tool(self):
        result = sized(load_capture(FINISH))
        self.assertEqual(kinds(result), ["toolBody", "pattern"])
        tool, pattern = result.recipe["features"]
        self.assertEqual((tool["combine"], [s["kind"] for s in tool["features"]]), ("new", ["extrude", "round"]))
        self.assertEqual(pattern["of"], [tool["id"]])
        self.assertEqual(marked(result), [])
        self.assertEqual(check_recipe(result.recipe), [])

    def without_the_round(self):
        capture = load_capture(FINISH)
        del capture["items"][2]
        return capture

    def test_steps_that_only_add_are_repeated_as_they_are(self):
        result = translate(self.without_the_round())
        self.assertEqual(kinds(result), ["extrude", "pattern"])
        self.assertEqual(result.recipe["features"][1]["of"], [result.recipe["features"][0]["id"]])

    def test_a_cut_by_its_own_copies_is_one_tool_per_copy(self):
        capture = self.without_the_round()
        capture["items"][-1]["data"].update(operation="cut", volume_before=None, volume_after=None)
        self.assertEqual(kinds(translate(capture)), ["extrude", "toolBody", "toolBody"])

    def test_a_later_pick_on_the_gathered_body_never_names_a_step_inside_it(self):
        capture = load_capture(FINISH)
        capture["items"].append({
            "index": 5, "name": "Fillet2", "type": "FilletFeature", "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}], "data": {"rolling_ball": True, "sets": [
                {"kind": "constant", "radius": 0.5, "continuity": "tangent", "input_kinds": ["edge"],
                 "edges": [{"token": "e1", "closed": False, "points": [[0, 0, 2.5]]}]}]}})
        last = sized(capture).recipe["features"][-1]
        self.assertEqual(evaluate(last["edges"]["near"][0][2]["expr"], {"block_h_mm": 8}), 4.0)


class RefusedPatternTest(unittest.TestCase):
    def test_copies_that_cannot_be_paired_refuse(self):
        cases = {"results unread": lambda d: d.update(result_bodies=None),
                 "points unread": lambda d: d["source_bodies"][0].update(points=[]),
                 "elements unread": lambda d: d.update(elements=[])}
        for name, edit in cases.items():
            with self.subTest(name):
                capture = load_capture(ROW)
                edit(pattern_item(capture)["data"])
                self.assertEqual(left_out(translate(capture))["name"], "Combine1")

    def test_a_mirrored_copy_without_its_source_refuses(self):
        capture = load_capture(ROW)
        item = pattern_item(capture)
        source = item["data"]["source_bodies"][0]
        image = {"token": "t3", "name": "Body3", "points": [[-p[0], p[1], p[2]] for p in source["points"]]}
        item.update(type="MirrorFeature", bodies_after=[{"token": "t3", "name": "Body3"}])
        item["data"] = {"entity_type": "bodies", "sources": [], "source_bodies": [source], "result_bodies": [image], "combine": False,
                        "plane": {"point": [0, 0, 0], "normal": [1, 0, 0], "origin": True}}
        capture["items"][-1]["data"].update(tools=[{"token": "t3", "name": "Body3"}], volume_before=None, volume_after=None)
        self.assertEqual(left_out(translate(capture))["name"], "Combine1")

    def test_a_mirror_of_the_whole_body_after_a_cutting_tool_mirrors_the_gathered_body(self):
        capture = load_capture("combine_tool_chamfer")
        capture["items"].append({
            "index": 6, "name": "Mirror1", "type": "MirrorFeature", "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}], "data": {
                "entity_type": "bodies", "combine": True, "sources": [], "plane": {"point": [40, 0, 0], "normal": [1, 0, 0], "origin": True},
                "target_box_before": capture["target"]["box"]}})
        result = translate(capture)
        self.assertEqual(steps_of(result.recipe, "mirror")[0]["of"], [result.recipe["features"][0]["id"]])

    def test_more_copies_than_the_recipe_holds_refuse(self):
        capture = load_capture(ROW)
        data = pattern_item(capture)["data"]
        source = data["source_bodies"][0]
        frame = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        count = 258
        data.update(quantity_one=count, params={}, elements=[
            {"id": n + 1, "suppressed": False, "frame": dict(frame, origin=[20 * n, 0, 0])} for n in range(count)])
        data["result_bodies"] = [{"token": "c%d" % n, "name": "C%d" % n, "points": [vec.add(p, [20 * n, 0, 0]) for p in source["points"]]}
                                 for n in range(1, count)]
        records = [{"token": r["token"], "name": r["name"]} for r in data["result_bodies"]]
        pattern_item(capture)["bodies_after"] = records
        capture["items"][-1]["data"].update(tools=[{"token": "t2", "name": "Body2"}] + records, volume_before=None, volume_after=None)
        refusal = translate(capture).refusal
        self.assertIsNone(refusal["index"])


if __name__ == "__main__":
    unittest.main()
