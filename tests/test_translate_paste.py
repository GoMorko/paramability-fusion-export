"""Copy Paste Body: the steps of the source written again (lib/translator/paste.py)."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import load_capture, steps_of, verdict_of

from lib.params import size_table
from lib.translator import translate, vec
from lib.translator.step_walk import all_steps

CHAIN = "paste_move_offset"
PASTE = 4


def sized(capture):
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"], "mm")
    return translate(capture, size_table=table)


def marked(result):
    return sorted({d["name"] for d in result.loose + result.fixed + [d for d in result.dropped if d.get("used")]})


def short_chain():
    """A pasted peg cut from the plate at once: plate, peg, paste, Combine."""
    capture = load_capture(CHAIN)
    combine = capture["items"][-1]
    capture["items"] = capture["items"][:PASTE + 1] + [combine]
    combine["index"] = PASTE + 1
    combine["data"].update(tools=[{"token": "t3", "name": "Body3"}], volume_before=None, volume_after=None)
    return capture


def paste_data(capture):
    return capture["items"][PASTE]["data"]


class PastedToolTest(unittest.TestCase):
    def test_the_whole_chain_is_copied(self):
        result = sized(load_capture(CHAIN))
        self.assertEqual([s["kind"] for s in result.recipe["features"]], ["extrude", "toolBody", "pattern"])
        tool = result.recipe["features"][1]
        self.assertEqual([s["kind"] for s in tool["features"]], ["extrude", "move", "move", "move", "offsetFaces"])
        self.assertEqual(result.recipe["features"][2]["of"], [tool["id"]])
        self.assertEqual(result.recipe["features"][2]["polar"]["count"], {"expr": "ring_n"})
        self.assertEqual(marked(result), [])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_ids_are_unique(self):
        ids = [s["id"] for s in all_steps(translate(load_capture(CHAIN)).recipe["features"])]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_pasted_tool_is_a_tool_step_even_when_it_only_adds(self):
        result = translate(short_chain())
        self.assertEqual([s["kind"] for s in result.recipe["features"]], ["extrude", "toolBody"])

    def test_the_verdict_holds_the_steps_of_the_source(self):
        verdict = verdict_of(translate(short_chain()), 5)["tool_steps"]
        self.assertEqual([v["name"] for v in verdict], ["CopyPaste1"])
        self.assertEqual([v["name"] for v in verdict[0]["tool_steps"]], ["Extrude2"])

    def test_a_forgotten_value_of_the_source_is_loose(self):
        capture = short_chain()
        capture["items"][3]["data"]["params"]["forgotten"] = {"name": "d9", "expression": "gap_mm", "value": 25.0}
        self.assertIn("gap_mm", marked(sized(capture)))

    def test_a_paste_of_a_paste_repeats_the_first_source(self):
        capture = short_chain()
        second = copy.deepcopy(capture["items"][PASTE])
        second.update(index=5, name="CopyPaste2", bodies_after=[{"token": "t7", "name": "Body7"}])
        points = paste_data(capture)["sources"][0]["points"]
        second["data"] = {"sources": [{"token": "t3", "name": "Body3", "points": points}],
                          "result_bodies": [{"token": "t7", "name": "Body7", "points": points}]}
        capture["items"].insert(5, second)
        combine = capture["items"][-1]
        combine["index"] = 6
        combine["data"]["tools"] = [{"token": "t7", "name": "Body7"}]
        self.assertEqual([s["kind"] for s in steps_of(translate(capture).recipe, "toolBody")[0]["features"]], ["extrude"])

    def test_an_exported_body_that_is_a_paste_starts_with_the_steps_of_its_source(self):
        capture = short_chain()
        capture["target"] = dict(capture["target"], token="t3", name="Body3")
        del capture["items"][-1]
        result = translate(capture)
        self.assertEqual([s["kind"] for s in result.recipe["features"]], ["extrude"])
        self.assertEqual(result.recipe["features"][0]["sketch"]["on"]["origin"], [0.0, 0.0, 20.0])

    def test_a_paste_at_another_place_adds_a_move_and_marks_the_sizes(self):
        capture = short_chain()
        result_body = paste_data(capture)["result_bodies"][0]
        result_body["points"] = [vec.add(p, [5, 0, 0]) for p in result_body["points"]]
        result = sized(capture)
        self.assertEqual(result.recipe["features"][1]["features"][1]["translate"], [5.0, 0.0, 0.0])
        self.assertIn("peg_len_mm", marked(result))

    def test_a_source_of_another_component_is_not_a_step_that_reaches_into_it(self):
        capture = short_chain()
        peg = capture["items"][3]
        peg.update(in_target_component=False, component="rod", helper_of="t3")
        paste_data(capture)["sources"][0].update(foreign=True, component={"token": "rod", "name": "Rod"})
        self.assertEqual([s["kind"] for s in translate(capture).recipe["features"]], ["extrude", "toolBody"])


class RefusedPasteTest(unittest.TestCase):
    def test_each_paste_that_cannot_be_copied_exactly_refuses(self):
        def bent(data):
            points = data["result_bodies"][0]["points"]
            points[0] = vec.add(points[0], [1, 0, 0])

        cases = {
            "no source": lambda d: d.update(sources=[]),
            "results unread": lambda d: d.update(result_bodies=None),
            "another result": lambda d: d.update(result_bodies=[{"token": "t9", "name": "Body9", "points": []}]),
            "corners unread": lambda d: d["sources"][0].update(points=[]),
            "does not match": bent,
        }
        for name, edit in cases.items():
            with self.subTest(name):
                capture = short_chain()
                edit(paste_data(capture))
                self.assertEqual(translate(capture).refusal["name"], "Combine1")

    def test_a_source_that_cannot_be_copied_names_its_step(self):
        capture = short_chain()
        capture["items"][3]["type"] = "SweepFeature"
        self.assertIn("Extrude2", translate(capture).refusal["reason"])

    def test_a_paste_chain_past_the_depth_limit_refuses(self):
        capture = short_chain()
        points = paste_data(capture)["sources"][0]["points"]
        for n, (source, result) in enumerate(((3, 7), (7, 8), (8, 9))):
            capture["items"].insert(5 + n, {
                "index": 5 + n, "name": "CopyPaste%d" % (n + 2), "type": "CopyPasteBody", "suppressed": False, "health": "ok",
                "message": "", "in_target_component": True, "bodies_after": [{"token": "t%d" % result, "name": "Body%d" % result}],
                "data": {"sources": [{"token": "t%d" % source, "name": "Body%d" % source, "points": points}],
                         "result_bodies": [{"token": "t%d" % result, "name": "Body%d" % result, "points": points}]}})
        combine = capture["items"][-1]
        combine["index"] = 8
        combine["data"]["tools"] = [{"token": "t9", "name": "Body9"}]
        self.assertEqual(translate(capture).refusal["name"], "Combine1")


if __name__ == "__main__":
    unittest.main()
