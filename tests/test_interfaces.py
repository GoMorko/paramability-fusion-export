"""The parameter store, the export port, the probe and the recorder are declared once
(`design_edit.store.ParameterStore`, `pipeline.ExportPort`, `pipeline.PartsPort`, `probe_flow.Probe`,
`design_model.recorder.Recorder`). The Fusion classes, the shared fakes, both probes and both translation contexts
must have every declared member with the declared parameters, and the code that is handed a store, port, probe or
recorder may ask it only for a declared member."""
import ast
import inspect
import os
import typing
import unittest

from tests import context
from tests.fakes import FakePartsPort, FakePort, FakeStore, RollingStore, TrimStore

from lib.design_edit.store import TIMELINE_CONTROLS, ParameterStore
from lib.design_model.recorder import Recorder
from lib.export_plan.pipeline import ExportPort, PartsPort
from lib.export_plan.probe_flow import Probe, ProbeGroup, SizeProbe

LIB = os.path.join(context.ADDIN_DIR, "lib")
COMMANDS = os.path.join(context.ADDIN_DIR, "commands")
FUSION_STORE = os.path.join(LIB, "fusion_reader", "rows.py")
FUSION_PORTS = os.path.join(COMMANDS, "ExportForParamability", "export_flow.py")
PROBE_FLOW = os.path.join(LIB, "export_plan", "probe_flow")
PIPELINE = os.path.join(LIB, "export_plan", "pipeline")
PROBE_RUNNER = os.path.join(PIPELINE, "probe_run.py")
WALK_BACKS = os.path.join(PIPELINE, "walk_backs.py")  # the walks back of the try runner
DESIGN_MODEL = os.path.join(LIB, "design_model")
CONTEXTS = (os.path.join(LIB, "translator", "context.py"), os.path.join(LIB, "orca_translate", "context.py"))

# A name, or an attribute of any object, with one of these names is a store or a port; so is a name or a `self.`
# attribute assigned from one (`x = self.port`, `self.owner = port`).
STORE_AND_PORT_NAMES = {"store": "store", "port": "port"}
PROBE_NAMES = {"probe": "probe"}

STORE_MEMBERS = set(typing.get_protocol_members(ParameterStore)) | set(TIMELINE_CONTROLS)
PORT_MEMBERS = set(typing.get_protocol_members(ExportPort))
PARTS_PORT_MEMBERS = set(typing.get_protocol_members(PartsPort))
PROBE_MEMBERS = set(typing.get_protocol_members(Probe))
RECORDER_MEMBERS = set(typing.get_protocol_members(Recorder))
DECLARED = {"store": STORE_MEMBERS, "port": PORT_MEMBERS | PARTS_PORT_MEMBERS, "probe": PROBE_MEMBERS}


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return head and head + "." + node.attr
    return None


def _parse(path):
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read())


def _class(path, class_name):
    return next(n for n in _parse(path).body if isinstance(n, ast.ClassDef) and n.name == class_name)


def _targets(node):
    """The plain targets an assignment statement binds, tuples opened."""
    if isinstance(node, ast.Assign):
        found = list(node.targets)
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        found = [node.target]
    else:
        return []
    out = []
    while found:
        target = found.pop()
        if isinstance(target, (ast.Tuple, ast.List)):
            found.extend(target.elts)
        else:
            out.append(target)
    return out


def _walk_skipping_classes(node):
    """`ast.walk` that does not go into classes defined inside `node` (their `self` is another object)."""
    todo = list(ast.iter_child_nodes(node))
    while todo:
        child = todo.pop()
        if isinstance(child, ast.ClassDef):
            continue
        yield child
        todo.extend(ast.iter_child_nodes(child))


