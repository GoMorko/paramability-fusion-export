"""The step kind table (lib/capture_model/step_kinds.py) is the one list of step types and recipe kinds."""
import ast
import importlib
import os
import re
import unittest

from tests import context  # noqa: F401

from lib.capture_model import step_kinds
from lib.probe import plan
from lib.translator.translate import HANDLERS

LIB = os.path.join(context.ADDIN_DIR, "lib")
TABLE = os.path.join(LIB, "capture_model", "step_kinds.py")
READER_DIR = os.path.join(LIB, "fusion_reader")
HANDLER_MAP = os.path.join(LIB, "translator", "handlers.py")
# The Orca output keeps its own small maps of the types it copies: a `HANDLERS` dict in each of its handler modules.
ORCA_HANDLER_MAP = os.path.join(LIB, "orca_translate", "steps.py")
ORCA_DIR = os.path.dirname(ORCA_HANDLER_MAP)
FEATURE_NAME = re.compile(r"[A-Z][A-Za-z]*Feature")


def _sources():
    for folder, _, files in os.walk(context.ADDIN_DIR):
        for name in sorted(files):
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    yield path, ast.parse(f.read(), path)


def _registrations(tree, name="READERS"):
    """The keys of a module level `<name> = {...}` dict."""
    for node in tree.body:
        if (isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets)
                and isinstance(node.value, ast.Dict)):
            return [k.value for k in node.value.keys]
    return []


class StepKindTableTest(unittest.TestCase):
    def test_every_entry_has_words_and_a_modeling_type_a_handler_or_a_reason(self):
        for spec in step_kinds.STEP_TYPES:
            with self.subTest(spec.name):
                self.assertTrue(spec.words)
                if spec.name in HANDLERS:
                    self.assertTrue(callable(HANDLERS[spec.name]))
                    self.assertIsNone(spec.unsupported)
                elif spec.role == step_kinds.MODELING:
                    self.assertTrue(spec.unsupported or spec.splits_faces)

    def test_the_handler_map_registers_only_modeling_types_of_the_table(self):
        modeling = {t.name for t in step_kinds.STEP_TYPES if t.role == step_kinds.MODELING}
        self.assertLessEqual(set(HANDLERS), modeling)

    def test_the_types_that_repeat_their_sources_have_the_body_copy_handlers(self):
        repeating = {t.name for t in step_kinds.STEP_TYPES if t.repeats_sources}
        self.assertEqual(repeating, {name for name, handler in HANDLERS.items()
                                     if handler.__module__ == "lib.translator.repeat.body_copies"})

    def test_every_reader_registers_only_types_the_table_gives_it(self):
        named = {t.name: t.reader for t in step_kinds.STEP_TYPES if t.reader}
        found = {}
        for path, tree in _sources():
            if os.path.dirname(path) != READER_DIR:
                continue
            module = os.path.basename(path)[:-3]
            for key in _registrations(tree):
                found[key] = module
                self.assertEqual(named.get(key), module, "%s registers a reader for %s" % (module, key))
        self.assertEqual(found, named)
        for name, module in named.items():
            pair = importlib.import_module("lib.fusion_reader." + module).READERS[name]
            self.assertEqual(len(pair), 2)
            self.assertTrue(callable(pair[0]))

    def test_every_sketch_record_has_a_probe_scanner(self):
        for spec in step_kinds.STEP_TYPES:
            self.assertLessEqual(set(spec.sketches), set(plan.SCANNERS), spec.name)

    def test_no_other_module_keeps_a_list_of_step_types_or_kinds(self):
        types = {t.name for t in step_kinds.STEP_TYPES if t.role == step_kinds.MODELING}
        kinds = {k.name for k in step_kinds.RECIPE_KINDS}
        for path, tree in _sources():
            if path == TABLE:
                continue
            allowed = set(_registrations(tree)) if os.path.dirname(path) == READER_DIR else set()
            if path == HANDLER_MAP or os.path.dirname(path) == ORCA_DIR:
                allowed = set(_registrations(tree, "HANDLERS"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    text = node.value
                    if (text in types or FEATURE_NAME.fullmatch(text)) and text not in allowed:
                        self.fail("%s names the step type %s; use the step kind table" % (path, text))
                if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                    listed = [e.value for e in node.elts if isinstance(e, ast.Constant) and e.value in kinds]
                elif isinstance(node, ast.Dict):
                    listed = [k.value for k in node.keys if isinstance(k, ast.Constant) and k.value in kinds]
                else:
                    continue
                if len(listed) >= 2:
                    self.fail("%s lists the recipe kinds %s; use the step kind table" % (path, listed))


if __name__ == "__main__":
    unittest.main()
