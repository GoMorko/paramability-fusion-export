"""Parameters a body reads through formulas at any depth: the dependency graph, the default ticks and the dialog."""
import unittest

from tests import context  # noqa: F401
from lib.dialog_model import dialog_rows as rows
from lib.export_plan.size_offers import initial_table, offers, probe_sizes
from lib.params import defaults, size_table
from lib.params.dependencies import Graph


def plain(name, mm=None, count=None, fav=False):
    """A plain user parameter: a length in mm (Fusion keeps cm) or a count without a unit."""
    if count is not None:
        return dict(name=name, expression=str(count), value=float(count), unit="", kind="count", is_favorite=fav)
    return dict(name=name, expression="%s mm" % mm, value=mm / 10.0, unit="mm", kind="length", is_favorite=fav)


def formula(name, expression, mm, fav=False, **extra):
    return dict(name=name, expression=expression, value=mm / 10.0, unit="mm", kind="derived", is_favorite=fav,
                **extra)


def model(name, expression, mm, kind="sketchDimension", component="lid"):
    return dict(name=name, expression=expression, value=mm / 10.0, unit="mm", role="",
                created_by={"kind": kind, "sketch": "Outline", "component": component})


# A box whose outer size is a formula over a count of cells, a cell pitch and a wall, two formulas deep.
BOX = [
    plain("cells", count=3),
    plain("pitch", 6.0),
    plain("wall", 1.5),
    formula("inner", "cells * pitch", 18.0),
    formula("outer", "inner + 2 * wall", 21.0),
    plain("unused", 4.0),
]


class GraphTest(unittest.TestCase):
    def test_a_body_that_reads_only_the_outer_formula_reaches_every_base_through_it(self):
        usage = Graph(BOX, [model("d1", "outer / 2", 10.5)]).usage(["d1"])
        self.assertEqual(usage.used, {"cells", "pitch", "wall", "inner", "outer"})
        self.assertEqual(usage.through, {"cells": ["outer"], "pitch": ["outer"], "wall": ["outer"],
                                         "inner": ["outer"]})
        self.assertEqual(usage.direct, {"outer"})

    def test_a_base_the_body_also_reads_itself_is_direct(self):
        usage = Graph(BOX, [model("d1", "outer", 21.0), model("d2", "wall", 1.5)]).usage(["d1", "d2"])
        self.assertIn("wall", usage.direct)
        self.assertNotIn("wall", usage.through)

    def test_a_formula_the_parser_refuses_still_gives_the_names_it_holds(self):
        params = BOX[:3] + [formula("odd", "cells * pitch < 40 mm < wall", 1.0)]
        self.assertEqual(Graph(params).user_reads("odd"), ["cells", "pitch", "wall"])

    def test_a_cycle_ends(self):
        params = [plain("base", 2.0), formula("a", "b + base", 1.0), formula("b", "a * 2", 1.0)]
        body = [model("d1", "a", 1.0)]
        self.assertEqual(Graph(params, body).usage(["d1"]).used, {"a", "b", "base"})
        self.assertEqual(size_table.build(params, ["base"], body).depends("d1"), {"base"})

    def test_a_model_parameter_of_another_component_is_followed_through_the_dependents_of_its_base(self):
        # d1 of the body reads d9, a model parameter of another component the capture does not hold. Fusion lists
        # d1 among the dependents of the base, walked through d9 and `outer`.
        params = [dict(p) for p in BOX]
        dependents = [{"name": "d9", "kind": "sketchDimension", "component": "box"},
                      {"name": "d1", "kind": "sketchDimension", "component": "lid"}]
        for p in params:
            if p["name"] in ("cells", "pitch", "wall", "inner", "outer"):
                p["dependents"] = dependents
        body = [model("d1", "d9 + 1 mm", 22.0)]
        self.assertEqual(defaults.names_read_by(params, body), {"cells", "pitch", "wall", "inner", "outer"})
        table = size_table.build(params, ["cells", "pitch", "wall"], body)
        self.assertEqual(table.depends("d1"), {"cells", "pitch", "wall"})


class DefaultTicksTest(unittest.TestCase):
    def test_bases_of_a_favourite_formula_are_ticked_with_the_other_favourites(self):
        params = [dict(p) for p in BOX] + [plain("lip", 2.0, fav=True)]
        params[4]["is_favorite"] = True  # outer
        body = [model("d1", "outer", 21.0), model("d2", "lip", 2.0)]
        self.assertEqual(defaults.default_ticked(params, body), ["cells", "pitch", "wall", "lip"])

    def test_a_formula_that_reaches_the_body_through_another_component_brings_its_bases(self):
        # Only the formula is linked: the sketch of the body is drawn around a component that `outer` changes.
        table = initial_table(BOX, links=[{"param": "outer", "sketch": "Outline", "component": "Box",
                                           "via": "component"}])
        self.assertEqual(table.ticked, ["cells", "pitch", "wall"])
        self.assertEqual([s["param"] for s in probe_sizes(table, BOX)], ["cells", "pitch", "wall"])
        self.assertEqual(table.sizes["outer"]["expr"], "inner + 2 * wall")


class OffersTest(unittest.TestCase):
    def test_a_base_says_which_formula_the_part_uses_it_through(self):
        table = initial_table(BOX, [model("d1", "outer / 2", 10.5)])
        lines = {o["param"]: o for o in offers(table, BOX)}
        self.assertTrue(lines["cells"]["ticked"])
        self.assertIn("outer", lines["cells"]["through"])
        self.assertIn(lines["cells"]["through"], rows.details_html(lines["cells"], True))
        self.assertIn(lines["cells"]["through"], rows.name_tooltip(lines["cells"]))
        self.assertEqual(lines["outer"]["through"], "")
        self.assertEqual(lines["unused"]["through"], "")
        self.assertFalse(lines["unused"]["ticked"])


if __name__ == "__main__":
    unittest.main()
