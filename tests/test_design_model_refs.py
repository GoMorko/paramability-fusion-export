"""Which sizes may move a reference of another component (`design_model/refs.py`), and what each output does when the
capture cannot say.

Fixtures: `component_foreign_mirror` (a mirror across a plane of Cover; gap_mm acts on Cover and on the part) and
`component_tool_foreign` (a box cut by a tool made in the component Rod; rod_x acts on Rod, here moved to a joint in
the root that places Rod)."""
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture, table_of
from tests.probe_helpers import user

from lib import orca_translate, translator
from lib.design_model import refs

ROD = {"token": "cRod", "name": "Rod"}
COVER = {"token": "cCover", "name": "Cover"}


class Recorder:
    def __init__(self, capture, ticked):
        self.capture, self.cache, self.motion = capture, {}, None
        self.table = type("Table", (), {"ticked": list(ticked)})()
        self.events = []

    def doubt(self, names, why):
        self.events.append(("doubt", tuple(names)))

    def note(self, text):
        self.events.append(("note", text))

    def follow_component(self, component):
        self.events.append(("follow", component))

    def movers_unknown(self, phrase):
        self.events.append(("unknown", phrase))


def acting(name, **dependent):
    return dict(user(name, "5 mm", 5), dependents=[dict({"name": "d_" + name}, **dependent)])


def capture_with(users, *items):
    return {"target": {"token": "t1", "name": "Body1", "component": {"token": "cPart", "name": "Part"}},
            "parameters": {"user": users}, "items": list(items)}


def move(name, component, input_kind):
    return {"index": 9, "name": name, "type": "MoveFeature", "component": component, "data": {"input_kind": input_kind}}


ASSEMBLY = [
    acting("on_rod", kind="feature", component="cRod", feature="Extrude1"),
    acting("joint_x", kind="joint", component="cRoot", feature="Rigid1"),
    acting("move_x", kind="feature", component="cRoot", feature="Move1"),
    acting("body_x", kind="feature", component="cRoot", feature="Move2"),
]
ITEMS = (move("Move1", "cRoot", "other"), move("Move2", "cRoot", "bodies"))
NAMES = [p["name"] for p in ASSEMBLY]


class ActingSizesTest(unittest.TestCase):
    def sizes(self, ref):
        return refs.acting_sizes(Recorder(capture_with(ASSEMBLY, *ITEMS), NAMES), ref)

    def test_joints_and_moves_of_occurrences_move_every_other_component(self):
        self.assertEqual(self.sizes({"component": ROD}), (["on_rod", "joint_x", "move_x"], True))
        self.assertEqual(self.sizes({"component": COVER}), (["joint_x", "move_x"], True))

    def test_a_reference_of_the_part_itself_does_not_move_with_the_assembly(self):
        self.assertEqual(self.sizes({"component": ROD, "own": True}), (["on_rod"], True))
        self.assertEqual(self.sizes({"component": {"token": "cPart"}}), ([], True))

    def test_the_place_of_the_root_moves_only_with_the_assembly(self):
        self.assertEqual(self.sizes({"component": {"token": "cRoot"}, "root": True}), (["joint_x", "move_x"], True))

    def test_without_data_on_where_sizes_act_the_recorder_is_told_and_nothing_is_marked(self):
        users = [user("gap_mm", "5 mm", 5)]
        ctx = Recorder(capture_with(users), ["gap_mm"])
        refs.mark_all(ctx, {"name": "Mirror1"}, {"component": COVER, "type": "ConstructionPlane"}, "mirrors across")
        self.assertEqual([kind for kind, _ in ctx.events], ["unknown"])


def without_dependents(capture):
    for p in capture["parameters"]["user"]:
        p.pop("dependents")
    return capture


def rod_jointed_in_the_root(capture):
    """`component_tool_foreign` with rod_x read only by the offset of a joint in the root that places Rod."""
    rod_x = next(p for p in capture["parameters"]["user"] if p["name"] == "rod_x")
    rod_x["dependents"] = [{"name": "d9", "kind": "joint", "component": "cRoot", "feature": "Rigid1"}]
    return capture


def recipe_marks(capture):
    result = translator.translate(capture, size_table=table_of(capture))
    found = {d["name"] for d in result.dropped if d.get("used")}
    return found | {d["name"] for d in result.loose + result.fixed}, result


class OutputsTest(unittest.TestCase):
    def test_the_recipe_copies_with_a_note_when_the_sizes_on_another_component_are_unknown(self):
        marks, result = recipe_marks(without_dependents(fixture("component_foreign_mirror")))
        self.assertNotIn("gap_mm", marks)
        self.assertEqual([v["verdict"] for v in result.items if v["index"] == 4], ["translatedWithNote"])

    def test_the_orca_copy_fixes_every_size_when_the_sizes_on_another_component_are_unknown(self):
        capture = without_dependents(fixture("component_foreign_mirror"))
        result = orca_translate.translate(capture, table_of(capture))
        self.assertEqual({p["outcome"] for p in result.parameters} & {"variable", "unused"}, set())

    def test_a_joint_in_the_root_moves_the_tool_in_both_outputs(self):
        capture = rod_jointed_in_the_root(fixture("component_tool_foreign"))
        self.assertIn("rod_x", recipe_marks(capture)[0])
        result = orca_translate.translate(capture, table_of(capture))
        self.assertEqual({p["name"]: p["outcome"] for p in result.parameters}["rod_x"], "fixed")


if __name__ == "__main__":
    unittest.main()
