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
# The end check of the body (`export_plan.probe_flow.states.body_difference`): a box that moved more than this (mm), or
# a volume that changed by more than this share, is a change on its own. A rebuild of the same shape stays far below
# both; a sketch point moved a few tenths of a mm goes past them. A smaller difference past `BODY_TOLERANCE_MM` or the
# volume tolerance of `probe.state` counts as a change only when the end check also finds an outline or a step changed.
END_BODY_BOX_MM = 0.01
END_BODY_VOLUME_SHARE = 1e-3
# The sketches after the parameters were put back are where they were at the start (mm).
RESTORE_TOLERANCE_MM = 1e-4
# A followed value (mm or degrees) may read this far from its first read before the sketch counts as on another
# solution; Fusion's own restore leaves up to about a hundredth of a degree on short lines.
FLIP_TOLERANCE = 0.05
# Curve ends closer than this (mm) are one point.
CHAIN_TOL = 1e-4
