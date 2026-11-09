"""Captures of the owner's hybrid assembly (add-in 0.3.1, 0.3.2 for report (3), and 0.3.3 inside the FilterBox
package). They stay outside the repo; the tests skip without them."""
import json
import os
import unittest
import zipfile

from tests import context  # noqa: F401

from lib.translator import translate

REPORTS = os.path.expanduser("~/Documents/free-projects/3mf-compose/tmp/reports")
FILES = ("report.json", "report (1).json", "report (3).json")
PACKAGE = "Pat - Pipe, Filter (Box, Cylinder).paramability"


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


    def test_the_filter_box_steps_up_to_the_offset_are_copied(self):
        path = os.path.join(REPORTS, PACKAGE)
        if not os.path.exists(path):
            self.skipTest("the owner's package is not on this machine")
        with zipfile.ZipFile(path) as package:
            capture = json.loads(package.read("report.json"))["capture"]
        result = translate(capture)
        walked = {v["name"]: v["verdict"] for v in result.items if v["verdict"] != "skipped"}
        self.assertEqual(walked["Chamfer1"], "translated")
        self.assertEqual(walked["Extrude9"], "translated")
        self.assertEqual(result.refusal["name"], "OffsetFaces3")


if __name__ == "__main__":
    unittest.main()
