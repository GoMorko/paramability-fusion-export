"""Step roles in the shared layer (`design_model/roles.py`): what an item is for the body a walk builds, the bodies
before and after it, and which measures of that body apply to it."""
import unittest

from tests import context  # noqa: F401

from lib.design_model import roles

PART = {"token": "t1", "name": "Body1"}
PARENT = {"token": "t0", "name": "Body0"}
OTHER = {"token": "t2", "name": "Body2"}
# The part is born at index 5 by a split of PARENT.
CHAIN = [(5, PARENT)]
WHOLE = {"min": [0, 0, 0], "max": [40, 20, 10]}


def item(index=3, kind="ExtrudeFeature", after=(PART,), **more):
    found = {"index": index, "name": "Step%d" % index, "type": kind, "suppressed": False,
             "in_target_component": True, "bodies_after": list(after), "data": {}}
    found.update(more)
    return found


class KindTest(unittest.TestCase):
    def test_each_kind_of_item(self):
        cases = {
            roles.SUPPRESSED: item(suppressed=True),
            roles.NOT_A_STEP: item(kind="Sketch", after=()),
            roles.ASSEMBLY: item(kind="Occurrence", after=()),
            roles.TOOL_ELSEWHERE: item(in_target_component=False, helper_of="t9"),
            roles.OTHER_COMPONENT: item(in_target_component=False),
            roles.BUILDS: item(),
            roles.HELPER: item(after=(OTHER,)),
        }
        for kind, found in cases.items():
            self.assertEqual(roles.role_of(found, PART).kind, kind, kind)

    def test_before_a_split_of_the_lineage_the_walk_builds_the_body_it_was_split_from(self):
        early = roles.role_of(item(after=(PARENT,)), PART, CHAIN)
        self.assertEqual((early.kind, early.before, early.after), (roles.BUILDS, PARENT, PARENT))
        split = roles.role_of(item(index=5, kind="SplitBodyFeature", after=(PART, OTHER)), PART, CHAIN)
        self.assertEqual((split.before, split.after), (PARENT, PART))
        self.assertEqual(roles.role_of(item(after=(PARENT,)), PART).kind, roles.HELPER)

    def test_a_join_lists_the_body_among_its_participants_and_a_new_body_does_not(self):
        joins = item(after=(), data={"operation": "join", "participants": [PART]})
        new = item(after=(), data={"operation": "newBody", "participants": [PART]})
        self.assertEqual((roles.role_of(joins, PART).touches, roles.role_of(new, PART).touches), (True, False))

    def test_a_body_with_the_name_of_the_part_under_another_token_is_lost(self):
        self.assertTrue(roles.role_of(item(after=({"token": "t7", "name": "Body1"},)), PART).lost)


class NewBodiesTest(unittest.TestCase):
    def test_a_body_that_did_not_exist_before_is_new(self):
        found = roles.role_of(item(after=(PART, OTHER), bodies_before=[PART]), PART)
        self.assertEqual((found.new_bodies, found.makes_other), ((OTHER,), True))

    def test_without_bodies_before_the_bodies_the_data_names_existed(self):
        named = item(after=(PART, OTHER), data={"target": PART, "tools": [OTHER]})
        self.assertEqual(roles.role_of(named, PART).new_bodies, ())

    def test_copies_of_bodies_are_new_but_not_another_body(self):
        mirror = roles.role_of(item(kind="MirrorFeature", after=(PART, OTHER), bodies_before=[PART]), PART)
        self.assertEqual((mirror.copies, mirror.makes_other), (True, False))
        features = item(kind="MirrorFeature", after=(PART, OTHER), bodies_before=[PART],
                        data={"entity_type": "features"})
        self.assertTrue(roles.role_of(features, PART).makes_other)


class SeenOnTest(unittest.TestCase):
    STATE = {"t0": {"box_before": WHOLE, "volume_before": 8000.0, "volume_after": 8000.0}}

    def step(self, **more):
        return item(after=(PARENT,), body_states=self.STATE, target_changed=True,
                    target_before={"box": {"min": [9, 9, 9], "max": [9, 9, 9]}, "volume_mm3": 1.0},
                    data={"target_box_before": None, "volume_before": 1.0, "volume_after": 2.0}, **more)

    def test_another_body_reads_its_own_measures_and_none_of_the_exported_body(self):
        seen = roles.seen_on(self.step(), PARENT)
        self.assertEqual((seen["data"]["target_box_before"], seen["data"]["volume_before"]), (WHOLE, 8000.0))
        self.assertEqual((seen["target_before"], seen["target_after"], seen["target_changed"]), (None, None, False))

    def test_the_exported_body_keeps_the_measures_on_the_item(self):
        seen = roles.seen_on(self.step(), PARENT, exported=True)
        self.assertEqual((seen["data"]["volume_before"], seen["target_before"]["volume_mm3"]), (1.0, 1.0))

    def test_an_unmeasured_body_has_no_measures(self):
        seen = roles.seen_on(self.step(), OTHER)
        self.assertEqual((seen["data"]["target_box_before"], seen["target_changed"]), (None, None))

    def test_before_the_split_a_measured_step_reads_the_body_it_was_split_from(self):
        step = self.step()
        self.assertEqual(roles.seen_before_split(step, PART, CHAIN)["data"]["target_box_before"], WHOLE)
        unmeasured = dict(step, body_states={})
        for found in (dict(step, index=7), dict(step, type="SplitBodyFeature", index=5),
                      dict(step, in_target_component=False), unmeasured):
            self.assertIs(roles.seen_before_split(found, PART, CHAIN), found)
        self.assertIs(roles.seen_before_split(step, PART, []), step)


class SplitPiecesTest(unittest.TestCase):
    def split(self):
        pieces = [dict(PART, box=WHOLE), dict(OTHER, box=WHOLE)]
        return item(index=5, kind="SplitBodyFeature", after=(PART, OTHER),
                    data={"bodies": [PARENT], "pieces": pieces})

    def test_the_other_pieces_and_a_later_step_that_uses_one_with_the_part(self):
        split = self.split()
        self.assertEqual([b["token"] for b in roles.other_pieces(split, PARENT, PART)], ["t2"])
        alone = item(index=6, after=(OTHER,))
        both = item(index=7, after=(PART,), data={"operation": "join", "participants": [PART, OTHER]})
        timeline = [split, alone, both]
        self.assertIs(roles.used_later(timeline, split, OTHER, PART, CHAIN), both)
        self.assertIsNone(roles.used_later(timeline[:2], split, OTHER, PART, CHAIN))


if __name__ == "__main__":
    unittest.main()
