import unittest

from scripts.make_release_zip import is_junk


class ReleaseZipTest(unittest.TestCase):
    def test_operating_system_and_compiled_files_stay_out_of_the_zip(self):
        for name in (".DS_Store", "._recipe_dialog.py", "Thumbs.db", "desktop.ini", "step.cpython-313.pyc"):
            self.assertTrue(is_junk(name), name)

    def test_add_in_files_go_into_the_zip(self):
        for name in ("ParamabilityExport.py", "ParamabilityExport.manifest", "icon.png", "README.md"):
            self.assertFalse(is_junk(name), name)


if __name__ == "__main__":
    unittest.main()
