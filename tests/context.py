"""Puts the add-in folder on the import path so tests can import lib.* without Fusion."""
import os
import sys

ADDIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ParamabilityExport")
if ADDIN_DIR not in sys.path:
    sys.path.insert(0, ADDIN_DIR)
