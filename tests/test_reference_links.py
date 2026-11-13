"""Parameters that act on the component of a measured reference: found, offered, ticked and tried."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture

from lib.export_plan import size_offers
from lib.export_plan.body_scope import body_links, body_outside
from lib.params import geometry_links
from lib.translator.sizes import probed_sizes

LINK = {"param": "gap_mm", "sketch": "", "component": "Cover", "via": "reference", "step": "Mirror1",
        "ref": "4.plane"}


def mirror_capture(edit=None):
    capture = load_capture("component_foreign_mirror")
    if edit:
        edit(capture, capture["items"][4]["data"]["plane"]["ref"])
    return capture


class ItemRefsTest(unittest.TestCase):
    def test_a_reference_is_found_under_the_slot_it_was_read_in(self):
        found = geometry_links.item_refs(mirror_capture()["items"][4])
        self.assertEqual([(r["key"], r["item"], r["slot"], r["name"]) for r in found],
                         [("4.plane", 4, "plane", "Mirror1")])

    def test_the_points_of_a_hole_are_told_apart_by_their_place_in_the_list(self):
        item = {"index": 7, "name": "Hole1", "data": {"position_refs": [{"slot": "positions.0", "token": "a"},
                                                                       {"slot": "positions.0", "token": "b"}]}}
        self.assertEqual([r["key"] for r in geometry_links.item_refs(item)], ["7.positions.0", "7.positions.1"])

    def test_a_slot_used_twice_keeps_the_first_and_unreadable_steps_have_none(self):
        twice = {"index": 2, "data": {"a": {"ref": {"slot": "axis", "token": "1"}}, "b": {"ref": {"slot": "axis", "token": "2"}}}}
        self.assertEqual([r["ref"]["token"] for r in geometry_links.item_refs(twice)], ["1"])
        for edit in ({"suppressed": True}, {"in_target_component": False}):
            self.assertEqual(geometry_links.item_refs(dict(twice, **edit)), [])
        self.assertEqual(geometry_links.item_refs(dict(twice, data={"read_error": "x"})), [])


class ReferenceLinksTest(unittest.TestCase):
    def test_a_size_that_acts_on_the_component_of_the_plane_gets_a_link(self):
        self.assertEqual(geometry_links.reference_links(mirror_capture()), [LINK])

    def test_an_origin_plane_of_the_component_gets_a_link(self):
        capture = mirror_capture(lambda c, ref: ref.update(origin=True))
        self.assertEqual(geometry_links.reference_links(capture), [LINK])

    def test_components_no_size_acts_on_give_no_link(self):
        elsewhere = mirror_capture(lambda c, ref: ref.update(component={"token": "cmp_lid", "name": "Lid"}))
        self.assertEqual(geometry_links.reference_links(elsewhere), [])

    def test_without_data_on_where_sizes_act_there_are_no_links(self):
        def edit(capture, ref):
            for p in capture["parameters"]["user"]:
                del p["dependents"]
        self.assertEqual(geometry_links.reference_links(mirror_capture(edit)), [])

    def test_a_component_owning_several_references_links_a_size_once(self):
        def edit(capture, ref):
            second = copy.deepcopy(capture["items"][4])
            second.update(index=5, name="Mirror2")
            capture["items"].append(second)
        links = geometry_links.reference_links(mirror_capture(edit))
        self.assertEqual([(l["param"], l["step"]) for l in links], [("gap_mm", "Mirror1")])

    def test_only_the_given_steps_are_looked_at(self):
        capture = mirror_capture()
        self.assertEqual(geometry_links.reference_links(capture, capture["items"][:3]), [])

    def test_the_body_links_hold_them_and_the_size_is_ticked_to_start_with(self):
        capture = mirror_capture()
        self.assertEqual(body_links(capture), [LINK])
        capture["parameters"]["model"] = []  # no step reads a parameter: only the link makes one worth a try
        table = size_offers.table_for_body(capture["parameters"]["user"], "mm", [], capture)
        self.assertEqual(table.ticked, ["gap_mm"])
        self.assertEqual(table.links_of("gap_mm"), [LINK])
        self.assertIn("gap_mm", probed_sizes(table))

    def test_the_offer_says_which_step_uses_which_component(self):
        capture = mirror_capture()
        table = size_offers.table_for_body(capture["parameters"]["user"], "mm", [], capture)
        offer = next(o for o in size_offers.offers(table, capture["parameters"]["user"]) if o["param"] == "gap_mm")
        self.assertIn("Mirror1", offer["link"])
        self.assertIn("Cover", offer["link"])


class OutsideTest(unittest.TestCase):
    def test_sizes_that_act_on_other_components_are_tried_when_a_step_uses_a_reference(self):
        self.assertEqual(geometry_links.outside(mirror_capture()), ["gap_mm"])
        self.assertEqual(body_outside(mirror_capture()), ["gap_mm"])

    def test_the_one_on_the_referenced_component_comes_first(self):
        def edit(capture, ref):
            next(p for p in capture["parameters"]["user"] if p["name"] == "depth_mm")["dependents"].append(
                {"name": "d8", "kind": "constructionPlane", "component": "cmp_lid", "feature": "LidPlane"})
        self.assertEqual(geometry_links.outside(mirror_capture(edit)), ["gap_mm", "depth_mm"])

    def test_nothing_is_tried_without_a_sketch_link_or_a_reference(self):
        capture = mirror_capture()
        capture["items"][4]["data"]["plane"].pop("ref")
        self.assertEqual(geometry_links.outside(capture), [])


if __name__ == "__main__":
    unittest.main()
