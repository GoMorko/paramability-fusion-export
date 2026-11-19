"""Why a step was left out of the copy (its cause), and the short hint that tells the person what to change in Fusion
so the step copies.

A handler gives the cause with its Refusal (`Refusal.cause`); a step type with no handler gets it from the step kind
table (`StepType.gap_cause`). A step that stops the copy gives its cause to the walk's refusal, so the dialog and the
report show its hint too.
The hints follow the app's user guide chapter "Designing in Fusion (experimental)" (page "Steps that do not copy
yet"): when the two disagree, the chapter is right. A cause without useful advice has no hint.
"""

# Causes with a hint.
DELETE_FACE = "deleteFace"
SURFACE = "surface"
DRAFT_STEEP = "draftSteep"
TAPER_STEEP = "taperSteep"
TAPER_CUT_BOTH = "taperCutBothWays"
EXTRUDE_END_FACE = "extrudeEndFace"
EXTRUDE_START_OFFSET = "extrudeStartOffset"
EXTRUDE_WAY = "extrudeWay"
THROUGH_ADDS = "throughAllAdds"
THROUGH_BODIES = "throughAllBodies"
THIN_OUTLINE = "thinOutline"
ROUND_KIND = "roundKind"
ROUND_CHANGING = "roundChanging"
SET_UNREAD = "setUnread"
SHELL_KIND = "shellKind"
REPEAT_FACES = "repeatFaces"
SWEEP_KIND = "sweepKind"
TWIST_LONG = "twistLong"
PART_OF_PATH = "partOfPath"
GUIDE_SURFACE = "guideSurface"
SHARP_CORNER = "sharpCorner"
LOFT_KIND = "loftKind"
THREAD_PROFILE = "threadProfile"
THREAD_LIMITS = "threadLimits"
THREAD_TOOL = "threadTool"
THREAD_HOLE = "threadHole"
HOLE_END = "holeEnd"
COIL = "coil"
COIL_SPIRAL = "coilSpiral"
COIL_TAPER = "coilTaper"
COIL_PLACE = "coilPlace"
COIL_LIMIT = "coilLimit"
COIL_TOOL = "coilTool"
PIPE = "pipe"
PIPE_PART_OF_PATH = "pipePartOfPath"
COIL_HALF = "coilHalf"
SCALE = "scale"
MOVE_UNMEASURED = "moveUnmeasured"
OFFSET_CURVED = "offsetCurved"
REPLACE_FACE = "replaceFace"
RIB_WEB = "ribWeb"
PATH_PATTERN = "pathPattern"
REVOLVE_SIDES = "revolveSides"
REVOLVE_AXIS_SIDE = "revolveAxisSide"
BOUNDARY_FILL = "boundaryFill"
NEW_COMPONENT = "newComponent"
OTHER_COMPONENT = "otherComponent"
OLD_EXPORT = "oldExport"
CHANGED_FROM_OTHER_COMPONENT = "changedFromOtherComponent"
MADE_IN_OTHER_COMPONENT = "madeInOtherComponent"
AFTER_GAP = "afterGap"
ADDIN_ERROR = "addinError"
FAILS_IN_FUSION = "failsInFusion"

# Causes without a hint: a refusal that names no cause, and a step type with no handler and no cause in the table.
REFUSED = "refused"
UNSUPPORTED = "unsupported"

