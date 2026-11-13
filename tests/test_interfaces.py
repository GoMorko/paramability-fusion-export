"""The parameter store, the export port and the probe are declared once (`design_edit.store.ParameterStore`,
`pipeline.ExportPort`, `pipeline.PartsPort`, `probe_flow.Probe`). The Fusion classes, the shared fakes and both probes
must have every declared member, and the pure code may ask a store, port or probe only for a declared one."""
import ast
import os
import typing
import unittest

from tests import context
from tests.fakes import FakeStore
from tests.test_parts_pipeline import FakePartsPort
from tests.test_pipeline import FakePort

from lib.design_edit.store import TIMELINE_CONTROLS, ParameterStore
from lib.export_plan.pipeline import ExportPort, PartsPort
from lib.export_plan.probe_flow import Probe

LIB = os.path.join(context.ADDIN_DIR, "lib")
FUSION_STORE = os.path.join(LIB, "fusion_reader", "rows.py")
FUSION_PORTS = os.path.join(context.ADDIN_DIR, "commands", "ExportForParamability", "export_flow.py")
# Folders of the pure code that is handed a store or a port.
PURE_FOLDERS = ("design_edit", "export_plan")
PROBE_FLOW = os.path.join(LIB, "export_plan", "probe_flow")
PIPELINE = os.path.join(LIB, "export_plan", "pipeline")

STORE_NAMES = {"store", "self.store", "port.store", "self.port.store"}
PORT_NAMES = {"port", "self.port"}

STORE_MEMBERS = set(typing.get_protocol_members(ParameterStore)) | set(TIMELINE_CONTROLS)
PORT_MEMBERS = set(typing.get_protocol_members(ExportPort))
PARTS_PORT_MEMBERS = set(typing.get_protocol_members(PartsPort))
PROBE_MEMBERS = set(typing.get_protocol_members(Probe))


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return head and head + "." + node.attr
    return None


def _class_members(path, class_name):
    """Names a class defines without importing it (the Fusion classes sit beside `adsk`): methods, class attributes
    and attributes set on `self` in its methods."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    found = set()
    for node in ast.walk(cls):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in ast.walk(ast.Tuple(elts=targets)):
                if isinstance(target, ast.Name):
                    found.add(target.id)
                elif isinstance(target, ast.Attribute) and _dotted(target.value) == "self":
                    found.add(target.attr)
    return found


def _asked_of_store_and_port():
    """{(kind, member): [file:line]} of each member the pure code asks of a store or a port, by direct access and by
    `timeline_control(store, "member")`."""
    found = {}
    for folder in PURE_FOLDERS:
        for dirpath, dirnames, names in os.walk(os.path.join(LIB, folder)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in names:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    where = "%s:%d" % (os.path.relpath(path, LIB), node.lineno) if hasattr(node, "lineno") else ""
                    if isinstance(node, ast.Attribute):
                        owner = _dotted(node.value)
                        if owner in STORE_NAMES:
                            found.setdefault(("store", node.attr), []).append(where)
                        elif owner in PORT_NAMES:
                            found.setdefault(("port", node.attr), []).append(where)
                    elif (isinstance(node, ast.Call) and _dotted(node.func) == "timeline_control" and len(node.args) == 2
                          and isinstance(node.args[1], ast.Constant)):
                        found.setdefault(("store", node.args[1].value), []).append(where)
    return found


def _asked_of(path, names):
    """Members asked of the objects called `names` in a file."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and _dotted(node.value) in names}


def _asked_of_probe_by_the_runner():
    return _asked_of(os.path.join(PIPELINE, "probe_run.py"), {"self.probe"})


class DeclaredInterfaceTest(unittest.TestCase):
    def test_the_fusion_store_has_every_declared_member(self):
        missing = STORE_MEMBERS - _class_members(FUSION_STORE, "DesignParameterStore")
        self.assertEqual(missing, set())

    def test_the_fusion_ports_have_every_declared_member(self):
        self.assertEqual(PORT_MEMBERS - _class_members(FUSION_PORTS, "FusionPort"), set())
        self.assertEqual(PARTS_PORT_MEMBERS - _class_members(FUSION_PORTS, "FusionPartsPort"), set())

    def test_the_shared_fakes_have_every_declared_member_except_the_timeline_controls(self):
        store = FakeStore({})
        self.assertEqual({m for m in set(typing.get_protocol_members(ParameterStore)) if not hasattr(store, m)}, set())
        self.assertEqual({m for m in PORT_MEMBERS if not hasattr(FakePort(), m)}, set())
        self.assertEqual({m for m in PARTS_PORT_MEMBERS if not hasattr(FakePartsPort([]), m)}, set())

    def test_the_pure_code_asks_a_store_or_port_only_for_declared_members(self):
        asked = _asked_of_store_and_port()
        self.assertTrue(asked[("store", "recompute")] and asked[("port", "undo_steps")])
        undeclared = {key: places for key, places in asked.items()
                      if key[1] not in {"store": STORE_MEMBERS, "port": PORT_MEMBERS | PARTS_PORT_MEMBERS}[key[0]]}
        self.assertEqual(undeclared, {})

    def test_every_declared_member_is_asked_for_somewhere(self):
        asked = {member for _, member in _asked_of_store_and_port()}
        self.assertEqual((STORE_MEMBERS | PORT_MEMBERS | PARTS_PORT_MEMBERS) - asked - {"export_step"}, set())

    def test_both_probes_have_every_declared_member(self):
        self.assertEqual(PROBE_MEMBERS - _class_members(os.path.join(PROBE_FLOW, "size_probe.py"), "SizeProbe"), set())
        self.assertEqual(PROBE_MEMBERS - _class_members(os.path.join(PROBE_FLOW, "probe_group.py"), "ProbeGroup"), set())

    def test_the_try_runner_asks_the_probe_only_for_declared_members(self):
        asked = _asked_of_probe_by_the_runner()
        self.assertIn("far_pair_rows", asked)
        self.assertEqual(asked - PROBE_MEMBERS, set())

    def test_every_declared_probe_member_is_asked_for_by_the_runner_or_both_pipelines(self):
        single = _asked_of(os.path.join(PIPELINE, "run.py"), {"probe", "self.probe"})
        parts = _asked_of(os.path.join(PIPELINE, "parts.py"), {"group", "self.group"})
        self.assertEqual(PROBE_MEMBERS - _asked_of_probe_by_the_runner() - (single & parts), set())


if __name__ == "__main__":
    unittest.main()
