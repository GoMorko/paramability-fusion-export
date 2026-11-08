import os
import re
import unittest

from tests import context

PURE = ["package", "translator"]


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


if __name__ == "__main__":
    unittest.main()
