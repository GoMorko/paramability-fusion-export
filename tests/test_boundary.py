import ast
import os
import re
import unittest

from tests import context

# The packages of the add-in and the packages each one may import, bottom to top. A new import between packages must
# fit this table, so a cycle or an upward import fails here. `fusion_reader`, `fusion_ui` and `commands` are the only
# places that use Fusion (`adsk`); `commands` sits on top.
ALLOWED_IMPORTS = {
    "package": set(),
    "geometry": set(),
    "capture_model": {"geometry"},
    "timing": set(),
    "orca_recipe": set(),
    "params": {"capture_model", "package"},
    "sketch_values": {"package"},
    "sketch_solve": {"package", "sketch_values"},
    "design_edit": {"package", "params"},
    "design_model": {"capture_model", "geometry", "package", "params", "sketch_solve", "sketch_values"},
    "results": {"design_model"},
    "translator": {"capture_model", "design_model", "geometry", "package", "params", "results", "sketch_values",
                   "timing"},
    "probe": {"capture_model", "design_model", "geometry", "package", "params", "sketch_solve", "sketch_values"},
    "orca_translate": {"capture_model", "design_model", "geometry", "orca_recipe", "params", "results", "sketch_solve",
                       "sketch_values"},
    "export_plan": {"capture_model", "design_edit", "design_model", "geometry", "orca_recipe", "orca_translate",
                    "package", "params", "probe", "results", "sketch_values", "timing", "translator"},
    "dialog_model": {"design_model", "export_plan", "package", "params", "results", "translator"},
    "fusion_reader": {"capture_model", "design_edit", "geometry", "package", "params", "timing"},
    "fusion_ui": {"dialog_model", "export_plan", "fusion_reader", "package"},
    "commands": {"design_edit", "dialog_model", "export_plan", "fusion_reader", "fusion_ui", "package", "timing"},
}

# Private names (a leading underscore) that a test reaches in another module, by test file. A name used by the
# add-in itself in another module is never listed: it is public in the module that owns it.
PRIVATE_REACHES_IN_TESTS = {
    "test_capture_reader.py": {"_target_state"},
    "test_capture_reader_helpers.py": {"_Pass"},
    "test_recipe_export.py": {"_parts_notes"},
    "test_step_export_copy_guard.py": {"_require_copy_in_place"},
    "test_translate_crossings.py": {"_from_anchors", "_joined"},
    "test_translate_follow.py": {"_fix_long_formulas"},
    "test_translate_moved_faces.py": {"_walk"},
    "test_translate_sized.py": {"_gives_whole_numbers"},
    "test_translate_sweep.py": {"_sweep_version"},
    "test_translate_sweep_limits.py": {"_scaled_volume"},
    "test_translate_text.py": {"_fit"},
    "test_translate_tool_body.py": {"_over_caps"},
}

# Modules above the shared design layer that still take the data of a timeline step from the item itself
# (`item["data"]`, `item.get("data")`, or a `data_of` or `_data` helper), by path under `lib`. A module that gets
# that data handed in is reached through one of these. The shared layer (`design_model`), the reader
# (`fusion_reader`) and the capture model (`capture_model`) read it on purpose. This list may only shrink: a module
# that moves to the facts of `design_model` leaves it, and no module joins it.
RAW_STEP_DATA = {
    "translator/faces/floating.py", "translator/gaps/gap_file.py", "translator/gaps/gap_measures.py",
    "translator/hole/step.py", "translator/hole/thread.py", "translator/repeat/body_copies.py",
    "translator/repeat/repeat_circular.py", "translator/repeat/repeat_lattice.py",
    "translator/repeat/repeat_mirror.py", "translator/repeat/repeat_rectangular.py",
    "translator/repeat/repeat_sources.py", "translator/revolve/step.py", "translator/sketch/sketch_motion.py",
}
_READS_DATA_ITSELF = ("design_model", "fusion_reader", "capture_model")
_DATA_HELPERS = ("data_of", "_data")
# Names of one output that the shared layer must not use: its refusals, skips and translation contexts.
_DESTINATION_NAMES = {"Refusal", "Skip", "Pass", "StepResult", "Context"}
_DESTINATIONS = {"translator", "orca_translate", "orca_recipe"}


def _python_files(folder):
    for dirpath, dirnames, names in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in names:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _zone(path):
    """The package a file belongs to: a folder of `lib`, or `commands`."""
    parts = os.path.relpath(path, context.ADDIN_DIR).split(os.sep)
    if parts[0] == "lib" and len(parts) > 2:
        return parts[1]
    return parts[0] if parts[0] == "commands" else None


