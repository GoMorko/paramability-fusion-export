"""Causes of steps left out of the Orca copy that only the Orca copy gives (`Skip.cause`, the report's
`orca.left_out[].cause`).

The Orca output writes no gap file, so these causes have no hint in `capture_model.gap_hints`; they tell the report
and the tests which rule left the step out. Causes the recipe translator gives as well come from `gap_hints`.
"""

# A join or new body extrude through all: the copy cannot give it a length that stays right when sizes change.
THROUGH_ALL_ADDS = "throughAllAdds"
# A cut, intersect or hole that removes nothing from the part the copy builds (Orca stops its rebuild on it).
MISSES_PART = "missesPart"

# Tapered extrudes: an outline whose tapered walls Orca builds otherwise than Fusion (corners it rounds, arcs it
# twists, holes), and a taper on an extrude Orca does not taper (through all).
TAPER_SHAPE = "taperShape"
TAPER_EXTENT = "taperExtent"

# Sweeps: an outline Orca's sweep cannot shape the same way (a twist, a taper, one kept direction), and a path it
# cannot follow the same way (out of one plane, free curves).
SWEEP_SHAPE = "sweepShape"
SWEEP_PATH = "sweepPath"

# Lofts: two outlines Orca's loft joins in its own way (other shapes, corners that do not pair up clearly), or in
# planes that are not parallel.
LOFT_SHAPE = "loftShape"

# Revolves.
REVOLVE_AXIS = "revolveAxisOffPlane"
REVOLVE_ACROSS_AXIS = "revolveAcrossAxis"
REVOLVE_TWO_ANGLES = "revolveTwoAngles"
OUTLINE_HOLES = "outlineHoles"

# Patterns and mirrors.
COPIES_SUPPRESSED = "copiesSuppressed"
COPIES_TURNED = "copiesTurned"
COPIES_UNEVEN = "copiesUneven"
REPEATS_FINISH = "repeatsFinish"
NOT_REPEATABLE = "notRepeatable"
HOLE_PLACE_IN_TOOL = "holePlaceInTool"

# Combine, split and move.
INTERSECT_RULE = "intersectRule"
OTHER_BODY = "otherBody"
SPLIT_SIDES = "splitSides"
MOVE_MISMATCH = "moveMismatch"

# Rounds, chamfers and threads.
EDGES_UNKNOWN = "edgesUnknown"
EDGES_NOT_ON_COPY = "edgesNotOnCopy"
HAND_PICKED = "handPickedEdges"
NO_ROOM = "noRoom"
EDGES_CHANGED = "edgesChanged"
FACE_BY_NUMBER = "faceByNumber"
NEAR_ROUND = "nearRound"
THREAD_END = "threadEnd"
TAPPED_RECESS = "tappedRecess"
# Rounds and chamfers of side edges drawn into an extrude's outline (`outline_rounds`): a corner where a curve meets
# the outline, an edge the copy does not show as a whole straight side edge of the extrude (or that a later step
# changed), and an outline another feature also uses.
CORNER_CURVE = "cornerCurve"
CORNER_CHANGED = "cornerChanged"
SKETCH_SHARED = "sketchShared"
# A round or chamfer of side edges of an extrude that a later mirror or pattern copied with the body: Orca would draw
# it into the copies as well.
BODY_COPIED = "bodyCopied"
# A round or chamfer of side edges that would be drawn into an outline whose size follows a variable: the redraw would
# cost that binding, so the step is left out and the outline keeps it.
ROUND_UNBINDS = "roundUnbinds"
# A round or chamfer of side edges on an outline that follows sizes, cut as corner tools (`corner_hosts`): the tools
# cannot be worked out or written so that they give Fusion's corner (a formula Orca cannot write, too many features,
# a corner the formulas do not give, another side in the tool), or the copy cannot tell how far a variable may go
# with them.
CORNER_TOOLS = "cornerTools"
# A step whose handler stopped on an error the copy did not expect: the step is left out, the error goes to the
# report (`orca.left_out[].error`), and the rest of the copy goes on.
INTERNAL_ERROR = "internalError"
