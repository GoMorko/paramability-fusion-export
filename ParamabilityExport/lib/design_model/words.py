"""Plain-words sentences that both outputs give for the same fact about the design: a step that cannot be read or
placed (the `Problem` sentences of the shared readers), geometry of other components that a step uses, outlines a step
takes from another component's sketch, and the refusals the two translators word alike (patterns, splits, revolves,
lofts, sweeps, rounds and chamfers).

A sentence here says what the design has and that it is not copied. It names no output, and it does not promise to copy
later, so it reads right in the recipe and in the Orca copy. Each output words the refusals that come from its own
limits. The words of sweep paths are in `paths/words.py`. Pure."""
from ..capture_model.step_kinds import step_type


def type_words(type_name):
    """The words of the step kind table, else the type name split into words: 'SweepFeature' to 'sweep',
    'RectangularPatternFeature' to 'rectangular pattern'."""
    spec = step_type(type_name)
    if spec is not None:
        return spec.words
    base = type_name[: -len("Feature")] if type_name.endswith("Feature") and type_name != "Feature" else type_name
    words = []
    for ch in base:
        if ch.isupper() and words and not words[-1][-1].isupper():
            words.append(ch)
        elif words:
            words[-1] += ch
        else:
            words.append(ch)
    return " ".join(w.lower() for w in words) or type_name


# The noun for a referenced entity, by its Fusion type.
NOUNS = {"ConstructionPlane": "a plane", "ConstructionAxis": "an axis", "BRepFace": "a face", "BRepEdge": "an edge",
         "SketchPoint": "a sketch point", "SketchLine": "a sketch line", "BRepVertex": "a corner",
         "Place": "the place"}


def step_name(item):
    return item.get("name", "a step")


def ref_phrase(item, ref, what):
    """"<step> <what> <a plane> of <component>": what a step does with a reference. A reference of the part itself
    (`own`) names no component."""
    noun = NOUNS.get(ref.get("type"), "geometry")
    if ref.get("own"):
        return "%s %s %s" % (step_name(item), what, noun)
    owner = (ref.get("component") or {}).get("name") or "another component"
    return "%s %s %s of %s" % (step_name(item), what, noun, owner)


def kept_in_place(phrase):
    """The doubt of sizes that may move a reference the copy keeps where it is."""
    return "%s that may move with it, and the copy cannot follow that" % phrase


def movers_unknown(phrase):
    """The note when the sizes that may move a reference cannot be found."""
    return "%s, and the sizes that may move it could not be found, so the copy keeps it where it is now." % phrase


def movers_unknown_doubt(phrase):
    """The doubt of every size when the sizes that may move a reference cannot be found."""
    return "%s that may move with it, and the export cannot tell which sizes move it, so the copy keeps it where it " \
        "is now" % phrase


# Why a record of another component cannot be used, by what it is.
CURVED_TARGET = "This step starts from or reaches to a curved face of another component, which is not copied."
UNPLACED_TARGET = ("This step starts from or reaches to a face or plane of another component whose place could not "
                   "be read, which is not copied.")
HOLE_ON_EDGE = "This hole is placed on an edge or point of another component, which is not copied."
HOLE_UNPLACED = "This hole is placed on a face of another component whose place could not be read, which is not copied."


def sketch_fixed(sketch, component, step):
    """The doubt of sizes that change a sketch of another component whose outline is copied as numbers."""
    return "it changes the sketch %s of %s, which %s copies as fixed numbers" % (sketch, component, step)


def sketch_may_move(sketch, component, step):
    """The doubt of sizes that may move a sketch of another component whose outline is copied as numbers: through
    that component, its place in the assembly, the plane the sketch is on or geometry projected into it."""
    return "it may move the sketch %s of %s, which %s copies as fixed numbers" % (sketch, component, step)


def sketch_outline(step, sketch, component):
    """"<step> uses an outline of the sketch <sketch> of <component>", for the reasons about a borrowed outline."""
    return "%s uses an outline of the sketch %s of %s" % (step, sketch, component)


