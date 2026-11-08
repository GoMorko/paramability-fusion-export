import os
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from lib.export_plan.runner import RowExport
from lib.package import caps
from lib.package.caps import PackageCapError, check_package_caps
from lib.package.writer import write_package


class CapsTest(unittest.TestCase):
    def setUp(self):
        self._saved = (caps.MAX_STEP_BYTES, caps.MAX_TOTAL_BYTES)
        caps.MAX_STEP_BYTES, caps.MAX_TOTAL_BYTES = 100, 250

    def tearDown(self):
        caps.MAX_STEP_BYTES, caps.MAX_TOTAL_BYTES = self._saved

    def test_app_limits(self):
        self.assertEqual(self._saved, (256 * 1024 ** 2, 1024 ** 3))

    def test_big_step_names_the_entry(self):
        with self.assertRaises(PackageCapError) as ctx:
            check_package_caps({"rows/01.step": b"x" * 101})
        self.assertIn("rows/01.step", str(ctx.exception))

    def test_total_over_the_cap(self):
        files = {f"rows/{i:02d}.step": b"x" * 90 for i in range(1, 4)}
        with self.assertRaises(PackageCapError) as ctx:
            check_package_caps(files)
        self.assertIn("add up", str(ctx.exception))

    def test_within_caps_passes(self):
        check_package_caps({"rows/01.step": b"x" * 100, "rows/02.step": b"x" * 100})

    def test_writer_refuses_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "x.paramability")
            with self.assertRaises(PackageCapError):
                write_package(out, {"a": 1}, {"rows/01.step": b"x" * 101})
            self.assertEqual(os.listdir(tmp), [])

    def test_runner_stops_at_the_first_big_step(self):
        written = []

        def export(path):
            written.append(path)
            with open(path, "wb") as f:
                f.write(b"x" * (101 if len(written) == 2 else 10))

        store = FakeStore({"width": "20 mm"})
        rows = [{"name": n, "values": {"width": 20.0}} for n in ("A", "B", "C")]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PackageCapError) as ctx:
                RowExport(store, {"width": "mm"}, export).run(rows, tmp, lambda i, n, name: True)
        self.assertIn("\"B\"", str(ctx.exception))
        self.assertEqual(len(written), 2)
        self.assertEqual(store.exprs["width"], "20 mm")


if __name__ == "__main__":
    unittest.main()