HINTS = {
    DELETE_FACE: "Cut the shape away with an extrude cut, or change the step that made the face.",
    SURFACE: "Build the solid with an extrude, sweep, loft or shell.",
    DRAFT_STEEP: "Draw the sloped wall in the sketch, or give the extrude a taper.",
    TAPER_STEEP: "Use a taper under 45 degrees, or draw the sloped wall in the sketch.",
    TAPER_CUT_BOTH: "Make two tapered cuts through all, one for each way, or give the cut a distance.",
    EXTRUDE_END_FACE: "Start and end on flat faces or planes, or give a distance.",
    EXTRUDE_START_OFFSET: "Start the extrude on the face itself, or on a plane at that distance from the face.",
    EXTRUDE_WAY: "End the extrude on a flat face or plane, or give it a distance.",
    THROUGH_ADDS: "Give the extrude a distance, or end it on a face or plane.",
    THROUGH_BODIES: "Let the extrude join only this body, or give it a distance.",
    THIN_OUTLINE: "Draw one closed outline for the wall, or shell a solid body.",
    ROUND_KIND: "Use a fillet with one radius.",
    ROUND_CHANGING: "Give the changing radius a fillet of its own with one edge and no radii between the ends.",
    SET_UNREAD: "Pick the edges of that set, or turn Tangent Chain off for its face, or remove the set if it changes "
                "nothing.",
    SHELL_KIND: "Shell one way only, inward or outward, with sharp or rounded corners.",
    REPEAT_FACES: "Pattern or mirror the feature or the body.",
    SWEEP_KIND: "Use a twist or a taper alone, or a loft between two outlines.",
    TWIST_LONG: "Use a twist of 3600 degrees or less.",
    PART_OF_PATH: "Sweep along the whole path.",
    GUIDE_SURFACE: "Sweep along the same path without the guide surface, or build the shape with a loft.",
    SHARP_CORNER: "Round the sharp corner of the path with a sketch fillet.",
    LOFT_KIND: "Build it from lofts of two outlines each, or from extrudes.",
    THREAD_PROFILE: "Use a metric or Unified thread (60 degrees) that is not tapered, or a cosmetic thread.",
    THREAD_LIMITS: "Use a pitch of 0.2 to 10 mm, at most 100 turns in all and 8 threads, or a cosmetic thread.",
    THREAD_TOOL: "Make the thread on the finished part, not on a body that is combined later, or use a cosmetic thread.",
    THREAD_HOLE: "Make the thread of the hole cosmetic: the hole then copies at its drill size, without the thread.",
    HOLE_END: "Let the hole end inside the part with a flat or pointed end, or make it go through all.",
    COIL: "Your AI assistant can add a coil to the copy.",
    COIL_SPIRAL: "Use a coil with a height, or let your AI assistant add the spiral to the copy.",
    COIL_TAPER: "Use a taper angle of 0, or let your AI assistant add the taper to the copy.",
    COIL_PLACE: "Make the coil a new body, then join it to the part with a combine.",
    COIL_LIMIT: "A copy holds up to 8 coils and 100 turns of coils and threads in all. Your AI assistant can add the rest.",
    COIL_HALF: "Use revolutions that do not end in a half, such as 3.25 or 4.",
    COIL_TOOL: "Join the coil to the part with a combine before you move or change it.",
    PIPE: "Draw the section on a sketch square to the path at its start, and sweep it along the path.",
    PIPE_PART_OF_PATH: "Let the pipe run along the whole path.",
    SCALE: "Change the sizes in the sketches instead of scaling the body.",
    MOVE_UNMEASURED: "Draw the sketch of the body where the body should be, instead of moving the body.",
    OFFSET_CURVED: "Press Pull flat faces only, or change the size of the curved face in its sketch.",
    REPLACE_FACE: "Cut the shape with an extrude, or extrude the face up to the shape you want.",
    RIB_WEB: ("Draw the rib or web along straight lines, with no draft or fillet, or draw its outline in a sketch "
              "and extrude it."),
    PATH_PATTERN: "Use a rectangular or circular pattern, or a mirror.",
    REVOLVE_SIDES: "Make two revolves, one to each side of the sketch.",
    REVOLVE_AXIS_SIDE: "Type size ranges that keep the outline on one side of the axis, or leave the ranges to the "
                       "add-in.",
    BOUNDARY_FILL: "Build the solid with extrudes and cuts instead of filling a boundary.",
    NEW_COMPONENT: "Make the body in the component that holds the part.",
    OTHER_COMPONENT: "Use sketches, planes and faces of the part's own component.",
    OLD_EXPORT: "Export again with this version of the add-in.",
    CHANGED_FROM_OTHER_COMPONENT: "Make the step in the part's own component, or export both parts together.",
    MADE_IN_OTHER_COMPONENT: "Model the body in the component you export, or export the component that holds it.",
    AFTER_GAP: "Fix the step it builds on first.",
    ADDIN_ERROR: "Send the report and the file export-trail.log from the ParamabilityExport temp folder with it.",
    FAILS_IN_FUSION: "Fix the step that Fusion shows in red, then export again.",
}


def refusal_cause(refusal):
    """The cause of a handler's Refusal: its own, else AFTER_GAP when it names the gaps it depends on."""
    if refusal.cause:
        return refusal.cause
    return AFTER_GAP if refusal.depends_on else REFUSED


def hint(cause):
    """The hint for `cause`, or None when there is no useful advice."""
    return HINTS.get(cause)
