import json
import os
import tempfile
import unittest
import zipfile

from tests import context  # noqa: F401
from lib.package import manifest as mf
from lib.package.writer import write_package


class WriterTest(unittest.TestCase):
    def test_zip_layout(self):
        m = mf.build_step_only_manifest("Part", "w")
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.step")
            with open(src, "wb") as f:
                f.write(b"STEP-FILE")
            out = os.path.join(d, "p.paramability")
            write_package(out, m, {"part.step": src, "report.json": b"{}"})
            with zipfile.ZipFile(out) as zf:
                self.assertEqual(zf.namelist(), ["manifest.json", "part.step", "report.json"])
                self.assertEqual(json.loads(zf.read("manifest.json")), m)
                self.assertEqual(zf.read("part.step"), b"STEP-FILE")
                self.assertEqual(zf.getinfo("part.step").compress_type, zipfile.ZIP_DEFLATED)
            self.assertEqual(os.listdir(d).count("p.paramability"), 1)
            self.assertFalse([n for n in os.listdir(d) if n.endswith(".tmp")])

    def test_failure_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "p.paramability")
            with self.assertRaises(FileNotFoundError):
                write_package(out, {}, {"part.step": os.path.join(d, "missing.step")})
            self.assertEqual(os.listdir(d), [])

    def test_replaces_existing(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "p.paramability")
            write_package(out, {"a": 1}, {})
            write_package(out, {"a": 2}, {})
            with zipfile.ZipFile(out) as zf:
                self.assertEqual(json.loads(zf.read("manifest.json")), {"a": 2})

    def test_rejects_manifest_entry(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                write_package(os.path.join(d, "p"), {}, {"manifest.json": b"x"})


if __name__ == "__main__":
    unittest.main()
