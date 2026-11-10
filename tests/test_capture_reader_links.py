"""The reader's geometry links: the other components a sketch is tied to, and where each user parameter acts."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, Obj

from lib.fusion_reader.parameters import dependents
from lib.fusion_reader.read_links import sketch_inputs
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
    context = Obj(component=PIPE)
    body = Obj("fusion::BRepBody", entityToken="pb1 seen", name="Pipe body", assemblyContext=context,
               nativeObject=Obj("fusion::BRepBody", entityToken="pb1", name="Pipe body"))
    return Obj("fusion::BRepEdge", entityToken="edge", assemblyContext=context, body=body)


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
                                            "plane": False, "bodies": [{"token": "pb1", "name": "Pipe body"}],
                                            "sketches": []}])

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


ROOT = Obj(entityToken="root", name="Design")
PROFILE_SKETCH = Obj("fusion::Sketch", entityToken="sk_pipe", name="PipeProfile", parentComponent=ROOT)


def parameter(name, made_by=None, dependents=()):
    """A model parameter (with its maker) or, without one, a user parameter. Fusion names the root as the component
    of every dependent, as it did in a real design."""
    kind = "fusion::ModelParameter" if made_by is not None else "fusion::UserParameter"
    return Obj(kind, name=name, createdBy=made_by, component=ROOT, dependentParameters=Coll(dependents))


class DependentsTest(unittest.TestCase):
    def test_each_dependent_names_its_sketch_or_feature_and_their_component_through_parameters_that_read_it(self):
        dimension = Obj("fusion::SketchLinearDimension", entityToken="dim", parentSketch=PROFILE_SKETCH,
                        parameter=None)
        extrude = Obj("fusion::ExtrudeFeature", entityToken="ext", name="PipeExtrude", parentComponent=PIPE)
        helper = parameter("pipe_r", dependents=[parameter("d2", extrude)])
        found = {d["name"]: d for d in dependents(parameter("pipe_d", dependents=[parameter("d1", dimension), helper]))}
        self.assertEqual(found["d1"], {"name": "d1", "kind": "sketchDimension", "component": "root",
                                       "sketch": "PipeProfile", "sketch_token": "sk_pipe"})
        self.assertEqual(found["d2"], {"name": "d2", "kind": "feature", "component": "cmp_pipe",
                                       "feature": "PipeExtrude"})
        self.assertEqual(set(found), {"d1", "d2"})

    def test_an_unreadable_dependent_list_or_maker_adds_nothing_it_cannot_read(self):
        self.assertEqual(dependents(Broken()), [])
        self.assertEqual(dependents(parameter("pipe_d", dependents=[Broken()])), [])
        self.assertEqual(dependents(parameter("pipe_d", dependents=[parameter("d1", Broken())])),
                         [{"name": "d1", "kind": "other", "component": ""}])


class SketchInputsTest(unittest.TestCase):
    def test_outlines_and_path_of_a_step_name_their_sketches_once(self):
        path_sketch = Obj("fusion::Sketch", entityToken="sk_path", name="Rail")
        sweep = Obj("fusion::SweepFeature",
                    profile=Coll([Obj(parentSketch=PROFILE_SKETCH), Obj(parentSketch=PROFILE_SKETCH)]),
                    path=Coll([Obj(entity=Obj(parentSketch=path_sketch))]))
        self.assertEqual(sketch_inputs(sweep), [{"token": "sk_pipe", "name": "PipeProfile"},
                                                {"token": "sk_path", "name": "Rail"}])

    def test_a_step_whose_inputs_cannot_be_read_names_none(self):
        self.assertEqual(sketch_inputs(Broken()), [])
        self.assertEqual(sketch_inputs(Obj("fusion::ExtrudeFeature", profile=Obj("fusion::BRepFace"))), [])


if __name__ == "__main__":
    unittest.main()