def sketch_copied(step, sketches, fixed):
    """The note of a step that uses sketches of other components (`sketches`: "<sketch> of <component>" each)."""
    return "%s uses the sketch %s; its outline is copied in place%s." % (
        step, ", ".join(sorted(set(sketches))), " as fixed numbers" if fixed else "")


def unsupported_type(type_name):
    """Why a step of a type the copy has no reason for is left out."""
    return "Steps of type %s are not copied." % type_words(type_name or "")


# What about a timeline item cannot be read (`design.py`).
STEP_UNREAD = "This step could not be read from Fusion."
STEP_FAILS = "This step does not build in Fusion."
BODIES_UNREAD = "The bodies this step changes could not be read."

# The steps of the timeline.
SUPPRESSED = "Suppressed in Fusion."
HELPER = "Helper geometry, not part of the exported body."
IN_OTHER_COMPONENT = "In another component."
SPLITS_FACES_ONLY = "Only splits faces of the body, so the solid stays the same."

# Extrudes.
EXTRUDE_UNREADABLE = "A setting of this extrude could not be read from Fusion."
EXTRUDE_EXTENT_KIND = "This extrude sets its length in a way that is not copied."
EXTRUDE_SIDE_KIND = "This way of setting the extrude length is not copied."
EXTRUDE_START_KIND = "This extrude starts in a way that is not copied."
EXTRUDE_NO_LENGTH = "This extrude has no length."
EXTRUDE_NO_READABLE_LENGTH = "This extrude has no readable length."
EXTRUDE_FOREIGN = ("This extrude %s a curved face of another component, or one whose place could not be read, which is "
                   "not copied.")
EXTRUDE_NOT_FLAT = "This extrude %s a surface that is not flat, which is not copied."
EXTRUDE_TILTED = "This extrude %s a tilted surface, which is not copied."
EXTRUDE_ON_START = "This extrude ends on the surface it starts from."
EXTRUDE_SAME_SIDE = "Both sides of this extrude end on the same side of its sketch, which is not copied."
EXTRUDE_CHAINED = ("This extrude %s a face and the faces next to it, and its outline may reach past that face, so it "
                   "is not copied.")
EXTRUDE_FACE_UNREAD = "Whether the face this extrude %s is flat or curved could not be read, so it is not copied."
EXTRUDE_PAST_CURVED = ("This extrude %s a curved face, and its outline reaches past that face or could not be checked "
                       "against it, so it is not copied.")
EXTRUDE_WAY_UNSURE = "The face Fusion measured does not show which way this extrude goes, so it is not copied."
EXTRUDE_START_OFFSET = "This extrude starts at a distance from a face or plane, which is not copied."
TAPER_WAY = "The taper direction does not match what was measured, so it is not copied."
TAPER_UNMEASURED = "The taper of this extrude could not be measured."
TAPER_WAY_UNMEASURED = "The direction of the taper could not be measured."
TAPER_NO_CHANGE = "The taper of this extrude shows no change in size, so it is not copied."
VOLUME_UNMEASURED = "The change this extrude makes to the part could not be measured, so it is not copied."
VOLUME_DIFFERS = "The result of this extrude does not match the outlines it was drawn with, so it is not copied."
END_DIFFERS = "The measured end of this extrude does not match its length, so it is not copied."

# Outlines that cannot be written as loops (`loops.py`). `%s` is `outline_in(sketch)`.
OUTLINE_NO_CURVES = "%s has no curves."
OUTLINE_UNREAD_CURVE = "%s has a curve that could not be read closely enough to copy."
OUTLINE_OPEN = "%s is not closed."
OUTLINE_FLAT = "%s has no area."
OUTLINE_COMPLEX_CURVE = "%s has a curve that is too complex to copy closely enough."
OUTLINE_TOO_MANY_POINTS = "%s has too many points."
OUTLINE_UNPLACED = "%s could not be placed on its plane with certainty, so it is not copied."
OUTLINE_NOT_ONE_OUTER = "%s does not have exactly one outer loop."
OUTLINE_TOO_MANY_HOLES = "%s has too many holes."
OUTLINE_UNREAD = "An outline of this step could not be read from Fusion, so it is not copied."
OUTLINE_FACE = "A flat face used as a sketch outline is not copied."
TEXT_TOO_BIG = "This text has too many outline points to copy."
# Why a sketch text record without outlines (its `problem`) is not copied.
TEXT_PROBLEMS = {
    "too_many": TEXT_TOO_BIG,
    "open": "The outlines of this text could not be closed, so it is not copied.",
    "overlap": "This text has overlapping outlines, so it is not copied.",
    "space": "The place of this text on its sketch could not be told with certainty, so it is not copied.",
    "unread": "The outlines of this text could not be read from Fusion, so it is not copied.",
}


