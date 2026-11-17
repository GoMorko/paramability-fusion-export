"""Puts the add-in folder on the import path so tests can import lib.* without Fusion. The export trail
(`lib/timing/trail.py`) of a test run goes to a temp folder of its own, removed at the end."""
import atexit
import os
import shutil
import sys
import tempfile

ADDIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ParamabilityExport")
if ADDIN_DIR not in sys.path:
    sys.path.insert(0, ADDIN_DIR)

from lib.timing import trail  # noqa: E402

TRAIL_ROOT = tempfile.mkdtemp(prefix="paramability_trail_")
trail.ROOT = TRAIL_ROOT
atexit.register(shutil.rmtree, TRAIL_ROOT, True)
