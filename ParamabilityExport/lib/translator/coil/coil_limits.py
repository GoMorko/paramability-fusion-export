"""Tolerances and the refusal texts of the coil handler. The caps repeat the recipe's own (`RECIPE_CAPS` of the app)."""
from ...capture_model import gap_hints

# Coil features in one recipe, turns of one coil, and turns summed over the coils of a recipe (the app shares the
# total with threads, which the add-in does not write).
MAX_COILS = 8
MAX_TURNS = 100
MAX_TURNS_TOTAL = 100

LEN_TOL = 1e-3          # mm: a measured length that equals a parameter
REL_TOL = 1e-4
VOLUME_TOL = 0.005      # share of the coil's volume (the app checks its own coil to the same share)
AREA_TOL = 1e-3         # share: the flat end face is the whole section
ZERO_TURN = 1e-6

CANNOT_READ = "This coil could not be read closely enough to copy."
OLD_EXPORT = "This coil was captured without its details. Export again with this version of the add-in to copy it."
NO_PARAMETERS = "The sizes of this coil could not be read."
SPIRAL = "Spirals are not copied yet."
SPIRAL_OR_OTHER = "This coil is a spiral or has a shape that is not copied yet."
TAPERED = "Coils with a taper angle are not copied yet."
HALF_TURNS = "Coils that end a half turn from where they start are not copied yet."
NOT_FITTING = "The shape of this coil does not match a plain helix, so it is not copied."
SECTION = "The wire of this coil has a shape that is not copied yet."
PLACE = "The place of this coil could not be worked out from its end faces."
OPERATION = "How this coil combines with the part could not be told."
TOO_MANY = "A copy holds at most %d coils."
TOO_MANY_TURNS = "A copy holds at most %d turns of coils in all."
TOUCHING = "The turns of this coil would touch each other."
NEW_COMPONENT = "Coils that make a new component are not copied."
IN_TOOL = "A coil cannot be part of a tool body that has other steps."

# The hint of each cause: `capture_model/gap_hints.py`.
CAUSE_SPIRAL = gap_hints.COIL_SPIRAL
CAUSE_TAPER = gap_hints.COIL_TAPER
CAUSE_PLACE = gap_hints.COIL_PLACE
CAUSE_LIMIT = gap_hints.COIL_LIMIT
CAUSE_TOOL = gap_hints.COIL_TOOL
CAUSE_HALF = gap_hints.COIL_HALF
CAUSE_OTHER = gap_hints.COIL