def outline_in(sketch):
    return "An outline in %s" % sketch if sketch else "An outline"


# Holes and threads.
HOLE_UNREAD = "This hole has no readable position or size."
HOLE_KIND = "This kind of hole is not copied."
HOLE_EXTENT = "This way of setting the hole depth is not copied."
HOLE_TO_OFFSET = "This hole goes up to a face or plane with an offset, which is not copied."
HOLE_NO_DEPTH = "This hole has no depth."
HOLE_END_UNREAD = "The end of this hole could not be measured."
HOLE_DRILL_POINT = "A hole that ends at a face with a drill point is not copied."
HOLE_ENDS_DIFFER = "The holes of this step end at different depths."
HOLE_THREAD_UNREAD = "The thread of this hole could not be read."
HOLE_DRILL_UNREAD = "The drill size of this tapped hole could not be measured."
THREAD_TAPERED = "Tapered threads are not copied."
THREAD_KIND_UNREAD = "The kind of thread of %s could not be read."
THREAD_PROFILE = "A thread that is not a 60 degree thread is not copied."
THREAD_FAMILY = "Only metric and Unified threads are copied, not %s."
THREAD_SIZE_UNREAD = "The size or hand of the thread of %s could not be read."
THREAD_PITCH = "A thread pitch of %g mm is not copied (%g to %g mm)."
THREAD_NO_DEPTH = "The thread of %s has no usable depth."
THREAD_NOT_CYLINDER = "A thread on a face that is not a cylinder is not copied."
THREAD_OTHER_COMPONENT = "This thread is on a face of another component, which is not copied."
THREAD_CYLINDER_UNREAD = "The cylinder of this thread could not be read."
THREAD_NOT_ONE_CYLINDER = "The faces of this thread are not one cylinder."
THREAD_FACES_APART = "The faces of this thread do not touch each other."
THREAD_START_UNREAD = "Where the thread over part of the length starts could not be read."
THREAD_START_UNCLEAR = "Where the thread over part of the length starts could not be told."
THREAD_SIDE_UNREAD = "It could not be told whether this thread is inside or outside."
THREAD_SIZE_MISMATCH = "The size of this thread does not match its cylinder."
THREAD_OFFSET = "A thread that starts away from the end of its face is not copied."
THREAD_LENGTH_UNREAD = "How long this thread runs could not be read."
THREAD_HOLE_MISMATCH = "The thread size of %s does not match the hole that was measured."
THREAD_DEPTH_UNREAD = "How deep the thread of this hole runs could not be read."
THREAD_HOLE_SPAN = ("The thread of this hole does not start at the top of the hole (or below its counterbore or "
                    "countersink) and run as deep as Fusion says, so it is not copied.")
THREAD_HOLE_ENDS_UNREAD = "The depth of this threaded hole could not be measured."
THREAD_LONGER_THAN_FACE = "The thread is longer than its face."
THREAD_DEEPER_THAN_HOLE = "The thread is deeper than its hole."

