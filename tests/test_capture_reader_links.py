"""The reader's geometry links: the other components a sketch is tied to, and where each user parameter acts."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, Obj

from lib.fusion_reader.parameters import dependent_components
from lib.fusion_reader.read_geometry import ReadContext
from lib.fusion_reader.read_links import sketch_links

BOX = Obj(entityToken="cmp_box", name="Box")
PIPE = Obj(entityToken="cmp_pipe", name="Pipe")


def _raise():
    raise RuntimeError("retired")


class Broken:
    """A Fusion object whose every member raises."""

    def __getattr__(self, name):
        _raise()


def pipe_edge():
    """An edge of the pipe's body, seen through the pipe's occurrence."""
    return Obj("fusion::BRepEdge", entityToken="edge", assemblyContext=Obj(component=PIPE))


def arc(token, reference=None):
    return Obj("fusion::SketchArc", entityToken=token, isReference=reference is not None, referencedEntity=reference)


def sketch(curves, constraints=(), plane=None):
    return Obj("fusion::Sketch", entityToken="s2", name="PipeHole", sketchCurves=Coll(curves), sketchPoints=Coll([]),
               geometricConstraints=Coll(constraints), referencePlane=plane, parentComponent=BOX)


class Design:
    def __init__(self, found):
        self.rootComponent = Obj(entityToken="root")
        self._found = found

    def findEntityByToken(self, token):
        return [self._found] if self._found is not None else []


ITEMS = [{"index": 3, "in_target_component": True,
          "data": {"profiles": [{"sketch": "PipeHole", "sketch_token": "s2"}]}}]


def read(found):
    design = Design(found)
    ctx = ReadContext(design, Obj("fusion::BRepBody", entityToken="t1", name="Box body", parentComponent=BOX))
    return sketch_links(design, ctx, ITEMS)


class SketchLinksTest(unittest.TestCase):
    def test_a_projected_arc_and_an_arc_constrained_to_it_tie_the_sketch_to_the_pipe(self):
        projected = arc("a0", pipe_edge())
        drawn = arc("a1")
        concentric = Obj("fusion::ConcentricConstraint", entityOne=drawn, entityTwo=projected)
        [record] = read(sketch([projected, drawn], [concentric]))
        self.assertEqual((record["sketch"], record["token"], record["unknown"]), ("PipeHole", "s2", 0))
        self.assertEqual(record["links"], [{"token": "cmp_pipe", "name": "Pipe", "references": 1, "constrained": 1,
                                            "plane": False}])

    def test_a_reference_to_the_part_itself_or_without_a_source_is_no_link(self):
        own = arc("a0", Obj("fusion::BRepEdge", entityToken="e", body=Obj(parentComponent=BOX)))
        silent = Obj("fusion::SketchArc", entityToken="a1", isReference=True, referencedEntity=None)
        [record] = read(sketch([own, silent]))
        self.assertEqual((record["links"], record["unknown"]), ([], 1))

    def test_a_sketch_drawn_on_a_face_of_the_pipe_is_tied_to_it(self):
        face = Obj("fusion::BRepFace", entityToken="f", assemblyContext=Obj(component=PIPE))
        [record] = read(sketch([], plane=face))
        self.assertEqual([(link["name"], link["plane"]) for link in record["links"]], [("Pipe", True)])

    def test_members_that_raise_leave_their_part_out(self):
        self.assertEqual(read(None)[0]["error"], "The sketch could not be found.")
        self.assertEqual(read(Broken())[0]["links"], [])
        broken = Obj("fusion::Sketch", sketchCurves=Coll([Broken(), arc("a0", Broken())]), sketchPoints=Broken(),
                     geometricConstraints=Broken(), referencePlane=Broken())
        self.assertEqual(read(broken)[0]["links"], [])


def parameter(name, component=None, dependents=()):
    kw = {"component": component} if component is not None else {}
    return Obj("fusion::ModelParameter" if component is not None else "fusion::UserParameter", name=name,
               dependentParameters=Coll(dependents), **kw)


class DependentComponentsTest(unittest.TestCase):
    def test_components_of_dependents_are_listed_through_parameters_that_read_it(self):
        lid = Obj(entityToken="cmp_lid", name="Lid")
        helper = parameter("pipe_r", dependents=[parameter("d7", lid)])
        top = parameter("pipe_d", dependents=[parameter("d1", PIPE), helper, parameter("d2", PIPE)])
        self.assertEqual(sorted(c["name"] for c in dependent_components(top)), ["Lid", "Pipe"])

    def test_an_unreadable_dependent_list_gives_none(self):
        self.assertEqual(dependent_components(Broken()), [])
        self.assertEqual(dependent_components(parameter("pipe_d", dependents=[Broken()])), [])


if __name__ == "__main__":
    unittest.main()
