"""Causes of steps left out of the Orca copy that only the Orca copy gives (`Skip.cause`, the report's
`orca.left_out[].cause`).

The Orca output writes no gap file, so these causes have no hint in `capture_model.gap_hints`; they tell the report
and the tests which rule left the step out. Causes the recipe translator gives as well come from `gap_hints`.
"""
from ..capture_model import gap_hints

# A join or new body extrude through all: the copy cannot give it a length that stays right when sizes change. The
# recipe translator gives the same cause.
THROUGH_ALL_ADDS = gap_hints.THROUGH_ADDS
# A cut, intersect or hole that removes nothing from the part the copy builds (Orca stops its rebuild on it).
MISSES_PART = "missesPart"

# Tapered extrudes: an outline whose tapered walls Orca builds otherwise than Fusion (corners it rounds, arcs it
# twists, holes), and a taper on an extrude Orca does not taper (through all).
TAPER_SHAPE = "taperShape"
TAPER_EXTENT = "taperExtent"

# Sweeps: an outline Orca's sweep cannot shape the same way (a twist, a taper, one kept direction), and a path it
# cannot follow the same way (out of one plane, free curves it cannot draw exactly).
SWEEP_SHAPE = "sweepShape"
SWEEP_PATH = "sweepPath"

# Lofts: two outlines Orca's loft joins in its own way (other shapes, corners that do not pair up clearly), or in
# planes that are not parallel.
LOFT_SHAPE = "loftShape"

# Thin extrudes: a closed outline that is not one rectangle or one circle, whose wall Orca has no plain shape for.
THIN_SHAPE = "thinShape"

# Revolves.
REVOLVE_AXIS = "revolveAxisOffPlane"
REVOLVE_ACROSS_AXIS = "revolveAcrossAxis"
OUTLINE_HOLES = "outlineHoles"
# A revolve of several outlines that do not all turn the same way at the sketch (they lie on different sides of the
# axis, or on different planes through it), so the one measured start face cannot tell how each one turned.
REVOLVE_OUTLINE_SIDES = "revolveOutlineSides"
# A round or chamfer of a face group on a body that Orca builds from several revolves joined together: the faces
# where they meet are not merged, so Orca's group holds edges Fusion does not have (`solid.seamed`).
REVOLVE_SEAM = "revolveSeam"
# Outlines of one revolve whose turns overlap: a join Orca may not make as Fusion does, or a cut whose later revolve
# would remove nothing after the earlier ones (`revolve_checks`).
REVOLVE_OVERLAP = "revolveOverlap"

# Patterns and mirrors.
COPIES_SUPPRESSED = "copiesSuppressed"
COPIES_TURNED = "copiesTurned"
COPIES_UNEVEN = "copiesUneven"
REPEATS_FINISH = "repeatsFinish"
NOT_REPEATABLE = "notRepeatable"
HOLE_PLACE_IN_TOOL = "holePlaceInTool"
# A Combine that takes the copies of a pattern or mirror of bodies (`body_pattern`): it takes only some copies, or the
# copies without the body they copy; a step changes a copy or the source on its own before the Combine; or the
# Combine keeps what the part shares with the copies.
COPIES_TAKEN = "copiesTaken"
COPY_CHANGED = "copyChanged"
COPIES_INTERSECT = "copiesIntersect"

# Combine, split and move.
INTERSECT_RULE = "intersectRule"
OTHER_BODY = "otherBody"
SPLIT_SIDES = "splitSides"
# A split whose other piece a later step changes together with the part (`roles.used_later`): the copy keeps only the
# part's piece, so what that step brings back would be missing.
PIECE_USED_LATER = "pieceUsedLater"
MOVE_MISMATCH = "moveMismatch"
# A pasted body that does not sit where the body it copies sat (`paste`): Fusion pastes in place, and the copy does not
# know what else put it there.
PASTE_PLACE = "pastePlace"

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
# Sketch text and embosses (`text_regions`, `emboss`): letters Orca would build otherwise than drawn or leave out
# without an error (a loop it cannot build, letters that touch, text with other outlines or as the first body of
# several letters), an extent Orca does not build for text (two sides, a taper), and an emboss that Fusion trims to
# its face or that sits on a face the copy cannot follow (curved, several planes, tangent faces).
TEXT_OUTLINE = "textOutline"
TEXT_EXTENT = "textExtent"
EMBOSS_TRIMMED = "embossTrimmed"
EMBOSS_FACE = "embossFace"
# Press Pull (`press_round`): only one whole round face is copied, so a Press Pull of a flat face, or of more than one
# face, is left out.
PRESS_PULL_FLAT = "pressPullFlat"
PRESS_PULL_FACES = "pressPullFaces"
# Coils (`coils`): Orca's sweep along its helix turns the wire otherwise than Fusion's coil, so every coil is left out.
COIL_SHAPE = "coilShape"
# A step that lists a body with the part's name under another token (`roles.lost`): the part may have a new token,
# so the copy cannot tell whether the step changes it.
BODY_LOST = "bodyLost"
# A step whose handler stopped on an error the copy did not expect: the step is left out, the error goes to the
# report (`orca.left_out[].error`), and the rest of the copy goes on.
INTERNAL_ERROR = "internalError"


# The causes of `gap_hints` whose tip fits the Orca copy as well. The tip of any other cause names the Paramability app
# (an AI assistant that adds a coil, the size limits of a thread, exporting parts together), so it is not shown.
_TIPS = frozenset({
    gap_hints.DELETE_FACE, gap_hints.SURFACE, gap_hints.EXTRUDE_END_FACE, gap_hints.TAPER_STEEP,
    gap_hints.THIN_OUTLINE, gap_hints.ROUND_KIND, gap_hints.REPEAT_FACES, gap_hints.SHARP_CORNER,
    gap_hints.LOFT_KIND, gap_hints.SCALE, gap_hints.REPLACE_FACE, gap_hints.RIB_WEB, gap_hints.PATH_PATTERN,
    gap_hints.REVOLVE_SIDES, gap_hints.BOUNDARY_FILL, gap_hints.NEW_COMPONENT, gap_hints.OTHER_COMPONENT,
    gap_hints.MADE_IN_OTHER_COMPONENT, gap_hints.AFTER_GAP, gap_hints.PIPE})


def tip(cause):
    """What to change in Fusion so a step left out for `cause` copies to Orca, or None."""
    return gap_hints.hint(cause) if cause in _TIPS else None
