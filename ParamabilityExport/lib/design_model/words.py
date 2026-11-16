"""Plain-words texts of the facts the shared layer records: geometry of other components that a step uses, and
outlines a step takes from another component's sketch. Each destination words its own refusals; these texts say
what is known, so both translators give the same sentence for the same fact."""

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


# Why a record of another component cannot be used, by what it is.
CURVED_TARGET = "This step starts from or reaches to a curved face of another component, which is not copied."
UNPLACED_TARGET = ("This step starts from or reaches to a face or plane of another component whose place could not "
                   "be read, which is not copied.")
HOLE_ON_EDGE = "This hole is placed on an edge or point of another component, which is not copied."
HOLE_UNPLACED = "This hole is placed on a face of another component whose place could not be read, which is not copied."


def sketch_fixed(sketch, component, step):
    """The doubt of sizes that change a sketch of another component whose outline is copied as numbers."""
    return "it changes the sketch %s of %s, which %s copies as fixed numbers" % (sketch, component, step)


def sketch_copied(step, sketches, fixed):
    """The note of a step that uses sketches of other components (`sketches`: "<sketch> of <component>" each)."""
    return "%s uses the sketch %s; its outline is copied in place%s." % (
        step, ", ".join(sorted(set(sketches))), " as fixed numbers" if fixed else "")


# What about a timeline item cannot be read (`design.py`).
STEP_UNREAD = "This step could not be read from Fusion."
STEP_FAILS = "This step does not build in Fusion."
BODIES_UNREAD = "The bodies this step changes could not be read."
