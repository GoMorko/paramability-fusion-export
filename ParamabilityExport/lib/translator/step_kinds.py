"""The step kind table: one entry per Fusion timeline item type and one per recipe step kind. Pure: no Fusion imports.

`STEP_TYPES` lists what the add-in knows about each capture `type`: its plain words, its role in the timeline, the
reader module that reads it in Fusion, the translator handler that copies it, and which sketch records the size
probe follows for it. `RECIPE_KINDS` lists what the translator knows about each recipe step kind it writes: the
recipe version that brought it, its positions and directions, and how patterns, mirrors and combines treat it.

Handlers and readers are named by text ("module:function", "module") and resolved by the code that runs them, so
this module never imports Fusion code and the walk never imports a reader. `tests/test_step_kinds.py` checks that
every name resolves, that every reader registers only types listed here, and that no other module keeps its own list
of step types or kinds.
"""
from dataclasses import dataclass

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
    handler: "module:function" in `lib/translator` that copies it (`handle(item, ctx) -> StepResult | Refusal`),
      or None when the recipe has no step for it.
    sketches: the sketch records it carries that the size probe follows (PROFILES, AXIS, HOLE_POINTS, PATH), and
      OUTLINE_FACE when the probe reads a flat face it uses as its outline. A sketch token anywhere else in its data
      leaves that sketch unfollowed.
    unsupported: for a modeling type without a handler, the plain reason the copy stops at it.
    splits_faces: it cuts faces of a body without changing its solid, so it is skipped when the capture shows the
      body unchanged.
    makes_bodies: it can make bodies that copy others (a Paste, a pattern or mirror of bodies). Its other results are
      expected, so the walk of one body does not refuse them.
    moves_bodies: it carries the bodies its data names to another place.
    splits_bodies: it cuts bodies into pieces, and a piece may come out as a new body (translator/lineage.py).
    """

    name: str
    words: str
    role: str = MODELING
    reader: str = None
    handler: str = None
    sketches: tuple = ()
    unsupported: str = None
    splits_faces: bool = False
    makes_bodies: bool = False
    moves_bodies: bool = False
    splits_bodies: bool = False


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
    written: bool = True


STEP_TYPES = (
    StepType("ExtrudeFeature", "extrude", reader="read_solid", handler="extrude:handle",
             sketches=(PROFILES, OUTLINE_FACE)),
    StepType("RevolveFeature", "revolve", reader="read_solid", handler="revolve:handle", sketches=(PROFILES, AXIS)),
    StepType("HoleFeature", "hole", reader="read_solid", handler="hole:hole", sketches=(HOLE_POINTS,)),
    StepType("ThreadFeature", "thread", reader="read_solid", handler="hole:thread"),
    StepType("CombineFeature", "combine", reader="read_solid", handler="combine:handle"),
    StepType("FilletFeature", "fillet", reader="read_finish", handler="finish:fillet"),
    StepType("ChamferFeature", "chamfer", reader="read_finish", handler="finish:chamfer"),
    StepType("ShellFeature", "shell", reader="read_finish", handler="finish:shell"),
    StepType("DraftFeature", "draft", reader="read_finish", handler="draft:handle"),
    StepType("OffsetFacesFeature", "offset faces", reader="read_offset", handler="offset:handle"),
    StepType("RectangularPatternFeature", "rectangular pattern", reader="read_repeat",
             handler="body_copies:rectangular", makes_bodies=True),
    StepType("CircularPatternFeature", "circular pattern", reader="read_repeat", handler="body_copies:circular",
             makes_bodies=True),
    StepType("MirrorFeature", "mirror", reader="read_repeat", handler="body_copies:mirror", makes_bodies=True),
    StepType("SplitFaceFeature", "split face", splits_faces=True),
    StepType("SplitBodyFeature", "split body", reader="read_split", handler="split:handle",
             splits_bodies=True),
    StepType("CopyPasteBody", "pasted body", reader="read_paste", handler="paste:handle", makes_bodies=True),
    StepType("MoveFeature", "move", reader="read_move", handler="move:handle", moves_bodies=True),
    StepType("EmbossFeature", "emboss", reader="read_emboss", handler="emboss:handle",
             sketches=(PROFILES, OUTLINE_FACE)),
    StepType("SweepFeature", "sweep", reader="read_sweep", handler="sweep:handle", sketches=(PROFILES, PATH)),
    StepType("LoftFeature", "loft", reader="read_sweep", handler="loft:handle", sketches=(PROFILES,)),
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
    RecipeKind("thread", written=False),
    RecipeKind("coil", written=False),
    RecipeKind("skin", written=False),
    RecipeKind("draft", version=8, positions=(("faces", "near", "[]"), ("neutral", "origin")),
               directions=(("neutral", "normal"),)),
    RecipeKind("bevelGear", written=False),
)

_TYPES = {t.name: t for t in STEP_TYPES}
_KINDS = {k.name: k for k in RECIPE_KINDS}
_UNKNOWN_KIND = RecipeKind("")


def step_type(name):
    """The StepType of a capture `type`, or None for a type the table does not list (it is not copied)."""
    return _TYPES.get(name)


def role(name):
    """The role of a capture `type`: a type the table does not list counts as a modeling step."""
    found = _TYPES.get(name)
    return found.role if found else MODELING


def skipped(name):
    """Sketches, construction geometry and unreadable items: the walk passes them by."""
    return role(name) in (SKETCH, UNREAD)


def is_assembly(name):
    return role(name) == ASSEMBLY


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
