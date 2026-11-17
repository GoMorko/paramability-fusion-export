"""Every name the add-in uses is bound somewhere: an import, a definition, an assignment, a parameter or a builtin.

A missing import (say `math` in a module that calls `math.tan`) only fails when the line runs, which may be one rare
branch in Fusion. This check reads every module under ParamabilityExport with `symtable`, which resolves each name to
its scope the same way the compiler does, and fails on a name no scope binds. A star import is refused, as it hides
which names a module binds.
"""
import ast
import builtins
import os
import symtable
import unittest

from tests import context

# Names that Python binds in every module.
MODULE_NAMES = {"__name__", "__file__", "__doc__", "__spec__", "__loader__", "__package__", "__path__", "__builtins__",
                "__cached__", "__annotations__", "__dict__"}


def _tables(table):
    yield table
    for child in table.get_children():
        yield from _tables(child)


def unbound_names(source, path="<module>"):
    """`(line, name)` of each name used in `source` that no scope binds, and of each star import."""
    tree = ast.parse(source, path)
    stars = [(node.lineno, "*") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
             and any(alias.name == "*" for alias in node.names)]
    top = symtable.symtable(source, path, "exec")
    bound = set(dir(builtins)) | MODULE_NAMES
    bound |= {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    for table in _tables(top):
        # `global x` in a function, then `x = ...` there, binds x in the module.
        bound |= {s.get_name() for s in table.get_symbols() if s.is_declared_global() and s.is_assigned()}
    used = set()
    for table in _tables(top):
        for symbol in table.get_symbols():
            if not symbol.is_referenced():
                continue
            # Locals, parameters and names of enclosing functions (`is_free`) are bound by the scope that owns them;
            # a global (explicit, implicit, or any name at module level) must be bound in the module.
            if table is top or symbol.is_global():
                used.add(symbol.get_name())
    missing = used - bound
    lines = sorted((node.lineno, node.id) for node in ast.walk(tree)
                   if isinstance(node, ast.Name) and node.id in missing)
    first = {}
    for line, name in lines:
        first.setdefault(name, line)
    return sorted([(line, name) for name, line in first.items()] + stars)


def _modules():
    for folder, dirnames, names in os.walk(context.ADDIN_DIR):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(names):
            if name.endswith(".py"):
                yield os.path.join(folder, name)


class UndefinedNamesTest(unittest.TestCase):
    def test_every_name_the_add_in_uses_is_bound(self):
        found = []
        for path in _modules():
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            rel = os.path.relpath(path, context.ADDIN_DIR)
            found += ["%s:%d %s" % (rel, line, name) for line, name in unbound_names(source, path)]
        self.assertEqual(found, [])

    def test_the_check_finds_a_missing_import_a_star_import_and_a_name_of_no_scope(self):
        source = ("from os.path import *\n"
                  "def lean(a):\n"
                  "    return math.tan(a)\n"
                  "class Box:\n"
                  "    size = width\n")
        self.assertEqual(unbound_names(source), [(1, "*"), (3, "math"), (5, "width")])

    def test_the_check_takes_every_kind_of_binding(self):
        source = ("import math\n"
                  "from os import path as p\n"
                  "def outer(a, *rest, k=1, **more):\n"
                  "    global counter\n"
                  "    counter = 1\n"
                  "    b = [x * a for x in rest if (y := x)]\n"
                  "    def inner():\n"
                  "        nonlocal b\n"
                  "        b = y\n"
                  "        return k, more, b\n"
                  "    try:\n"
                  "        pass\n"
                  "    except ValueError as err:\n"
                  "        del err\n"
                  "    with open(__file__) as f:\n"
                  "        return inner, f, math.pi, p, counter\n"
                  "class Box:\n"
                  "    size = 1\n"
                  "    wide = size * 2\n"
                  "    def area(self):\n"
                  "        return super().area()\n")
        self.assertEqual(unbound_names(source), [])


if __name__ == "__main__":
    unittest.main()
