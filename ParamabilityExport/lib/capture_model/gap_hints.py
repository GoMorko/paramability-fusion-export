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
THIN_OUTLINE = "thinOutline"
ROUND_KIND = "roundKind"
SHELL_KIND = "shellKind"
REPEAT_FACES = "repeatFaces"
SWEEP_KIND = "sweepKind"
TWIST_LONG = "twistLong"
PART_OF_PATH = "partOfPath"
GUIDE_SURFACE = "guideSurface"
SHARP_CORNER = "sharpCorner"
LOFT_KIND = "loftKind"
THREAD = "modeledThread"
COIL = "coil"
SCALE = "scale"
REPLACE_FACE = "replaceFace"
RIB_WEB = "ribWeb"
PATH_PATTERN = "pathPattern"
BOUNDARY_FILL = "boundaryFill"
NEW_COMPONENT = "newComponent"
OTHER_COMPONENT = "otherComponent"
OLD_EXPORT = "oldExport"
CHANGED_FROM_OTHER_COMPONENT = "changedFromOtherComponent"
MADE_IN_OTHER_COMPONENT = "madeInOtherComponent"
AFTER_GAP = "afterGap"

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
    THIN_OUTLINE: "Draw one closed outline for the wall, or shell a solid body.",
    ROUND_KIND: "Use a fillet with one radius.",
    SHELL_KIND: "Shell inward, with the open faces picked.",
    REPEAT_FACES: "Pattern or mirror the feature or the body.",
    SWEEP_KIND: "Use a twist or a taper alone, or a loft between two outlines.",
    TWIST_LONG: "Use a twist of 3600 degrees or less.",
    PART_OF_PATH: "Sweep along the whole path.",
    GUIDE_SURFACE: "Sweep along the same path without the guide surface, or build the shape with a loft.",
    SHARP_CORNER: "Round the sharp corner of the path with a sketch fillet.",
    LOFT_KIND: "Build it from lofts of two outlines each, or from extrudes.",
    THREAD: "Use a cosmetic thread, which copies as a plain hole.",
    COIL: "Your AI assistant can add a coil to the copy.",
    SCALE: "Change the sizes in the sketches instead of scaling the body.",
    REPLACE_FACE: "Cut the shape with an extrude, or extrude the face up to the shape you want.",
    RIB_WEB: "Draw the rib or web outline in a sketch and extrude it.",
    PATH_PATTERN: "Use a rectangular or circular pattern, or a mirror.",
    BOUNDARY_FILL: "Build the solid with extrudes and cuts instead of filling a boundary.",
    NEW_COMPONENT: "Make the body in the component that holds the part.",
    OTHER_COMPONENT: "Use sketches, planes and faces of the part's own component.",
    OLD_EXPORT: "Export again with this version of the add-in.",
    CHANGED_FROM_OTHER_COMPONENT: "Make the step in the part's own component, or export both parts together.",
    MADE_IN_OTHER_COMPONENT: "Model the body in the component you export, or export the component that holds it.",
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
