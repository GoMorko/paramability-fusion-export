"""The design as both walks read it (`design_model/design.py`): one resolved step per timeline item, with its role,
what about it cannot be read, and the geometry of other components brought in, whose doubts and notes wait until a
walk replays them."""
import unittest

from tests import context  # noqa: F401

from lib.capture_model import step_kinds
from lib.design_model import design, roles
from lib.design_model.steps import finish, repeat

PART = {"token": "t1", "name": "Body1"}
FRAME = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


def item(index=1, kind="ExtrudeFeature", **more):
    found = {"index": index, "name": "Step%d" % index, "type": kind, "suppressed": False,
             "in_target_component": True, "bodies_after": [PART], "data": {}}
    found.update(more)
    return found


def borrowing(index=1, **more):
    """An extrude of an outline of the sketch Top of the component Lid, with a known place."""
    profile = {"foreign": True, "sketch": "Top", "sketch_token": "s1", "frame": FRAME, "native_frame": FRAME,
               "component": {"token": "cLid", "name": "Lid"}, "placement": {"frame": FRAME},
               "sketch_params": [{"reads": ["lid_w"]}], "loops": []}
    return item(index, data={"profiles": [profile]}, **more)


class Table:
    """A size table in which every size is ticked and depends on itself."""

    model_params = {}
    ticked = ("lid_w",)

    def depends(self, name):
        return {name}


class Recorder:
    def __init__(self, capture, table=None):
        self.capture, self.table, self.cache, self.motion = capture, table, {}, None
        self.events = []

    def doubt(self, names, why):
        self.events.append(("doubt", tuple(names)))

    def note(self, text):
        self.events.append(("note", text))

    def follow_component(self, component):
        self.events.append(("follow", component))

    def movers_unknown(self, phrase):
        self.events.append(("unknown", phrase))


def capture_of(*items):
    return {"target": PART, "items": list(items)}


class ReadTest(unittest.TestCase):
    def test_each_item_gets_its_role(self):
        steps = design.read(capture_of(item(1, "Sketch", bodies_after=[]), item(2),
                                       item(3, in_target_component=False)))
        self.assertEqual([s.role.kind for s in steps], [roles.NOT_A_STEP, roles.BUILDS, roles.OTHER_COMPONENT])

    def test_what_cannot_be_read(self):
        steps = design.read(capture_of(item(1, data={"read_error": "boom"}), item(2, health="error"),
                                       item(3, bodies_after=None), item(4)))
        self.assertEqual([[p.code for p in s.problems] for s in steps],
                         [[design.UNREAD], [design.FAILS], [design.BODIES_UNREAD], []])

    def test_a_borrowed_outline_is_brought_in_and_its_doubts_wait_for_the_walk(self):
        capture = capture_of(borrowing())
        ctx = Recorder(capture, Table())
        step = design.read(capture, ctx.table)[0]
        self.assertFalse(step.foreign)
        self.assertEqual(step.brought["data"]["profiles"][0]["borrowed"], "Lid")
        self.assertEqual(ctx.events, [])
        design.replay(step, ctx)
        # The capture does not say where sizes act, so the destination is told that more sizes may move the sketch.
        self.assertEqual([kind for kind, _ in ctx.events], ["doubt", "unknown", "note"])
        self.assertEqual(ctx.events[0][1], ("lid_w",))

    def test_a_step_of_another_component_is_not_brought_in(self):
        step = design.read(capture_of(borrowing(in_target_component=False)), Table())[0]
        self.assertIs(step.brought, step.item)
        self.assertEqual((step.foreign, step.events), (True, ()))

    def test_an_error_while_bringing_in_is_raised_where_the_walk_replays_the_step(self):
        broken = borrowing()
        broken["data"]["profiles"][0]["sketch_params"] = [{"reads": 5}]
        step = design.read(capture_of(broken), Table())[0]
        self.assertIsNotNone(step.error)
        with self.assertRaises(TypeError):
            design.replay(step, Recorder(capture_of(broken), Table()))

    def test_a_tool_step_resolved_without_a_role_is_brought_in(self):
        capture = capture_of(borrowing())
        step = design.resolve(borrowing(), Recorder(capture))
        self.assertIsNone(step.role)
        self.assertFalse(step.foreign)


class FactsTest(unittest.TestCase):
    def test_a_round_gives_its_sets_and_a_kind_without_a_reader_gives_none(self):
        sets = [{"kind": "constant", "radius": 2.0, "edges": []}]
        steps = design.read(capture_of(item(1, "FilletFeature", data={"sets": sets}), item(2)))
        self.assertIsInstance(steps[0].facts[0], finish.RoundSet)
        self.assertIsNone(steps[1].facts)

    def test_every_kind_of_facts_in_the_step_kind_table_has_a_reader(self):
        named = {t.facts for t in step_kinds.STEP_TYPES if t.facts}
        self.assertEqual(named - set(design.FACT_READERS), set())

    def test_the_sketches_an_item_names_at_any_depth_once_each_in_order(self):
        data = {"sketch": "Base", "profiles": [{"sketch": "Top"}, {"sketch": "Base"}], "path": {"sketch": ""}}
        self.assertEqual(design.sketches_of(item(data=data)), ["Base", "Top"])

    def test_a_pattern_names_the_items_it_repeats_and_another_kind_none(self):
        self.assertEqual(repeat.repeated_items(item(3, "MirrorFeature", data={"sources": [1, 2]})), [1, 2])
        self.assertEqual(repeat.repeated_items(item(3, "CombineFeature", data={"sources": [1, 2]})), [])


if __name__ == "__main__":
    unittest.main()
