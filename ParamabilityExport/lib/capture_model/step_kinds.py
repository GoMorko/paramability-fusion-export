"""The step kind table: one entry per Fusion timeline item type and one per recipe step kind. Pure: no Fusion imports.

`STEP_TYPES` lists what the reader and the translator both know about each capture `type`: its plain words, its role
in the timeline, the reader module that reads it in Fusion, and which sketch records the size probe follows for it.
The translator keeps its own map from type to handler (`translator/handlers.py`). `RECIPE_KINDS` lists what the translator knows about each recipe step kind it writes: the
recipe version that brought it, its positions and directions, and how patterns, mirrors and combines treat it.

Readers are named by module and resolved by the capture code, so this module never imports Fusion code and the walk
never imports a reader. `tests/test_step_kinds.py` checks that every reader and every handler registers only types
listed here, that every modeling type has a handler or a reason it is not copied, and that no other module keeps its
own list of step types or kinds.
"""
from dataclasses import dataclass

from . import gap_hints

# Roles of a timeline item.
MODELING = "modeling"   # a step that can make or change a body
SKETCH = "sketch"       # sketches and construction geometry: never a modeling step, skipped by the walk
ASSEMBLY = "assembly"   # occurrences, joints and the like: never change a body in its own component
UNREAD = "unread"       # an item whose Fusion entity could not be read (type "none"): skipped by the walk

# Sketch records a step carries that the size probe can follow (`probe.plan.scan`).
PROFILES = "profiles"   # data.profiles: sketch outlines
AXIS = "axis"           # data.axis: a sketch line used as a revolve axis
HOLE_POINTS = "hole"    # data.positions with point_tokens: hole centres on a sketch
PATH = "path"           # data.path: the curves of one sketch a sweep follows
OUTLINE_FACE = "face"   # a flat face used as the outline: one in data.profiles, or the face a trimmed emboss keeps to

# When a missing step of a type only finishes surfaces (`StepType.finishing`).
FINISHING_ALWAYS = "always"       # a round, a bevel, a draft, an emboss
FINISHING_UNMODELED = "unmodeled"  # a thread drawn as a cosmetic thread: data.modeled is false

# How a pattern or mirror treats a recipe step it repeats.
SOLID = "solid"         # repeated by the pattern or mirror step itself (`of`)
FINISH = "finish"       # copied as its own step with its pick points moved to each copy


@dataclass(frozen=True)
class StepType:
    """One Fusion timeline item type.

    name: the capture `type` (the Fusion object type name).
    words: the type in plain words, for messages ("rectangular pattern").
    role: MODELING, SKETCH, ASSEMBLY or UNREAD.
    reader: the `lib/fusion_reader` module whose `READERS` dict gives its (before, after) reader pair, or None.
    sketches: the sketch records it carries that the size probe follows (PROFILES, AXIS, HOLE_POINTS, PATH), and
      OUTLINE_FACE when the probe reads a flat face it uses as its outline. A sketch token anywhere else in its data
      leaves that sketch unfollowed.
    unsupported: for a modeling type without a handler (`translator/handlers.py`), the plain reason the copy stops at
      it.
    gap_cause: for a modeling type without a handler, the `gap_hints` cause of the gap it leaves, when that cause
      has a hint for the person.
    splits_faces: it cuts faces of a body without changing its solid, so it is skipped when the capture shows the
      body unchanged.
    makes_bodies: it can make bodies that copy others (a Paste, a pattern or mirror of bodies). Its other results are
      expected, so the walk of one body does not refuse them.
    moves_bodies: it carries the bodies its data names to another place.
    splits_bodies: it cuts bodies into pieces, and a piece may come out as a new body (capture_model/lineage.py).
    reaches_bodies: it can change or take bodies of another component than its own (a Combine's tool bodies, a Move,
      a split), so the capture walk measures the target around it also when it lives in another component.
    pattern: `rectangular` or `circular` for the patterns whose copies the probe reads again at each state.
    repeats_sources: it repeats the items its data names (`data.sources`) as copies of their bodies: a pattern or a
      mirror.
    finishing: FINISHING_ALWAYS or FINISHING_UNMODELED when a missing step of this type changes neither the size of
      the part nor which bodies exist, so the gap's `finishing` flag is true (`translator/gaps/finishing.py`).
    """

    name: str
    words: str
    role: str = MODELING
    reader: str = None
    sketches: tuple = ()
    unsupported: str = None
    gap_cause: str = None
    splits_faces: bool = False
    makes_bodies: bool = False
    moves_bodies: bool = False
    splits_bodies: bool = False
    reaches_bodies: bool = False
    pattern: str = None
    repeats_sources: bool = False
    finishing: str = None


