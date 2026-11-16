"""The tolerances, the combine table and the small sign helpers that the extrude modules share. The tolerances and
sign helpers are the shared reader's (`design_model/steps/extrude.py`)."""
from ...design_model.steps.extrude import LENGTH_TOL, parallel, sign_of
from ...design_model import words as shared

SAMPLE_INSET = 0.02
COMBINE = {"join": "add", "cut": "cut", "intersect": "intersect", "newBody": "new"}
UNREADABLE = shared.EXTRUDE_UNREADABLE

__all__ = ["COMBINE", "LENGTH_TOL", "SAMPLE_INSET", "UNREADABLE", "parallel", "sign_of"]
