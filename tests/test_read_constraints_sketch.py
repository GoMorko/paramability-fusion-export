"""The sketch graph reader on whole sketches: a rectangle, entity matching by identity, limits, and which sketches a
capture reads."""
import json
import unittest
from types import SimpleNamespace

from tests import context  # noqa: F401
from tests.sketch_graph_fakes import Coll, Thing, constraint, point, rectangle, sketch

from lib.fusion_reader import read_constraints
from lib.fusion_reader.read_constraints import read_sketch_graph, sketch_graphs

PART = Thing(key="part", entityToken="cmp_part", name="Part")
CTX = SimpleNamespace(component=PART)


class RectangleTest(unittest.TestCase):
    def setUp(self):
        self.graph = read_sketch_graph(rectangle(40.0, 25.0), CTX)

    def test_the_rectangle_is_four_lines_on_four_shared_points(self):
        graph = self.graph
        self.assertEqual([p["xy"] for p in graph["points"]], [[40.0, 0.0], [40.0, 25.0], [0.0, 25.0], [0.0, 0.0]])
        self.assertEqual([p["origin"] for p in graph["points"]], [False, False, False, True])
        self.assertEqual(graph["origin"], 3)
        self.assertEqual([(c["kind"], c["points"]) for c in graph["curves"]],
                         [("line", [3, 0]), ("line", [0, 1]), ("line", [1, 2]), ("line", [2, 3])])
        self.assertEqual((graph["fully_constrained"], graph["cut"]), (True, ""))
        self.assertNotIn("unread", graph)

    def test_the_constraints_name_the_lines_and_the_corner_on_the_origin(self):
        self.assertEqual([(c["type"], c["on"]) for c in self.graph["constraints"]],
                         [("horizontal", [["line", 0]]), ("vertical", [["line", 1]]),
                          ("horizontal", [["line", 2]]), ("vertical", [["line", 3]]),
                          ("coincident", [["point", 3], ["line", 0]])])

    def test_the_two_dimensions_name_their_points_parameters_and_values(self):
        width, height = self.graph["dimensions"]
        self.assertEqual((width["type"], width["orientation"], width["on"], width["value"]),
                         ("linear", "horizontal", [["point", 3], ["point", 0]], 40.0))
        self.assertEqual((width["param"], width["expression"], width["reads"]), ("d1", "Width", ["Width"]))
        self.assertEqual((height["orientation"], height["on"], height["value"], height["expression"]),
                         ("vertical", [["point", 3], ["point", 2]], 25.0, "25 mm"))

    def test_the_record_is_plain_json(self):
        self.assertEqual(json.loads(json.dumps(self.graph)), self.graph)


class IdentityTest(unittest.TestCase):
    def test_two_entities_with_one_token_text_stay_two_entities(self):
        a0, a1 = point("a0", 0, 0), point("a1", 5, 0)
        twin = point("twin", 9, 9, entityToken="tok_a0")
        sk = sketch([a0, a1], constraints=[constraint("HorizontalPointsConstraint", "c", pointOne=a1.wrapper(True),
                                                      pointTwo=twin)])
        graph = read_sketch_graph(sk, CTX)
        [record] = graph["constraints"]
        self.assertEqual(record["on"][0], ["point", 1])
        self.assertNotEqual(record["on"][1], ["point", 0])
        self.assertTrue(graph["points"][record["on"][1][1]]["implicit"])

    def test_another_wrapper_of_a_listed_point_resolves_to_the_listed_id(self):
        a0 = point("a0", 0, 0)
        sk = sketch([a0], constraints=[constraint("HorizontalPointsConstraint", "c", pointOne=a0.wrapper(True),
                                                  pointTwo=a0.wrapper(True))])
        [record] = read_sketch_graph(sk, CTX)["constraints"]
        self.assertEqual(record["on"], [["point", 0], ["point", 0]])


