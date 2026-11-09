import sys
import types
import unittest

from tests import context  # noqa: F401
from lib.export_plan.errors import StepExportError

# step_export imports adsk.core at load time; a stub is enough for the pure check below.
if "adsk" not in sys.modules:
    adsk = types.ModuleType("adsk")
    adsk.core = types.ModuleType("adsk.core")
    sys.modules["adsk"], sys.modules["adsk.core"] = adsk, adsk.core
from lib.fusion_reader.step_export import _require_copy_in_place  # noqa: E402


def body(lo, hi):
    point = lambda c: types.SimpleNamespace(x=c[0], y=c[1], z=c[2])  # noqa: E731
    return types.SimpleNamespace(boundingBox=types.SimpleNamespace(minPoint=point(lo), maxPoint=point(hi)))


class CopyGuardTest(unittest.TestCase):
    def test_a_copy_in_place_passes_within_the_tolerance(self):
        original = body((10, 5, 0), (14, 7, 1))
        _require_copy_in_place(body((10, 5, 0), (14, 7, 1)), original)
        _require_copy_in_place(body((10.00005, 5, 0), (14, 7, 1)), original)  # 5e-4 mm in cm
        _require_copy_in_place(None, original)

    def test_a_copy_at_the_component_origin_is_refused(self):
        with self.assertRaises(StepExportError) as raised:
            _require_copy_in_place(body((0, 0, 0), (4, 2, 1)), body((10, 5, 0), (14, 7, 1)))
        self.assertIn("did not land in its place", str(raised.exception))

    def test_an_unreadable_box_is_refused(self):
        with self.assertRaises(StepExportError):
            _require_copy_in_place(object(), body((0, 0, 0), (1, 1, 1)))


if __name__ == "__main__":
    unittest.main()
