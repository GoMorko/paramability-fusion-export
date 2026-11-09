"""Offset faces handler (OffsetFacesFeature, press pull).

A flat face whose side walls stand square to it moves the same way as an extrude of its outline: outwards it adds a
slab of the offset's thickness, inwards it cuts one. Each face becomes one extrude step through the extrude handler.
Curved faces, faces with leaning or rounded side walls, and faces that touch each other are refused, since there
the side walls would have to grow or shrink with the face.
"""
from . import extrude, vec
from .result import Refusal
from .values import number

TYPES = ("OffsetFacesFeature",)

MOVE_TOL_MM = 1e-3
NORMAL_TOL = 1e-6


def _moved_as_read(face, distance, after):
    """True when a face Fusion left after the step lies on the face's plane moved by `distance` along its normal."""
    frame = face["frame"]
    for found in after:
        if vec.dot(found["normal"], frame["z"]) < 1.0 - NORMAL_TOL:
            continue
        if abs(vec.dot(vec.sub(found["point"], frame["origin"]), frame["z"]) - distance) <= MOVE_TOL_MM:
            return True
    return False


def _face_refusal(face, distance, after):
    if face.get("kind") == "other" or "loops" not in face:
        return Refusal("Offsets of curved faces are not copied yet.")
    if face.get("sides") != "square":
        return Refusal("Offsets of faces whose side walls lean or curve are not copied yet.")
    if face.get("meets_offset"):
        return Refusal("Offsets of faces that touch each other are not copied yet.")
    if not _moved_as_read(face, distance, after):
        return Refusal("The offset of this step could not be measured, so it is not copied.")
    return None


def _as_extrude(item, data, face):
    """The item as an extrude of the face outline by the offset distance (the face normal points out)."""
    distance = data["distance"]
    params = data.get("params") or {}
    extrude_data = {
        "operation": "join" if distance > 0 else "cut",
        "profiles": [{"sketch": "", "frame": face["frame"], "space": "sketch", "loops": face["loops"]}],
        "start": {"kind": "profilePlane"},
        "extent_type": "one",
        "side_one": {"kind": "distance", "distance": distance, "taper_deg": 0.0},
        "side_two": None,
        "symmetric": None,
        "thin": False,
        "participants": [],
        "target_box_before": None,
        "end_offset": None,
        "profile_area": None,
        "end_area": None,
    }
    if "distance" in params:
        extrude_data["params"] = {"side_one.distance": params["distance"]}
    return dict(item, data=extrude_data)


def handle(item, ctx):
    data = item.get("data") or {}
    if data.get("read_error"):
        return Refusal("This step could not be read from Fusion.")
    distance = data.get("distance")
    faces = data.get("faces") or []
    if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not faces:
        return Refusal("The faces or the distance of this offset could not be read.")
    if not abs(number(distance)) > 0:
        return Refusal("This offset has no distance.")
    after = data.get("faces_after") or []
    for face in faces:
        refusal = _face_refusal(face, distance, after)
        if refusal:
            return refusal
    steps = []
    for face in faces:
        outcome = extrude.handle(_as_extrude(item, data, face), ctx)
        if isinstance(outcome, Refusal):
            return outcome
        steps += outcome
    return steps
