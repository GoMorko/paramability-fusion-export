"""Move features as plain dicts (docs/capture-format.md).

`inputEntities` holds only bodies or only faces. The bodies are read with the timeline marker just before the item
(`points_before`) and again just after it (`points_after`, found by token), each as the first vertex points of every
body, so the translator can fit the move the bodies made whatever way Fusion defines it. The definition adds what
the move was made from: distances for a move along the axes, an angle and an axis for a rotation, the transform for a
free move. A member that cannot be read is null (or `other` for a type), and the translator refuses the item.
"""
from . import read_geometry as geo
from .param_refs import Params, with_params
from .read_bodies import points_of, with_points
from .read_reference import axis_with_reference

_INPUT_KINDS = {"BRepBody": "bodies", "BRepFace": "faces"}
_MOVE_TYPES = [
    ("translatealongentity", "alongEntity"),
    ("translatexyz", "translateXYZ"),
    ("pointtopoint", "pointToPoint"),
    ("pointtoposition", "pointToPosition"),
    ("rotate", "rotate"),
    ("free", "free"),
]
_DISTANCES = ("xDistance", "yDistance", "zDistance")


def _input_kind(entities):
    kinds = {_INPUT_KINDS.get(geo.type_name(e), "other") for e in entities}
    return kinds.pop() if len(kinds) == 1 else "other"


def _move_type(definition):
    return geo.pick_by_text(geo.type_name(definition), _MOVE_TYPES, "other")


def _distances(definition):
    """The three distances in mm; one that cannot be read is null."""
    return [geo.safe(lambda: geo.length(getattr(definition, name)), None) for name in _DISTANCES]


def _definition_data(feature, definition, move_type, ctx):
    if move_type == "translateXYZ":
        return {
            "translate": _distances(definition),
            "is_design_space": geo.safe(lambda: bool(definition.isDesignSpace), None),
        }
    if move_type == "rotate":
        return {
            "angle_deg": geo.safe(lambda: geo.angle(definition.angle), None),
            "axis": geo.safe(lambda: axis_with_reference(definition.axisEntity, ctx), {"kind": "other"}),
        }
    if move_type == "free":
        return {"transform": geo.safe(lambda: geo.frame_of(feature.transform), None)}
    return {}


def _params(definition, move_type):
    found = Params()
    if move_type == "translateXYZ":
        for n, name in enumerate(_DISTANCES):
            found.add("translate.%d" % n, lambda: getattr(definition, name))
    elif move_type == "rotate":
        found.add("angle_deg", lambda: definition.angle, "angle")
    return found.found


def move_before(feature, ctx):
    entities = geo.collection_items(geo.safe(lambda: feature.inputEntities, None))
    kind = _input_kind(entities)
    bodies = [with_points(e, ctx) for e in entities] if kind == "bodies" else []
    definition = geo.safe(lambda: feature.definition, None)
    move_type = _move_type(definition)
    data = {
        "input_kind": kind,
        "bodies": [{k: v for k, v in b.items() if k != "points"} for b in bodies],
        "move_type": move_type,
        "points_before": [b["points"] for b in bodies],
        "points_after": [],
    }
    data.update(_definition_data(feature, definition, move_type, ctx))
    return with_params(data, _params(definition, move_type))


def move_after(feature, ctx, data):
    return {"points_after": [points_of(ctx, body.get("token")) for body in data.get("bodies") or []]}


# type name -> (before, after); either may be None
READERS = {
    "MoveFeature": (move_before, move_after),
}
