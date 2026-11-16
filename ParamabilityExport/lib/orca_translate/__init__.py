"""A capture to an OrcaSlicer 2.5 Design tab recipe (`orca_recipe`) for one body, with what each parameter became.

Pure Python, standard library only: no Fusion imports. `translate.translate` is the entry point; `place` puts the
part on Orca's plate, `sketches` writes the outlines, `steps` the extrudes and holes, `formulas` turns the size
table's formulas into Orca's and `context` keeps what the walk found.
"""
from .translate import FIXED, PARTLY, UNUSED, VARIABLE, OrcaResult, translate

__all__ = ["FIXED", "OrcaResult", "PARTLY", "UNUSED", "VARIABLE", "translate"]