def _class_members(path, class_name):
    """Names a class defines, read without importing it (the Fusion classes sit beside `adsk`): the methods and
    properties and the names assigned in the class body, plus the attributes its methods assign on `self`."""
    cls = _class(path, class_name)
    found = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.add(node.name)
            for inner in _walk_skipping_classes(node):
                found.update(t.attr for t in _targets(inner)
                             if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self")
        found.update(t.id for t in _targets(node) if isinstance(t, ast.Name))
    return found


def _ast_parameters(function):
    """The parameters of a parsed method after `self`, as (name, kind, has default)."""
    args = function.args
    positional = args.posonlyargs + args.args
    defaults = [False] * (len(positional) - len(args.defaults)) + [True] * len(args.defaults)
    out = [(a.arg, "positional", d) for a, d in zip(positional, defaults)]
    if args.vararg:
        out.append((args.vararg.arg, "*", False))
    out += [(a.arg, "keyword", d is not None) for a, d in zip(args.kwonlyargs, args.kw_defaults)]
    if args.kwarg:
        out.append((args.kwarg.arg, "**", False))
    return tuple(out[1:])


_KINDS = {inspect.Parameter.POSITIONAL_ONLY: "positional", inspect.Parameter.POSITIONAL_OR_KEYWORD: "positional",
          inspect.Parameter.VAR_POSITIONAL: "*", inspect.Parameter.KEYWORD_ONLY: "keyword",
          inspect.Parameter.VAR_KEYWORD: "**"}


def _parameters(function, drop_self=True):
    """The parameters of a function as (name, kind, has default), without `self` when `drop_self`."""
    out = tuple((p.name, _KINDS[p.kind], p.default is not inspect.Parameter.empty)
                for p in inspect.signature(function).parameters.values())
    return out[1:] if drop_self else out


def _declared_methods(protocol):
    """{name: parameters} of the methods a protocol declares."""
    return {name: _parameters(getattr(protocol, name)) for name in typing.get_protocol_members(protocol)
            if callable(getattr(protocol, name, None))}


def _ast_methods(path, class_name):
    """{name: parameters} of the methods of a parsed class; a class-level `b = a` names method `a` again."""
    cls = _class(path, class_name)
    methods = {n.name: _ast_parameters(n) for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for node in cls.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id in methods:
            methods.update((t.id, methods[node.value.id]) for t in node.targets if isinstance(t, ast.Name))
    return methods


def _differing(declared, methods, more_with_defaults=False):
    """{name: (declared parameters, found parameters)} of the declared methods whose parameters differ. With
    `more_with_defaults` a method may take more parameters after the declared ones when each has a default."""
    def fits(want, found):
        if found is None or found[:len(want)] != want:
            return False
        return found == want or (more_with_defaults and all(p[-1] for p in found[len(want):]))
    return {name: (want, methods.get(name)) for name, want in declared.items() if not fits(want, methods.get(name))}


def _instance_methods(obj, names):
    return {name: _parameters(getattr(obj, name), drop_self=False) for name in names if hasattr(obj, name)}


def _class_methods(cls, names):
    return {name: _parameters(getattr(cls, name)) for name in names if hasattr(cls, name)}


class _Asked(ast.NodeVisitor):
    """Collects {(kind, member): [file:line]} of each member asked of an object of a kind: an attribute read, a
    `getattr` or `hasattr` with a constant name, and `timeline_control(store, "member")`. `names` maps a name or an
    attribute name to its kind; names and `self.` attributes assigned from such an object get its kind too."""

    def __init__(self, names, where, found):
        self.names, self.where, self.found = names, where, found
        self.scopes = [{}]
        self.keywords = set()  # (member, keyword) of each call of a member with a keyword argument

    def kind(self, node):
        if isinstance(node, ast.Attribute) and node.attr in self.names:
            return self.names[node.attr]
        name = _dotted(node)
        if name in self.names:
            return self.names[name]
        return next((scope[name] for scope in reversed(self.scopes) if name in scope), None)

    def note(self, kind, member, node):
        self.found.setdefault((kind, member), []).append("%s:%d" % (self.where, node.lineno))

    def aliases(self, nodes):
        """{dotted name: kind} of the names and `self.` attributes the assignments among `nodes` bind to a known
        object."""
        scope = {}
        self.scopes.append(scope)
        for _ in range(3):  # a few passes settle `a = port` then `b = a.store`
            for node in nodes:
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    pairs = [(node.targets[0], node.value)]
                    if isinstance(node.targets[0], ast.Tuple) and isinstance(node.value, ast.Tuple):
                        pairs = list(zip(node.targets[0].elts, node.value.elts))
                elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                    pairs = [(node.target, node.value)]
                else:
                    continue
                for target, value in pairs:
                    name, kind = _dotted(target), self.kind(value)
                    if name and kind and (isinstance(target, ast.Name) or name.startswith("self.")):
                        scope[name] = kind
        self.scopes.pop()
        return scope

    def visit_ClassDef(self, node):
        self.scopes.append({k: v for k, v in self.aliases(list(ast.walk(node))).items() if k.startswith("self.")})
        self.generic_visit(node)
        self.scopes.pop()

    def visit_FunctionDef(self, node):
        if node.name == "timeline_control":
            return
        self.scopes.append(self.aliases(list(ast.walk(node))))
        self.generic_visit(node)
        self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Module(self, node):
        self.scopes.append(self.aliases([n for n in node.body]))
        self.generic_visit(node)
        self.scopes.pop()

    def visit_Attribute(self, node):
        kind = self.kind(node.value)
        if kind:
            self.note(kind, node.attr, node)
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and self.kind(node.func.value):
            self.keywords.update((node.func.attr, k.arg) for k in node.keywords if k.arg)
        func = _dotted(node.func)
        named = len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
        if func == "timeline_control" and named:
            self.note("store", node.args[1].value, node)
        elif func in ("getattr", "hasattr") and named:
            kind = self.kind(node.args[0])
            if kind:
                self.note(kind, node.args[1].value, node)
        self.generic_visit(node)


def _asked_in(path, names, found=None):
    found = {} if found is None else found
    _Asked(names, os.path.relpath(path, context.ADDIN_DIR), found).visit(_parse(path))
    return found


def _python_files(*folders):
    for folder in folders:
        for dirpath, dirnames, files in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            yield from (os.path.join(dirpath, f) for f in sorted(files) if f.endswith(".py"))


def _asked_of_store_and_port():
    """What all the add-in code asks of a store or a port, except the Fusion port module (the port itself)."""
    found = {}
    for path in _python_files(LIB, COMMANDS):
        if path != FUSION_PORTS:
            _asked_in(path, STORE_AND_PORT_NAMES, found)
    return found


def _undeclared(asked):
    return {key: places for key, places in asked.items() if key[1] not in DECLARED[key[0]]}


def _asked_of(path, names):
    """Members asked of the objects called `names` (and their aliases) in a file."""
    return {member for _, member in _asked_in(path, {name: "probe" for name in names})}


def _probe_keywords():
    """(member, keyword) of each probe call with a keyword argument in the try runner and both pipelines."""
    found = set()
    for path, name in ((PROBE_RUNNER, "probe"), (os.path.join(PIPELINE, "run.py"), "probe"),
                       (os.path.join(PIPELINE, "parts.py"), "group")):
        asked = _Asked({name: "probe"}, path, {})
        asked.visit(_parse(path))
        found |= asked.keywords
    return found


class DeclaredInterfaceTest(unittest.TestCase):
    def test_the_fusion_store_has_every_declared_member(self):
        missing = STORE_MEMBERS - _class_members(FUSION_STORE, "DesignParameterStore")
        self.assertEqual(missing, set())

    def test_the_fusion_ports_have_every_declared_member(self):
        self.assertEqual(PORT_MEMBERS - _class_members(FUSION_PORTS, "FusionPort"), set())
        self.assertEqual(PARTS_PORT_MEMBERS - _class_members(FUSION_PORTS, "FusionPartsPort"), set())

    def test_the_fusion_classes_take_the_declared_parameters(self):
        for protocol, path, name in ((ParameterStore, FUSION_STORE, "DesignParameterStore"),
                                     (ExportPort, FUSION_PORTS, "FusionPort"),
                                     (PartsPort, FUSION_PORTS, "FusionPartsPort")):
            self.assertEqual(_differing(_declared_methods(protocol), _ast_methods(path, name)), {}, name)

    def test_the_shared_fakes_have_every_declared_member_except_the_timeline_controls(self):
        store = FakeStore({})
        self.assertEqual({m for m in set(typing.get_protocol_members(ParameterStore)) if not hasattr(store, m)}, set())
        self.assertEqual({m for m in PORT_MEMBERS if not hasattr(FakePort(), m)}, set())
        self.assertEqual({m for m in PARTS_PORT_MEMBERS if not hasattr(FakePartsPort([]), m)}, set())

    def test_the_shared_fakes_take_the_declared_parameters(self):
        for protocol, fake in ((ParameterStore, FakeStore({})), (ParameterStore, RollingStore({})),
                               (ParameterStore, TrimStore({})), (ExportPort, FakePort()),
                               (PartsPort, FakePartsPort([]))):
            declared = _declared_methods(protocol)
            self.assertEqual(_differing(declared, _instance_methods(fake, declared)), {}, type(fake).__name__)

    def test_the_code_asks_a_store_or_port_only_for_declared_members(self):
        asked = _asked_of_store_and_port()
        self.assertTrue(asked[("store", "recompute")] and asked[("port", "undo_steps")])
        self.assertEqual(_undeclared(asked), {})

    def test_an_alias_or_getattr_of_a_port_is_checked_too(self):
        source = ("def run(self, job):\n"
                  "    door = self.port\n"
                  "    door.open_window()\n"
                  "    getattr(job.store, 'shake')()\n")
        tree = ast.parse(source)
        found = {}
        _Asked(STORE_AND_PORT_NAMES, "example.py", found).visit(tree)
        self.assertEqual(set(_undeclared(found)), {("port", "open_window"), ("store", "shake")})

    def test_every_declared_member_is_asked_for_somewhere(self):
        asked = {member for _, member in _asked_of_store_and_port()}
        self.assertEqual((STORE_MEMBERS | PORT_MEMBERS | PARTS_PORT_MEMBERS) - asked - {"export_step"}, set())

    def test_both_probes_have_every_declared_member(self):
        for module, name in (("size_probe.py", "SizeProbe"), ("probe_group.py", "ProbeGroup")):
            self.assertEqual(PROBE_MEMBERS - _class_members(os.path.join(PROBE_FLOW, module), name), set(), name)

    def test_both_probes_take_the_declared_parameters(self):
        # The runner passes a probe's arguments by place, so their names may differ (`ProbeGroup` names its reads in
        # the plural); `SizeProbe` takes the marked states to judge by as one more parameter, which the group passes.
        unnamed = {name: tuple(p[1:] for p in params) for name, params in _declared_methods(Probe).items()}
        for probe in (SizeProbe, ProbeGroup):
            found = {name: tuple(p[1:] for p in params) for name, params in _class_methods(probe, unnamed).items()}
            self.assertEqual(_differing(unnamed, found, more_with_defaults=True), {}, probe.__name__)

    def test_both_probes_take_every_keyword_the_callers_pass(self):
        keywords = _probe_keywords()
        self.assertIn(("read_now", "outline"), keywords)
        for probe in (SizeProbe, ProbeGroup):
            missing = {(member, keyword) for member, keyword in keywords
                       if keyword not in inspect.signature(getattr(probe, member)).parameters}
            self.assertEqual(missing, set(), probe.__name__)

    def test_the_try_runner_asks_the_probe_only_for_declared_members(self):
        asked = _asked_in(WALK_BACKS, PROBE_NAMES, _asked_in(PROBE_RUNNER, PROBE_NAMES))
        self.assertIn(("probe", "far_pair_rows"), asked)
        self.assertIn(("probe", "off_start"), _asked_in(WALK_BACKS, PROBE_NAMES))
        self.assertEqual(_undeclared(asked), {})

    def test_every_declared_probe_member_is_asked_for_by_the_runner_or_both_pipelines(self):
        runner = _asked_of(PROBE_RUNNER, {"probe"})
        single = _asked_of(os.path.join(PIPELINE, "run.py"), {"probe"})
        parts = _asked_of(os.path.join(PIPELINE, "parts.py"), {"group"})
        self.assertEqual(PROBE_MEMBERS - runner - (single & parts), set())


class RecorderTest(unittest.TestCase):
    def test_both_translation_contexts_have_every_declared_member(self):
        for path in CONTEXTS:
            self.assertEqual(RECORDER_MEMBERS - _class_members(path, "Context"), set(), path)

    def test_both_translation_contexts_take_the_declared_parameters(self):
        for path in CONTEXTS:
            self.assertEqual(_differing(_declared_methods(Recorder), _ast_methods(path, "Context"),
                                        more_with_defaults=True), {}, path)

    def test_the_design_model_asks_a_recorder_only_for_declared_members(self):
        found = {}
        for path in _python_files(DESIGN_MODEL):
            _asked_in(path, {"ctx": "recorder"}, found)
        self.assertIn(("recorder", "doubt"), found)
        self.assertEqual({member for _, member in found} - RECORDER_MEMBERS, set())


if __name__ == "__main__":
    unittest.main()