def _imported_zones(path):
    """The packages a file imports from: every import in it, also one inside a function."""
    rel = os.path.relpath(path, context.ADDIN_DIR)[:-3].split(os.sep)
    folder = rel[:-1]
    found = set()
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets = [(a.name.split("."), []) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = folder[:len(folder) - (node.level - 1)]
                module = base + (node.module.split(".") if node.module else [])
            else:
                module = node.module.split(".") if node.module else []
            targets = [(module, [a.name for a in node.names])]
        else:
            continue
        for module, names in targets:
            if module[:1] == ["ParamabilityExport"]:
                module = module[1:]
            if module[:1] == ["lib"]:
                if len(module) > 1:
                    found.add(module[1])
                else:
                    found.update(names)
            elif module[:1] == ["commands"]:
                found.add("commands")
    return found


def _private(name):
    return name.startswith("_") and not name.startswith("__")


def _private_reaches(path):
    """The underscore names a file takes from another module: `from m import _x`, or `m._x` on an imported name."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    imported = set()
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                imported.add(a.asname or a.name)
                if _private(a.name):
                    found.add(a.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _private(node.attr):
            if isinstance(node.value, ast.Name) and node.value.id in imported:
                found.add(node.attr)
    return found


def _reads_step_data(path):
    """True when the file takes the data of a step from an item: `x["data"]`, `x.get("data")` or a data helper."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "data":
            return True
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == "data"):
            return True
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name in _DATA_HELPERS:
            return True
    return False


def _names_used(path):
    """Every name, attribute and imported name of a file."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            found.add(node.name)
        elif isinstance(node, ast.alias):
            found.add((node.asname or node.name).split(".")[-1])
    return found


class BoundaryTest(unittest.TestCase):
    def test_every_package_is_listed_and_has_more_than_one_module(self):
        lib = os.path.join(context.ADDIN_DIR, "lib")
        folders = {d for d in os.listdir(lib) if os.path.isdir(os.path.join(lib, d)) and d != "__pycache__"}
        self.assertEqual(folders | {"commands"}, set(ALLOWED_IMPORTS))
        for folder in folders:
            modules = [n for n in os.listdir(os.path.join(lib, folder)) if n.endswith(".py") and n != "__init__.py"]
            self.assertGreater(len(modules), 1, folder)

    def test_packages_import_only_the_packages_below_them(self):
        for path in _python_files(context.ADDIN_DIR):
            zone = _zone(path)
            if zone is None:
                continue
            extra = _imported_zones(path) - {zone} - ALLOWED_IMPORTS[zone]
            where = os.path.relpath(path, context.ADDIN_DIR)
            self.assertEqual(extra, set(), "%s may not import %s" % (where, sorted(extra)))

    def test_the_allowed_imports_have_no_cycle(self):
        def reaches(start, seen):
            for nxt in ALLOWED_IMPORTS[start]:
                if nxt not in seen:
                    seen.add(nxt)
                    reaches(nxt, seen)
            return seen
        for name in ALLOWED_IMPORTS:
            self.assertNotIn(name, reaches(name, set()), name)

    def test_no_module_imports_an_underscore_name_from_another(self):
        for path in _python_files(context.ADDIN_DIR):
            where = os.path.relpath(path, context.ADDIN_DIR)
            self.assertEqual(_private_reaches(path), set(), "%s reaches a private name of another module" % where)

    def test_tests_reach_only_the_private_names_listed(self):
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        found = {}
        for path in _python_files(tests_dir):
            names = _private_reaches(path)
            if names:
                found[os.path.relpath(path, tests_dir)] = names
        self.assertEqual(found, PRIVATE_REACHES_IN_TESTS)

    def test_adsk_only_in_reader_ui_and_commands(self):
        pattern = re.compile(r"^\s*(import|from)\s+adsk\b", re.M)
        allowed = ("fusion_reader", "fusion_ui", "commands")
        for dirpath, _, names in os.walk(context.ADDIN_DIR):
            rel = os.path.relpath(dirpath, context.ADDIN_DIR)
            top = rel.split(os.sep)
            zone = top[1] if top[0] == "lib" and len(top) > 1 else top[0]
            for name in names:
                if not name.endswith(".py") or zone in allowed or name == "ParamabilityExport.py":
                    continue
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    self.assertIsNone(pattern.search(f.read()), os.path.join(dirpath, name))

    def test_reader_files_that_tests_run_import_no_adsk_at_top_level(self):
        pattern = re.compile(r"^(import|from)\s+adsk\b", re.M)
        for name in ("parameters.py", "rows.py"):
            with open(os.path.join(context.ADDIN_DIR, "lib", "fusion_reader", name), encoding="utf-8") as f:
                self.assertIsNone(pattern.search(f.read()), name)



class DesignLayerTest(unittest.TestCase):
    def test_only_the_listed_modules_take_step_data_from_an_item(self):
        lib = os.path.join(context.ADDIN_DIR, "lib")
        found = set()
        for path in _python_files(lib):
            rel = os.path.relpath(path, lib).replace(os.sep, "/")
            if rel.split("/")[0] not in _READS_DATA_ITSELF and _reads_step_data(path):
                found.add(rel)
        self.assertEqual(found - RAW_STEP_DATA, set(), "new modules read the data of a step from the item")
        self.assertEqual(RAW_STEP_DATA - found, set(), "these modules no longer do: take them off the list")

    def test_the_design_layer_has_no_destination_words_or_contexts(self):
        # Its public functions take a recorder (`design_model.recorder.Recorder`); `tests/test_interfaces.py` checks
        # that the layer asks a recorder only for its declared members.
        for path in _python_files(os.path.join(context.ADDIN_DIR, "lib", "design_model")):
            where = os.path.relpath(path, context.ADDIN_DIR)
            self.assertEqual(_names_used(path) & _DESTINATION_NAMES, set(), where)
            self.assertEqual(_imported_zones(path) & _DESTINATIONS, set(), where)


if __name__ == "__main__":
    unittest.main()