# Sweeps.
SWEEP_NOT_MATCHING = "The result of this sweep does not match its outline and path, so it is not copied."
SWEEP_END_UNCHECKED = "The end of the path of %s could not be checked against the shape Fusion made."
SWEEP_SURFACE = "Surface sweeps are not copied."
SWEEP_UNREAD = "A setting of this sweep could not be read from Fusion."
SWEEP_PATH_UNREAD = "The path of this sweep could not be read from Fusion."
SWEEP_PATH_MIXED = "The path of this sweep mixes sketch curves and body edges, which is not copied."
SWEEP_SEVERAL_OUTLINES = "Sweeps that intersect the part with several outlines at once are not copied."
SWEEP_PATH_TOO_LONG = "The path of this sweep has more parts than can be read, so it is not copied."
SWEEP_KIND = "This kind of sweep is not copied."
SWEEP_RAIL = "Sweeps with a guide rail are not copied."
SWEEP_RAIL_UNREAD = "The guide rail of this sweep could not be read from Fusion."
SWEEP_GUIDE_SURFACE = "Sweeps with a guide surface are not copied."
SWEEP_GUIDE_SURFACE_LIKELY = (
    "This sweep likely has a guide surface (Fusion did not give its orientation, twist and taper), and sweeps with a "
    "guide surface are not copied.")
SWEEP_PART_OF_PATH = "This sweep covers only part of its path, which is not copied."

# Pipes.
PIPE_SECTION_KIND = ("Pipes with a square or triangle section are not copied, since Fusion does not say which way the "
                     "section turns.")
PIPE_SECTION_UNREAD = "The section of this pipe could not be read from Fusion."
PIPE_COVER_UNREAD = "How much of its path this pipe covers could not be read from Fusion."
PIPE_PART_OF_PATH = "This pipe covers only part of its path, which is not copied."
PIPE_PATH_UNREAD = "The path of this pipe could not be read from Fusion."
PIPE_START_UNREAD = "Where the path of this pipe starts could not be read from Fusion."
PIPE_SEAM_CORNER = "This pipe starts on a sharp corner of its closed path, which is not copied."


def sweep_settings_unread(missing, said):
    """The sentence for sweep settings read as null: `missing` names them (a list of words), `said` is what Fusion
    said about them (a sorted list of texts, may be empty)."""
    named = missing[0] if len(missing) == 1 else "%s and %s" % (", ".join(missing[:-1]), missing[-1])
    tail = " (Fusion said: %s)" % "; ".join(said) if said else ""
    return "Fusion did not give the %s of this sweep%s, so it is not copied." % (named, tail)


def face_outline_label(item):
    """How reasons name the flat face the step `item` uses as its outline (the probe names it so too)."""
    return "the face %s starts on" % (item.get("name") or "a step")


# Embosses.
EMBOSS_UNMEASURED = "The change this emboss makes to the part could not be measured, so it is not copied."
EMBOSS_NOT_MATCHING = "The result of this emboss does not match its outline and depth, so it is not copied."
EMBOSS_WRONG_WAY = "This emboss does not raise or sink its outline the way its depth says, so it is not copied."
EMBOSS_UNREADABLE = "A setting of this emboss could not be read from Fusion."
EMBOSS_CURVED = "Emboss on a curved face is not copied."
EMBOSS_PLANES = "This emboss lands on faces that are not on one plane, which is not copied."
EMBOSS_NO_DEPTH = "This emboss has no depth."
EMBOSS_MOVED = "This emboss is moved or turned on its face, which is not copied."
EMBOSS_NO_OUTLINE = "This emboss has no sketch outline."
EMBOSS_TILTED = "This emboss is drawn on a plane that is tilted to its face, which is not copied."
EMBOSS_TANGENT = "This emboss follows tangent faces (Tangent Chain), which is not copied."

# Lofts, revolves and shaping steps.
LOFT_UNREAD = "A setting of this loft could not be read from Fusion."
LOFT_SURFACE = "Surface lofts are not copied."
LOFT_CLOSED = "Closed lofts are not copied."
LOFT_FEW_OUTLINES = "This loft has fewer than two outlines."
LOFT_CROSSING = "The outlines of this loft cross each other."
REVOLVE_ANGLE_KIND = "This way of setting the revolve angle is not copied."
REVOLVE_ANGLE = "This revolve turns by an angle that is not copied."
REVOLVE_ON_AXIS = "The sketch of this revolve lies on its axis."
REVOLVE_TURN_UNREAD = "The turning direction of this revolve could not be read."
REVOLVE_SYMMETRIC_CAPS = "The turn of this symmetric revolve does not match its measured ends."
ROUND_NO_EDGES = "This round has no edges to copy."
ROUND_NO_RADIUS = "This round has no readable radius."
CHAMFER_NO_EDGES = "This chamfer has no edges to copy."
CHAMFER_NO_SIZE = "This chamfer has no readable size."
# A set of a round or chamfer whose picked edges or faces Fusion did not give (`FinishSet.unread`).
ROUND_SET_UNREAD = "Fusion did not give the edges of a set of this round, so the copy cannot tell what it rounds."
CHAMFER_SET_UNREAD = "Fusion did not give the edges of a set of this chamfer, so the copy cannot tell what it cuts."

