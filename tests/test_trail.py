"""The export trail (lib/timing/trail.py): the file of the last session, and the crash handler around it."""
import faulthandler
import os
import shutil
import tempfile
import unittest

from tests import context  # noqa: F401

from lib.timing import trail


def _lines():
    with open(trail.path(), encoding="utf-8") as handle:
        return [line.split(" ", 1)[1].rstrip("\n") for line in handle]


class TrailTest(unittest.TestCase):
    def setUp(self):
        self.root, self.folder = trail.ROOT, tempfile.mkdtemp()
        trail.ROOT = self.folder
        self.addCleanup(self._restore)

    def _restore(self):
        shutil.rmtree(self.folder, True)
        trail.ROOT = self.root

    def test_a_session_keeps_only_its_own_lines_and_each_line_is_on_disk_at_once(self):
        with trail.session("export"):
            trail.line("old")
        trail.line("after the session")
        with trail.session("export"):
            with trail.session("read the steps"):
                trail.line("marker to 3")
                self.assertEqual(_lines()[-1], "marker to 3")
        self.assertEqual(_lines(), ["start: export", "start: read the steps", "marker to 3", "end: read the steps",
                                    "end: export"])

    def test_the_crash_handler_is_on_during_a_session_only(self):
        was = faulthandler.is_enabled()
        with trail.session("export"):
            self.assertTrue(faulthandler.is_enabled())
        self.assertEqual(faulthandler.is_enabled(), was)

    def test_a_trail_that_cannot_be_written_never_stops_the_export(self):
        trail.ROOT = os.path.join(self.folder, "missing")
        open(trail.ROOT, "w").close()  # a file where the folder should be
        with trail.session("export"):
            trail.line("marker to 1")
        self.assertFalse(os.path.isdir(trail.ROOT))


if __name__ == "__main__":
    unittest.main()
