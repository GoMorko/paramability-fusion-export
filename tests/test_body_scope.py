import unittest

from tests import context  # noqa: F401
from lib.export_plan.body_scope import body_items, other_sketches, quantity_refs, scope_inputs, scoped_model_params

A = {"token": "a", "name": "Body1"}
B = {"token": "b", "name": "Body2"}


def item(index, name, type_name, bodies, **data):
    return {"index": index, "name": name, "type": type_name, "suppressed": False, "bodies_after": bodies, "data": data}


def model(name, expression, kind, owner="", sketch=""):
    return {"name": name, "expression": expression, "dependency_parameters": [], "created_by": {
        "kind": kind, "name": owner, "token": "", "sketch": sketch}}


def capture():
    return {
        "capture": 2, "target": A,
        "items": [
            item(0, "Sketch1", "Sketch", []),
            item(1, "Extrude1", "ExtrudeFeature", [A], profiles=[{"sketch": "Sketch1"}]),
            item(2, "Sketch2", "Sketch", []),
            item(3, "Extrude2", "ExtrudeFeature", [B], profiles=[{"sketch": "Sketch2"}], operation="newBody"),
            item(4, "Pattern1", "RectangularPatternFeature", [A], params={
                "quantity_one": {"name": "d9", "expression": "holes", "value": 3.0},
                "distance_one": {"name": "d10", "expression": "pitch", "value": 5.0}}),
        ],
        "parameters": {"user": [], "model": [
            model("d1", "wall", "sketchDimension", sketch="Sketch1"),
            model("d2", "wall * 2", "feature", "Extrude1"),
            model("d3", "other", "sketchDimension", sketch="Sketch2"),
            model("d4", "other", "feature", "Extrude2"),
            model("d5", "d4 + 1 mm", "feature", "Extrude1"),
            model("d6", "5 mm", "constructionPlane"),
            model("d7", "5 mm", "sketchDimension"),
        ]},
    }


def in_components(cap):
    """The same capture with the steps of Body2 in component cB and the rest in cA."""
    for it in cap["items"]:
        it["component"] = "cB" if it["name"] in ("Sketch2", "Extrude2") else "cA"
    for p in cap["parameters"]["model"]:
        made = p["created_by"]
        made["component"] = "cB" if made.get("sketch") == "Sketch2" or made.get("name") == "Extrude2" else "cA"
    return cap


class BodyScopeTest(unittest.TestCase):
    def test_steps_of_the_picked_body_only(self):
        self.assertEqual([i["name"] for i in body_items(capture())], ["Extrude1", "Pattern1"])

    def test_a_tool_body_combined_into_the_target_brings_its_steps(self):
        cap = capture()
        cap["items"].append(item(5, "Combine1", "CombineFeature", [A], target=A, tools=[B], operation="cut"))
        self.assertIn("Extrude2", {i["name"] for i in body_items(cap)})
        self.assertEqual(other_sketches(cap), set())

    def test_parameters_of_other_bodies_are_left_out_but_what_a_kept_one_reads_stays(self):
        kept = {p["name"] for p in scoped_model_params(capture())}
        self.assertEqual(kept, {"d1", "d2", "d4", "d5", "d6", "d7"})

    def test_sketches_only_other_bodies_use(self):
        self.assertEqual(other_sketches(capture()), {("", "Sketch2")})

    def test_sketch_and_step_names_are_matched_with_their_component(self):
        cap = in_components(capture())
        cap["items"][2]["name"], cap["items"][3]["name"] = "Sketch1", "Extrude1"
        cap["items"][3]["data"]["profiles"] = [{"sketch": "Sketch1"}]
        cap["parameters"]["model"][2]["created_by"]["sketch"] = "Sketch1"
        cap["parameters"]["model"][3]["created_by"]["name"] = "Extrude1"
        self.assertEqual(other_sketches(cap), {("cB", "Sketch1")})
        kept = {p["name"] for p in scoped_model_params(cap)}
        self.assertEqual(kept, {"d1", "d2", "d4", "d5", "d6", "d7"})

    def test_quantity_parameters_come_from_the_steps_of_the_body(self):
        self.assertEqual([r["name"] for r in quantity_refs(capture())], ["d9"])

    def test_without_a_capture_the_whole_root_is_used(self):
        fallback = [model("d1", "1 mm", "feature", "X")]
        self.assertEqual(scope_inputs(RuntimeError("x"), fallback), (fallback, []))


if __name__ == "__main__":
    unittest.main()