class LimitsAndFailuresTest(unittest.TestCase):
    def over(self, member, count):
        sk = sketch()
        getattr(sk, member).count = count
        return read_sketch_graph(sk, CTX)

    def test_a_sketch_over_a_limit_names_it_and_lists_nothing(self):
        for member, limit, cut in (("sketchPoints", read_constraints.MAX_ENTITIES, "entities"),
                                   ("sketchDimensions", read_constraints.MAX_DIMENSIONS, "dimensions"),
                                   ("geometricConstraints", read_constraints.MAX_CONSTRAINTS, "constraints")):
            with self.subTest(cut):
                graph = self.over(member, limit + 1)
                self.assertEqual(graph["cut"], cut)
                self.assertEqual((graph["points"], graph["curves"], graph["dimensions"], graph["constraints"]),
                                 ([], [], [], []))
        self.assertEqual(self.over("sketchPoints", read_constraints.MAX_ENTITIES)["cut"], "")

    def test_a_sketch_whose_members_all_raise_says_what_it_could_not_read(self):
        class Broken:
            def __getattr__(self, name):
                raise RuntimeError("gone")
        graph = read_sketch_graph(Broken(), CTX)
        self.assertEqual(sorted(graph["unread"]), ["geometricConstraints", "isFullyConstrained", "sketchCurves",
                                                   "sketchDimensions", "sketchPoints"])
        self.assertEqual((graph["fully_constrained"], graph["points"], graph["dimensions"]), (None, [], []))

    def test_a_collection_item_that_cannot_be_fetched_keeps_its_place_as_an_unread_record(self):
        class Flaky(Coll):
            def item(self, i):
                if i == 0:
                    raise RuntimeError("no")
                return super().item(i)
        sk = sketch([point("p", 1, 1)])
        sk.sketchDimensions = Flaky([Thing("SketchDiameterDimension", "d")])
        sk.geometricConstraints = Flaky([constraint("HorizontalConstraint", "c")])
        graph = read_sketch_graph(sk, CTX)
        self.assertEqual([(d["id"], d["unknown"], d["unread"]) for d in graph["dimensions"]], [(0, True, ["item"])])
        self.assertEqual([(c["id"], c["unknown"], c["unread"]) for c in graph["constraints"]], [(0, True, ["item"])])


def _design(sketches):
    return SimpleNamespace(findEntityByToken=lambda token: [sketches[token]] if token in sketches else [])


def _item(data, **flags):
    return {"in_target_component": True, "data": data, **flags}


class SketchesReadTest(unittest.TestCase):
    def test_own_and_borrowed_sketches_are_read_once_each_and_the_others_are_skipped(self):
        own, lent = rectangle(10, 10), rectangle(20, 20)
        items = [
            _item({"profiles": [{"sketch": "Own", "sketch_token": "t_own"}]}),
            _item({"profiles": [{"sketch": "Own", "sketch_token": "t_own"},
                                {"sketch": "Lid", "sketch_token": "t_lent", "foreign": True}]}),
            _item({"profiles": [{"sketch": "Skipped", "sketch_token": "t_off"}]}, suppressed=True),
            {"in_target_component": False, "data": {"profiles": [{"sketch": "Tool", "sketch_token": "t_tool"}]}},
        ]
        found = sketch_graphs(_design({"t_own": own, "t_lent": lent, "t_off": own, "t_tool": own}), CTX, items)
        self.assertEqual([(r["sketch"], r["token"], r.get("borrowed", False)) for r in found],
                         [("Own", "t_own", False), ("Lid", "t_lent", True)])
        self.assertEqual(found[1]["points"][0]["xy"], [20.0, 0.0])

    def test_a_sketch_named_by_an_own_and_a_foreign_record_is_not_borrowed(self):
        items = [_item({"a": {"sketch_token": "t", "foreign": True}}), _item({"b": {"sketch_token": "t"}})]
        [record] = sketch_graphs(_design({"t": sketch()}), CTX, items)
        self.assertNotIn("borrowed", record)

    def test_a_sketch_that_cannot_be_found_is_an_error_record(self):
        [record] = sketch_graphs(_design({}), CTX, [_item({"p": {"sketch": "Gone", "sketch_token": "t"}})])
        self.assertEqual(record, {"sketch": "Gone", "token": "t", "error": "The sketch could not be found."})

    def test_sketches_past_the_limit_are_named_and_not_read(self):
        count = read_constraints.MAX_SKETCHES + 2
        items = [_item({"p": {"sketch": "S%d" % i, "sketch_token": "t%d" % i}}) for i in range(count)]
        found = sketch_graphs(_design({"t%d" % i: sketch() for i in range(count)}), CTX, items)
        self.assertEqual([r.get("cut") == "sketches" for r in found].count(True), 2)
        self.assertEqual(found[-1], {"sketch": "S%d" % (count - 1), "token": "t%d" % (count - 1), "cut": "sketches"})


if __name__ == "__main__":
    unittest.main()
