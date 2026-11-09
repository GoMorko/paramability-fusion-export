"""Captures of the owner's hybrid assembly (add-in 0.3.1). They stay outside the repo; the test skips without them."""
import json
import os
import unittest

from tests import context  # noqa: F401

from lib.translator import translate

REPORTS = os.path.expanduser("~/Documents/free-projects/3mf-compose/tmp/reports")
FILES = ("report.json", "report (1).json")


class OwnerCaptureTest(unittest.TestCase):
    def test_assembly_steps_are_skipped_and_the_walk_reaches_the_part(self):
        found = [os.path.join(REPORTS, f) for f in FILES if os.path.exists(os.path.join(REPORTS, f))]
        if not found:
            self.skipTest("the owner's captures are not on this machine")
        for path in found:
            with self.subTest(os.path.basename(path)), open(path, encoding="utf-8") as f:
                capture = json.load(f)["capture"]
                own = capture["target"]["component"]["token"]
                result = translate(capture)
                walked = {v["index"]: v["verdict"] for v in result.items}
                assembly = [i["index"] for i in capture["items"] if i["type"] in ("Occurrence", "ConstructionPlane")
                            and i["index"] in walked]
                self.assertTrue(assembly and all(walked[i] == "skipped" for i in assembly))
                refused = capture["items"][result.refusal["index"]]
                self.assertEqual(refused["component"], own)


if __name__ == "__main__":
    unittest.main()
