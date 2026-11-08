import os
import re
import unittest

from tests import context

PURE = ["package", "translator", "export_plan"]


class BoundaryTest(unittest.TestCase):
    def test_pure_folders_do_not_import_adsk(self):
        pattern = re.compile(r"^\s*(import|from)\s+adsk\b", re.M)
        for folder in PURE:
            root = os.path.join(context.ADDIN_DIR, "lib", folder)
            for dirpath, _, names in os.walk(root):
                for name in names:
                    if name.endswith(".py"):
                        with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                            self.assertIsNone(pattern.search(f.read()), os.path.join(dirpath, name))

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


if __name__ == "__main__":
    unittest.main()
