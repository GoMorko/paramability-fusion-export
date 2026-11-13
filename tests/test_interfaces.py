"""The parameter store and the export port are declared once (`design_edit.store.ParameterStore`,
`pipeline.ExportPort`, `pipeline.PartsPort`). The Fusion classes and the shared fakes must have every declared member,
and the pure code may ask a store or port only for a declared one."""
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

LIB = os.path.join(context.ADDIN_DIR, "lib")
FUSION_STORE = os.path.join(LIB, "fusion_reader", "rows.py")
FUSION_PORTS = os.path.join(context.ADDIN_DIR, "commands", "ExportForParamability", "export_flow.py")
# Folders of the pure code that is handed a store or a port.
PURE_FOLDERS = ("design_edit", "export_plan")

STORE_NAMES = {"store", "self.store", "port.store", "self.port.store"}
PORT_NAMES = {"port", "self.port"}

STORE_MEMBERS = set(typing.get_protocol_members(ParameterStore)) | set(TIMELINE_CONTROLS)
PORT_MEMBERS = set(typing.get_protocol_members(ExportPort))
PARTS_PORT_MEMBERS = set(typing.get_protocol_members(PartsPort))


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


if __name__ == "__main__":
    unittest.main()