# Patterns and mirrors.
PATTERN_UNEVEN_ROUND = "The copies of this pattern are not spread evenly round the axis."
PATTERN_RULE = "The copies of this pattern do not spread to both sides of the first one by the rule that was expected."
PATTERN_NO_COPIES = "This pattern makes no copies."
PATTERN_ANGLE_UNREAD = "The angle of this pattern could not be read."
PATTERN_COPIES_UNREAD = "The copies of this pattern could not be read."
PATTERN_OFF_AXIS = "The copies of this pattern do not turn about the axis that was read."
PATTERN_ONE_LINE = "The two directions of this pattern run along one line."
PATTERN_DIRECTION_UNREAD = "The direction of this pattern could not be read."
PATTERN_ORIGINAL_LOST = "The original copy was not found among the copies of this pattern."
PATTERN_TURNED = "The copies of this pattern are turned, which is not copied."
PATTERN_UNEVEN_GRID = "The copies of this pattern do not sit on an even grid."
PATTERN_COUNT = "The copies of this pattern do not match its count."
PATTERN_FACES_DISAGREE = ("Fusion gives a place for a copy of this pattern that is not where the faces of that "
                          "copy are.")
PATTERN_PLACES_SHARED = "Fusion gives two copies of this pattern the same place."
PATTERN_PLACES_UNFILLED = ("The places Fusion gives for the copies of this pattern do not match its count, and no "
                           "copy is suppressed.")
PATTERN_TURN_UNREAD = "Which way this pattern turns its copies could not be read."
MIRROR_PLANE = "The mirror plane could not be read as a flat plane."
PATH_PATTERN_UNREAD = "The path or the settings of this path pattern could not be read."
PATH_PATTERN_CURVE = "This path pattern follows a path that is not one straight line, arc or circle, which is not copied."
PATH_PATTERN_BOTH_SIDES = "This path pattern spreads copies to both sides of its start point, which is not copied."
PATH_PATTERN_SLIDES = "The copies of this path pattern keep their direction along a round path, which is not copied."
PATH_PATTERN_RUNS_OFF = "The copies of this path pattern run past the end of its path, which is not copied."
PATH_PATTERN_WRONG_WAY = "The copies of this path pattern do not run along the path the way it was read."
PATH_PATTERN_OFF_ROUND = ("This path pattern starts part way along a round path or runs against it, where Fusion "
                          "can put the copies off the path, which is not copied.")
MIRROR_FACES = "Mirrors of faces are not copied."
REPEAT_TOOL_KEEPS = "%s keeps only what its tool shares with the part, so this %s cannot repeat it."

# Splits and tool bodies.
SPLIT_BODY_UNLISTED = "This split does not list the body it cuts."
SPLIT_PIECE_LOST = "The piece of this split that the part comes from was not found."
SPLIT_PLANE_UNREAD = "The plane of this split could not be read."
SPLIT_UNMEASURED = "The pieces of this split could not be measured."
SPLIT_BOTH_SIDES = "This split leaves pieces on both sides of its plane, which is not copied."
SPLIT_SURFACE = "This split cuts along a surface, which is not copied."
SPLIT_CURVED = "This split cuts along a curved surface or a line, which is not copied."
SPLIT_INSIDE_TOOL = "The copy could not tell which pieces of this split lie inside its tool body."
SPLIT_TOOL_UNREAD = "What this split cuts with was not read."
TOOL_NESTED_ELSEWHERE = ("The tool body %s is taken by a Combine inside a tool body of another component, which is "
                         "not copied.")


