"""Extrude feature handler (ExtrudeFeature): sketch profiles swept along their sketch normal.

Profiles that share a curve are merged into one outline (outlines.py); each outline becomes one recipe `extrude` step
per side. Fusion's sign conventions are checked against the measured
`end_offset` (where the end face landed), which wins when the two disagree. With the probe's motion file the outline
and its sketch plane follow sizes (sketch_motion.py). A start or reach on a flat face or plane follows the earlier
step that made it (follow.target_shift), else the offset the probe measured for it (reach_motion.py, and ref_motion.py
for one of another component).

A thin extrude of one closed outline without holes is written with the recipe's `thin` wall (thin_wall.py): the wall
thickness follows its parameter, and the side of the outline comes from the measured area of the end face. Open lines,
several outlines, outlines with holes, two sided and tapered thin extrudes are refused.

An extrude of text or spline outlines is also checked against the volume Fusion made.

A flat face of the part used as the outline is drawn again from the earlier extrude that made it, or written as
measured with the sizes that may change it marked (face_outline.py). Sketch outlines beside the face must lie on its
plane.

The modules: `step` (`handle`), `plan` (the sides: direction, end and length), `reach` (distance, start and reach to a
face), `taper` (the taper and its limit), `through` (the length of a cut through all and its taper check with
`through_taper.py`), `material` (the side of the part a cut through all goes to), `checks` (measured length, side walls
and volume), `built` (the outlines to write), `order` (the order of the outlines) and `common` (shared tolerances).
This package re-exports what the rest of the add-in reads as `extrude.<name>`.
"""
from .common import COMBINE
from .step import handle
from .taper import FUSION_TAPER_SIGN, MAX_TAPER_DEG, keep_angle_within

__all__ = ["COMBINE", "FUSION_TAPER_SIGN", "MAX_TAPER_DEG", "handle", "keep_angle_within"]
