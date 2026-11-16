"""Pattern and mirror handlers (RectangularPatternFeature, CircularPatternFeature, PathPatternFeature, MirrorFeature).

The copies are read from the measured transform of every pattern element, so the spacing, the turning sense and
the copies Fusion left out come from what Fusion built, not from flags. Solid sources (extrudes, revolves, holes,
other repeats) become one `pattern` or `mirror` step. Rounds and chamfers cannot be repeated by the recipe, so the
copies get their own `round` or `bevel` step with the source's `near` points moved to each copy. A Combine among the
sources, with every item that built its tools, is repeated by the steps the Combine wrote (a `toolBody` step or its
tool's steps one by one). When a rectangular pattern's count follows sizes, every copy any count can make gets its
own step, kept by a `when` on the count.

A direction that spreads copies to both sides of the original is written as a forward and a backward part that both
start at the original (`repeat/symmetric.py`); the pattern then becomes one one-sided grid for each choice of a part per
direction, and a place that two grids share is made by the first.

Each copy is a `follow.Motion`. A linear spacing that follows sizes moves the copied points with it, and the copies of
extrudes are handed to the walk (`placer_makers.CopiesMaker`), so later picks on them follow sizes too.

A mirror plane or a turning axis that sits on a face or edge of the part moves when a size moves that face or edge
(`follow.place_plane`): its origin or axis point is then written as a formula, and the copies move with it. One that
cannot be followed fixes the sizes written so far. A plane or axis of another component moves as the probe measured
it (`ref_motion`).

The handlers live in `repeat_*.py` modules, one concern each (sources, the steps built, the grid, the three
kinds of repeat, the mirror reach check); this module is the entry point the walk imports.
"""
from .repeat_build import MAX_COPIED_BODIES, copied_bodies
from .repeat_circular import axis_shift, circular, turn_motion
from .repeat_mirror import mirror
from .repeat_path import path
from .repeat_rectangular import rectangular
from .repeat_sources import MAX_REFERENCES

__all__ = ["MAX_COPIED_BODIES", "MAX_REFERENCES", "axis_shift", "circular", "copied_bodies", "mirror",
           "path", "rectangular", "turn_motion"]