# A tool body that cannot be copied because one of its steps cannot.
def sentence(text):
    """`text` as a sentence of its own: with a full stop when it has no end mark."""
    text = (text or "").strip()
    return text if not text or text[-1] in ".!?" else text + "."


class ToolStop:
    """Why a tool body cannot be copied: one step of it cannot, and `why` says why in plain words.

    tool: the name of the tool body. step: the name of the step that stops it, or "" when it has none. why: the reason
    of that step. inside: the name of the tool body that holds that step when it is a tool of a tool, else None. When
    the stopped step is itself a Combine whose own tool cannot be built, `through` makes the stop name the step that
    really stops, once."""

    def __init__(self, tool, step, why, inside=None):
        self.tool, self.step, self.why, self.inside = tool, step or "", sentence(why), inside

    @classmethod
    def through(cls, tool, step, why, inner=None):
        """The stop of `tool` at `step` with the reason `why`. `inner` is the `ToolStop` of that step when the step
        stops for the same fact one level down: then the step that stops `inner` is named and not `step`."""
        if inner is None:
            return cls(tool, step, why)
        return cls(tool, inner.step, inner.why, inner.inside or inner.tool)

    @property
    def reason(self):
        if self.inside:
            where = "the step %s in the tool body %s" % (self.step, self.inside) if self.step \
                else "a step in the tool body %s" % self.inside
        else:
            where = "its step %s" % self.step if self.step else "one of its steps"
        return ("The tool body %s cannot be copied because of %s. %s" % (self.tool, where, self.why)).rstrip()


# Thin extrudes (`steps/thin.py`).
THIN_UNREADABLE = "A setting of this thin extrude could not be read from Fusion."
THIN_LOCATION = "The wall of this thin extrude sits in a way that is not copied."
THIN_NO_THICKNESS = "This thin extrude has no wall thickness."
THIN_TWO_WAYS = "A thin extrude that goes two ways is not copied."
THIN_REACHES = "A thin extrude that reaches to a face or goes through is not copied."
THIN_TAPER = "A thin extrude with a taper is not copied."
THIN_UNMEASURED_AREA = "The size of the wall of this thin extrude could not be measured, so it is not copied."
THIN_NOT_ONE_OUTLINE = "The outline of this thin extrude is not one closed outline of lines and arcs."
THIN_SIDE_UNSURE = "The side the wall of this thin extrude sits on could not be told, so it is not copied."
THIN_AREA_DIFFERS = "The wall of this thin extrude does not match its outline and thickness, so it is not copied."
THIN_LINE_UNREADABLE = "The line of this thin extrude could not be read."
THIN_NOT_ONE_LINE = "The line of this thin extrude is not one open line of one sketch, so it is not copied."
THIN_LINE_CURVES = "A thin extrude of a line with arcs or curves is not copied."
THIN_LINE_OPPOSED = ("The lines of this thin extrude do not all run the same way along it, so the side of its wall is not "
                     "known.")
THIN_LINE_APART = "The lines of this thin extrude do not run one after the other, so it is not copied."
THIN_WALL_UNMEASURED = "The wall of this thin extrude could not be measured, so it is not copied."
THIN_NOT_MATCHING = ("The wall Fusion made does not match the line, side and length of this thin extrude, so it is not "
                     "copied.")
THIN_UNSURE = ("The side the wall of this thin extrude stands on could not be told from what Fusion made, so it is "
               "not copied.")

# Press Pull of a whole round face (`steps/offset_round.py`).
OFFSET_ROUND_UNREAD = "The round face of this offset could not be read, so it is not copied."
OFFSET_ROUND_NOT_WHOLE = ("A round face is copied only when it goes all the way round and both its ends are flat faces "
                          "square to its axis.")
OFFSET_ROUND_MEETS = "This offset also moves a face next to the round face, so it is not copied."
OFFSET_ROUND_CLOSES = "This offset would close the round face, so it is not copied."
OFFSET_ROUND_RUNS_INTO = ("The round face of this offset would run into other edges of the faces at its ends, so it is "
                          "not copied.")
OFFSET_NOT_MEASURED = "The offset of this step could not be measured, so it is not copied."