@dataclass(frozen=True)
class RecipeKind:
    """One recipe step kind.

    version: the recipe version that introduced it (0 for the base version the translator writes).
    positions, directions: paths to the points and directions it holds, which `place.place` moves and turns. "[]"
      walks a list; a path that is absent in a step is skipped.
    repeat: SOLID or FINISH when a pattern or mirror can repeat it, else None (the repeat refuses).
    repeats: it repeats other steps (`of`): it makes copies of the bodies they make.
    combine_tool: the step can be one of the steps that build the tool body of a Combine (a body made by such steps
      that only add material).
    always_cuts: it removes material whatever its `combine`.
    in_tool: the step may stand in the `features` of a `toolBody` (the recipe leaves thread, coil, skin and bevelGear
      out of a tool, since they build on the whole part).
    written: False for kinds the recipe schema has but the translator never writes.
    """

    name: str
    version: int = 0
    positions: tuple = ()
    directions: tuple = ()
    repeat: str = None
    repeats: bool = False
    combine_tool: bool = False
    always_cuts: bool = False
    in_tool: bool = True
    written: bool = True


STEP_TYPES = (
    StepType("ExtrudeFeature", "extrude", reader="read_solid", sketches=(PROFILES, OUTLINE_FACE)),
    StepType("RevolveFeature", "revolve", reader="read_solid", sketches=(PROFILES, AXIS)),
    StepType("HoleFeature", "hole", reader="read_solid", sketches=(HOLE_POINTS,)),
    StepType("ThreadFeature", "thread", reader="read_solid", finishing=FINISHING_UNMODELED),
    StepType("CombineFeature", "combine", reader="read_solid", reaches_bodies=True),
    StepType("FilletFeature", "fillet", reader="read_finish", finishing=FINISHING_ALWAYS),
    StepType("ChamferFeature", "chamfer", reader="read_finish", finishing=FINISHING_ALWAYS),
    StepType("ShellFeature", "shell", reader="read_finish"),
    StepType("DraftFeature", "draft", reader="read_finish", finishing=FINISHING_ALWAYS),
    StepType("OffsetFacesFeature", "offset faces", reader="read_offset"),
    StepType("RectangularPatternFeature", "rectangular pattern", reader="read_repeat", makes_bodies=True,
             pattern="rectangular", repeats_sources=True),
    StepType("CircularPatternFeature", "circular pattern", reader="read_repeat", makes_bodies=True, pattern="circular",
             repeats_sources=True),
    StepType("MirrorFeature", "mirror", reader="read_repeat", makes_bodies=True, repeats_sources=True),
    StepType("SplitFaceFeature", "split face", splits_faces=True),
    StepType("DeleteFaceFeature", "delete face", unsupported="Steps of type delete face are not copied yet.",
             gap_cause=gap_hints.DELETE_FACE),
    StepType("ThickenFeature", "thicken", unsupported="Steps of type thicken are not copied yet.",
             gap_cause=gap_hints.SURFACE),
    StepType("StitchFeature", "stitch", unsupported="Steps of type stitch are not copied yet.",
             gap_cause=gap_hints.SURFACE),
    StepType("BoundaryFillFeature", "boundary fill", unsupported="Steps of type boundary fill are not copied yet.",
             gap_cause=gap_hints.SURFACE),
    StepType("CoilFeature", "coil", reader="read_coil", gap_cause=gap_hints.COIL),
    StepType("SplitBodyFeature", "split body", reader="read_split", splits_bodies=True, reaches_bodies=True),
    StepType("CopyPasteBody", "pasted body", reader="read_paste", makes_bodies=True),
    StepType("MoveFeature", "move", reader="read_move", moves_bodies=True, reaches_bodies=True),
    StepType("EmbossFeature", "emboss", reader="read_emboss", sketches=(PROFILES, OUTLINE_FACE),
             finishing=FINISHING_ALWAYS),
    StepType("SweepFeature", "sweep", reader="read_sweep", sketches=(PROFILES, PATH)),
    StepType("LoftFeature", "loft", reader="read_sweep", sketches=(PROFILES,)),
    StepType("Sketch", "sketch", role=SKETCH),
    StepType("ConstructionPlane", "construction plane", role=SKETCH),
    StepType("ConstructionAxis", "construction axis", role=SKETCH),
    StepType("ConstructionPoint", "construction point", role=SKETCH),
    StepType("Occurrence", "occurrence", role=ASSEMBLY),
    StepType("Joint", "joint", role=ASSEMBLY),
    StepType("JointOrigin", "joint origin", role=ASSEMBLY),
    StepType("AsBuiltJoint", "as built joint", role=ASSEMBLY),
    StepType("RigidGroup", "rigid group", role=ASSEMBLY),
    StepType("MotionLink", "motion link", role=ASSEMBLY),
    StepType("TangentRelationship", "tangent relationship", role=ASSEMBLY),
    StepType("Snapshot", "snapshot", role=ASSEMBLY),
    StepType("Canvas", "canvas", role=ASSEMBLY),
    StepType("Decal", "decal", role=ASSEMBLY),
    StepType("none", "unreadable step", role=UNREAD),
)

