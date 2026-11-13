"""The tolerances the probe, the export health and the capture checks use to decide that two reads of the design agree.

Each value says what it compares. The values are separate names even where equal, so one can change without the others.
"""

# Two values of one size are the same value (probe rows, tries and kept ranges).
SAME_SIZE = 1e-9
# A probed value fits a model, or two fits agree (probe fit, terms and series).
FIT_TOLERANCE = 1e-4
# Two reads of a sketch point, or of a reference point, are the same point (mm).
POINT_TOLERANCE_MM = 1e-4
# Two reads of the box of a body agree (mm).
BODY_TOLERANCE_MM = 1e-4
# The sketches after the parameters were put back are where they were at the start (mm).
RESTORE_TOLERANCE_MM = 1e-4
# A followed value (mm or degrees) may read this far from its first read before the sketch counts as on another
# solution; Fusion's own restore leaves up to about a hundredth of a degree on short lines.
FLIP_TOLERANCE = 0.05
# Curve ends closer than this (mm) are one point.
CHAIN_TOL = 1e-4
