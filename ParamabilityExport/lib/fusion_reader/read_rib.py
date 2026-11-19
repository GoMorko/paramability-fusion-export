"""Rib and web features (adsk.fusion.RibFeature, WebFeature) as plain dicts (docs/capture-format.md).

A rib or a web is a wall along open sketch curves. Before the item: the curves as path records, one per chain of
curves whose ends meet (`path` for one chain, `paths` for two or more; `geometry/chains.py` puts them in order), the
thickness, whether it is symmetric, the extent (To Next or a distance) with its depth, the flip, the draft, the fillet
and, for a web, whether Fusion extends the curves to the part. After the item: the faces the feature made with their
corners, and the part's volume. The translator decides the wall from what Fusion measured.

The members of `RibFeature` and `WebFeature` are new in the API: the API stubs of older Fusion builds list none of
them. Each is read on its own: one that cannot be read becomes null, and the translator then leaves the step out.
`curves` can be read only with the marker just before the feature, where `before` runs.
"""
from ..geometry.chains import open_chains
from . import read_geometry as geo
from .param_refs import Params, with_params
from .read_solid import MAX_WALL_FACES, target_faces, wall_face
from .read_sweep import MAX_PATH_ENTITIES, chain_record, flat_record

# Corners read per face the feature made.
MAX_FACE_VERTICES = 64

_EXTENTS = {0: "toNext", 1: "distance"}
_EXTENT_NAMES = [("tonext", "toNext"), ("distance", "distance")]


def _extent(feature):
    """"toNext", "distance" or "other" for `extentType` (RibWebExtentTypes: 0 To Next, 1 Distance)."""
    raw = feature.extentType
    if isinstance(raw, bool):
        return "other"
    if isinstance(raw, int):
        return _EXTENTS.get(raw, "other")
    return geo.pick_by_text(geo.enum_name(raw, "RibWebExtentTypes"), _EXTENT_NAMES, "other")


def _optional(read, convert):
    """A setting that Fusion gives as a parameter only when it is used (`draftAngle`, `filletRadius`): 0 when the
    member is null, its value otherwise, and null when it cannot be read."""
    return geo.safe(lambda: 0.0 if read() is None else convert(read()), None)


def _flag(read):
    return geo.safe(lambda: bool(read()), None)


def _ends(curve):
    """(start, end) of a sketch curve in its sketch's 2D plane, or None."""
    flat = flat_record(curve)
    if not isinstance(flat, dict) or flat.get("start") is None or flat.get("end") is None:
        return None
    return flat["start"], flat["end"]


def chains_of(curves, ctx):
    """The path records of the curves (`chain_record`), one per chain, or None when the curves cannot be read, are
    not sketch curves of one plane, or do not make open chains (`open_chains`)."""
    if not curves or len(curves) > MAX_PATH_ENTITIES:
        return None
    ends = [geo.safe(lambda: _ends(geo.native_input(c, ctx)), None) for c in curves]
    if any(e is None for e in ends):
        return None
    chains = open_chains(ends)
    if chains is None:
        return None
    return [chain_record([(curves[n], reverse) for n, reverse in chain], ctx) for chain in chains]


def _params(feature, extent):
    """The parameters behind the values; `depth` only for a depth set as a distance."""
    found = Params()
    found.add("thickness", lambda: feature.thickness)
    if extent == "distance":
        found.add("depth", lambda: feature.depth)
    found.add("draft_deg", lambda: feature.draftAngle, "angle")
    found.add("fillet", lambda: feature.filletRadius)
    return found.found


def _before(feature, ctx, kind):
    curves = geo.safe(lambda: geo.sequence_items(feature.curves), None)
    chains = chains_of(curves, ctx) if curves is not None else None
    extent = geo.safe(lambda: _extent(feature), "other")
    data = {
        "kind": kind,
        "operation": "join",
        "thickness": geo.safe(lambda: geo.length(feature.thickness), None),
        "symmetric": _flag(lambda: feature.isSymmetric),
        "extent": extent,
        "depth": geo.safe(lambda: geo.length(feature.depth), None) if extent == "distance" else None,
        "flipped": _flag(lambda: feature.isFlipped),
        "draft_deg": _optional(lambda: feature.draftAngle, geo.angle),
        "fillet": _optional(lambda: feature.filletRadius, geo.length),
        "participants": [],
        "target_box_before": ctx.target_box(),
        "volume_before": geo.target_volume(ctx),
        "volume_after": None,
        "wall_faces": None,
    }
    if kind == "web":
        data["extended"] = _flag(lambda: feature.isExtended)
    if chains is None:
        data["paths"] = None
    elif len(chains) == 1:
        data["path"] = chains[0]
    else:
        data["paths"] = chains
    data["target_faces_body"], data["target_faces_before"] = target_faces(ctx)
    return with_params(data, _params(feature, extent))


def rib_before(feature, ctx):
    return _before(feature, ctx, "rib")


def web_before(feature, ctx):
    return _before(feature, ctx, "web")


def _made_face(face, ctx):
    """A `wall_face` record of one face the feature made, with `vertices`, its corners (null when they cannot be read
    or there are more than MAX_FACE_VERTICES)."""
    face = geo.native_input(face, ctx)
    record = wall_face(face)
    corners = geo.safe(lambda: geo.face_vertices(face), None)
    record["vertices"] = corners if corners is not None and len(corners) <= MAX_FACE_VERTICES else None
    return record


def after(feature, ctx, data):
    """wall_faces: the faces the feature made (`faces`), each with its corners; null when they cannot be read or
    there are more than MAX_WALL_FACES. volume_after: the part's volume."""
    faces = geo.safe(lambda: geo.sequence_items(feature.faces), None)
    made = None if faces is None or len(faces) > MAX_WALL_FACES else [_made_face(f, ctx) for f in faces]
    return {"wall_faces": made, "volume_after": geo.target_volume(ctx)}


READERS = {"RibFeature": (rib_before, after), "WebFeature": (web_before, after)}