_ON_SKETCH = (("sketch", "on", "origin"), ("within", "on", "origin"))
_SKETCH_DIRECTIONS = (("sketch", "on", "normal"), ("sketch", "on", "xDir"), ("within", "on", "normal"),
                      ("within", "on", "xDir"))
_EDGE_POINTS = (("edges", "near", "[]"), ("edges", "faceEdges", "near", "[]"))

RECIPE_KINDS = (
    RecipeKind("extrude", positions=_ON_SKETCH + (("extent", "upTo", "near", "[]"),), directions=_SKETCH_DIRECTIONS,
               repeat=SOLID, combine_tool=True),
    RecipeKind("revolve", positions=_ON_SKETCH, directions=_SKETCH_DIRECTIONS, repeat=SOLID, combine_tool=True),
    RecipeKind("hole", positions=(("origin",),), directions=(("direction",),), repeat=SOLID, always_cuts=True),
    RecipeKind("round", positions=_EDGE_POINTS, directions=(("edges", "parallelTo"),), repeat=FINISH),
    RecipeKind("bevel", positions=_EDGE_POINTS, directions=(("edges", "parallelTo"), ("sizeOn",)), repeat=FINISH),
    RecipeKind("shell", positions=(("openFaces", "near", "[]"),)),
    RecipeKind("offsetFaces", version=13, positions=(("faces", "near", "[]"),)),
    RecipeKind("pattern", positions=(("polar", "axisPoint"),),
               directions=(("linear", "dir"), ("linear2", "dir"), ("polar", "axis")), repeat=SOLID, repeats=True),
    RecipeKind("mirror", positions=(("plane", "origin"),), directions=(("plane", "normal"),), repeat=SOLID,
               repeats=True),
    RecipeKind("toolBody", version=15, repeat=SOLID),
    RecipeKind("move", version=15, positions=(("turn", "axisPoint"),), directions=(("translate",), ("turn", "axis"))),
    RecipeKind("loft", positions=(("sections", "[]", "on", "origin"), ("within", "on", "origin")),
               directions=(("sections", "[]", "on", "normal"), ("sections", "[]", "on", "xDir"),
                           ("within", "on", "normal"), ("within", "on", "xDir")), repeat=SOLID, combine_tool=True),
    RecipeKind("sweep", positions=(("sketch", "on", "origin"), ("path", "on", "origin"), ("path", "points", "[]")),
               directions=(("sketch", "on", "normal"), ("sketch", "on", "xDir"), ("path", "on", "normal"),
                           ("path", "on", "xDir")), repeat=SOLID, combine_tool=True),
    RecipeKind("thread", in_tool=False, written=False),
    RecipeKind("coil", positions=(("sketch", "on", "origin"),),
               directions=(("sketch", "on", "normal"), ("sketch", "on", "xDir")), combine_tool=True, in_tool=False),
    RecipeKind("skin", in_tool=False, written=False),
    RecipeKind("draft", version=8, positions=(("faces", "near", "[]"), ("neutral", "origin")),
               directions=(("neutral", "normal"),)),
    RecipeKind("bevelGear", in_tool=False, written=False),
)

_TYPES = {t.name: t for t in STEP_TYPES}
_KINDS = {k.name: k for k in RECIPE_KINDS}
_UNKNOWN_KIND = RecipeKind("")


def step_type(name):
    """The StepType of a capture `type`, or None for a type the table does not list (it is not copied)."""
    return _TYPES.get(name)


def pattern_kind(name):
    """`rectangular` or `circular` for the capture type of a pattern whose copies the probe reads, else None."""
    found = _TYPES.get(name)
    return found.pattern if found else None


def role(name):
    """The role of a capture `type`: a type the table does not list counts as a modeling step."""
    found = _TYPES.get(name)
    return found.role if found else MODELING


def skipped(name):
    """Sketches, construction geometry and unreadable items: the walk passes them by."""
    return role(name) in (SKETCH, UNREAD)


def is_assembly(name):
    return role(name) == ASSEMBLY


def keeps_to_own_bodies(name):
    """True for a listed type that cannot change bodies of another component than its own (`reaches_bodies`). A type
    the table does not list may, so it gives False."""
    found = _TYPES.get(name)
    return found is not None and not found.reaches_bodies


def makes_no_body(name):
    """Sketches, construction geometry and assembly items: they make no body and never change the shape of one in
    their component."""
    return role(name) in (SKETCH, ASSEMBLY)


def recipe_kind(name):
    """The RecipeKind of a recipe step kind; an unknown kind has every rule off."""
    return _KINDS.get(name, _UNKNOWN_KIND)


def types_with(role_name):
    """The capture types of one role, in table order."""
    return tuple(t.name for t in STEP_TYPES if t.role == role_name)
