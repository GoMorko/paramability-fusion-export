"""Why a step was left out of the copy (its cause), and the short hint that tells the person what to change in Fusion
so the step copies.

A handler gives the cause with its Refusal (`Refusal.cause`); a step type with no handler gets it from the step kind
table (`StepType.gap_cause`).
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
THIN_OUTLINE = "thinOutline"
ROUND_KIND = "roundKind"
SHELL_KIND = "shellKind"
REPEAT_FACES = "repeatFaces"
SWEEP_KIND = "sweepKind"
TWIST_LONG = "twistLong"
PART_OF_PATH = "partOfPath"
LOFT_KIND = "loftKind"
THREAD = "modeledThread"
COIL = "coil"
NEW_COMPONENT = "newComponent"
OTHER_COMPONENT = "otherComponent"
AFTER_GAP = "afterGap"

# Causes without a hint: a refusal that names no cause, and a step type with no handler and no cause in the table.
REFUSED = "refused"
UNSUPPORTED = "unsupported"

HINTS = {
    DELETE_FACE: "Cut the shape away with an extrude cut, or change the step that made the face.",
    SURFACE: "Build the solid with an extrude, sweep, loft or shell.",
    DRAFT_STEEP: "Use a draft under 30 degrees, or give the extrude a taper.",
    TAPER_STEEP: "Use a taper under 45 degrees, or draw the sloped wall in the sketch.",
    TAPER_CUT_BOTH: "Make two tapered cuts through all, one for each way, or give the cut a distance.",
    EXTRUDE_END_FACE: "Start and end on flat faces or planes, or give a distance.",
    THIN_OUTLINE: "Draw one closed outline for the wall, or shell a solid body.",
    ROUND_KIND: "Use a fillet with one radius.",
    SHELL_KIND: "Shell inward, with the open faces picked.",
    REPEAT_FACES: "Pattern or mirror the feature or the body.",
    SWEEP_KIND: "Use a twist or a taper alone, or a loft between two outlines.",
    TWIST_LONG: "Use a twist of 3600 degrees or less.",
    PART_OF_PATH: "Sweep along the whole path.",
    LOFT_KIND: "Build it from lofts of two outlines each, or from extrudes.",
    THREAD: "Use a cosmetic thread, which copies as a plain hole.",
    COIL: "Your AI assistant can add a coil to the copy.",
    NEW_COMPONENT: "Make the body in the component that holds the part.",
    OTHER_COMPONENT: "Use sketches, planes and faces of the part's own component.",
    AFTER_GAP: "Fix the step it builds on first.",
}


def refusal_cause(refusal):
    """The cause of a handler's Refusal: its own, else AFTER_GAP when it names the gaps it depends on."""
    if refusal.cause:
        return refusal.cause
    return AFTER_GAP if refusal.depends_on else REFUSED


def hint(cause):
    """The hint for `cause`, or None when there is no useful advice."""
    return HINTS.get(cause)
