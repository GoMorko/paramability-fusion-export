"""Emboss feature handler (EmbossFeature) for an outline on a flat face.

An emboss of sketch outlines on a flat face is an extrude of those outlines that starts on the face: it joins the
part when the depth is positive (raised) and cuts it when the depth is negative (sunk). A flat face used as an outline
goes the way of an extrude from a face (sketch/face_outline.py). The handler checks what the
copy relies on, rewrites the item as such an extrude and passes it to `extrude.handle`, so outline merging, size
formulas, slabs and picks work as for any extrude. Fusion keeps one signed depth and no emboss or deboss flag.

Sketch text arrives as ordinary outline profiles (`text_outlines.py`) whose areas come from the outlines themselves,
so the volume check below also confirms that the text outlines have the area the feature used.

An outline that runs past its face (over a hole of it or off its edge) is trimmed to the face by Fusion: the end
face then holds the whole change, which is the end face area times the depth. The step is then written with `within`,
the outline of the face with its holes, so the extrude acts only on the face. The face is drawn like the outline of an
extrude from a face (sketch/face_outline.py).

Refused, with the part then saved as a fixed shape: curved input faces, an outline moved or turned on its face (the
frame of those settings is not documented), a text whose outlines could not be read, a sketch plane tilted to the
face, a result whose measured volume does not match the outline area times the depth (or, for a trimmed outline,
the end face area times the depth), and a trimmed outline whose face cannot be copied (several input faces, edges not
read, flat faces following it by Tangent Chain).
"""
import copy

from ...design_model import design
from ...design_model.steps.emboss import volume_check
from ...design_model.values import Quantity
from ...geometry import vec
from .. import extrude, placement, values
from ..result import Refusal, StepResult
from ..sketch import face_outline, loops

PLANE_TOL = 1e-4
ZERO_TOL = 1e-6
SIGN_TOL = 1e-9
PARALLEL_TOL = 1e-9

UNREADABLE = "A setting of this emboss could not be read from Fusion."


def _flat_faces(faces):
    """The input faces when all are flat, readable and on one plane facing one way; else a Refusal."""
    if not faces or any(not isinstance(f, dict) for f in faces):
        return Refusal(UNREADABLE)
    if any(f.get("surface") is None for f in faces):
        return Refusal(UNREADABLE)
    if any(f["surface"] != "Plane" for f in faces):
        return Refusal("Emboss on a curved face is not copied yet.")
    if any(not f.get("plane") or not f.get("outward") or not f.get("face_point") for f in faces):
        return Refusal(UNREADABLE)
    first = faces[0]
    normal = vec.unit(first["outward"])
    for face in faces[1:]:
        same_way = vec.dot(vec.unit(face["outward"]), normal) > 1.0 - SIGN_TOL
        lies_in = abs(vec.dot(vec.sub(face["plane"]["point"], first["plane"]["point"]), normal)) <= PLANE_TOL
        if not (same_way and lies_in):
            return Refusal("This emboss lands on faces that are not on one plane, which is not copied yet.")
    return faces


def _moved(data):
    """True when the outline is shifted or turned on the face; None when a setting could not be read."""
    settings = [data.get(key) for key in ("offset_x", "offset_y", "rotation_deg")]
    if any(not isinstance(v, (int, float)) for v in settings):
        return None
    return any(abs(v) > ZERO_TOL for v in settings)


def _parallel(a, b):
    return vec.length(vec.cross(vec.unit(a), vec.unit(b))) <= PARALLEL_TOL


def _tilted(profiles, normal):
    """True when a sketch plane is not parallel to the face."""
    return any(isinstance(p.get("frame"), dict) and not _parallel(p["frame"]["z"], normal) for p in profiles)


def _volume_check(data, depth):
    """`(refusal, trimmed)` of the shared volume check (`design_model.steps.emboss.volume_check`)."""
    problem, trimmed = volume_check(data, depth)
    return (None if problem is None else Refusal(problem.words)), trimmed


def _on_plane(face, plane):
    """True when a neighbour record is a flat face on the plane of the input face."""
    own = face.get("plane") if isinstance(face, dict) else None
    if own is None or face.get("surface") != "Plane":
        return False
    same_way = abs(abs(vec.dot(vec.unit(own["normal"]), vec.unit(plane["normal"]))) - 1.0) <= SIGN_TOL
    return same_way and abs(vec.dot(vec.sub(own["point"], plane["point"]), vec.unit(plane["normal"]))) <= PLANE_TOL


def _tangent_refusal(data, face):
    """A Refusal when Tangent Chain is on (or unknown) and the outline could wrap onto a face that is not on the
    input plane. Without the neighbours the made faces tell: any curved one refuses; none listed copies."""
    if data.get("tangent_chain") is False:
        return None
    reason = Refusal("This emboss follows tangent faces (Tangent Chain), which is not copied yet.")
    neighbours = data.get("tangent_faces")
    if isinstance(neighbours, list):
        return reason if any(not _on_plane(n, face["plane"]) for n in neighbours) else None
    made = data.get("made_surfaces")
    if isinstance(made, list) and any(kind not in (None, "Plane") for kind in made):
        return reason
    return None


def _limit(ctx, item, data, face):
    """The `FaceOutline` of the face a trimmed emboss sits on, or a Refusal when that face cannot be the limit."""
    reason = "This emboss reaches past the face it sits on, and Fusion trims it there; %s, so it is not copied."
    if len(data.get("faces") or []) > 1:
        return Refusal(reason % "it lands on several faces")
    neighbours = data.get("tangent_faces")
    if data.get("tangent_chain") is not False and isinstance(neighbours, list) and neighbours:
        return Refusal(reason % "it also follows the faces next to its face (Tangent Chain)")
    outline = face.get("outline")
    if not isinstance(outline, dict):
        return Refusal(reason % "the edges of the face could not be read")
    found = face_outline.prepare(ctx, item, [outline])
    if isinstance(found, Refusal):
        return Refusal(reason % "the edges of the face cannot be written")
    return found


def _within(ctx, limit):
    """The limit as a recipe sketch: the face's outline with its holes, on the face's plane."""
    on = placement.from_frame(limit.profile["frame"])
    if limit.drawn is not None:
        on["origin"] = limit.drawn.origin(ctx, Quantity(0.0))
        outer, inner = limit.drawn.written(ctx)
    else:
        outer, inner = copy.deepcopy(limit.loops[0]), copy.deepcopy(limit.loops[1])
    sketch = {"on": on, "outer": outer}
    if inner:
        sketch["inner"] = inner
    return sketch


def _direction(data, face, depth):
    """+1 or -1 along the first outline's sketch normal: out of the face for a positive depth, into it for a
    negative one. The measured end of the feature wins when it is known."""
    frame = next((p["frame"] for p in data["profiles"] if isinstance(p.get("frame"), dict)), None)
    if frame is None:
        return 1
    z = vec.unit(frame["z"])
    out = 1 if vec.dot(vec.unit(face["outward"]), z) >= 0 else -1
    direction = out if depth > 0 else -out
    end = data.get("end_offset")
    if end is not None:
        reach = end - vec.dot(vec.sub(face["plane"]["point"], frame["origin"]), z)
        if abs(reach) > SIGN_TOL:
            direction = 1 if reach > 0 else -1
    return direction


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    faces = _flat_faces(data.get("faces"))
    if isinstance(faces, Refusal):
        return faces
    depth = data.get("depth")
    moved = _moved(data)
    if not isinstance(depth, (int, float)) or moved is None:
        return Refusal(UNREADABLE)
    if abs(depth) <= ZERO_TOL:
        return Refusal("This emboss has no depth.")
    if moved:
        return Refusal("This emboss is moved or turned on its face, which is not copied yet.")
    profiles = data.get("profiles") or []
    if not profiles:
        return Refusal("This emboss has no sketch outline.")
    for profile in profiles:
        refusal = None if profile.get("face") else loops.outline_refusal(profile)
        if refusal is not None:
            return refusal
    face = faces[0]
    if _tilted(profiles, face["outward"]):
        return Refusal("This emboss is drawn on a plane that is tilted to its face, which is not copied yet.")
    refusal, trimmed = _volume_check(data, depth)
    if refusal is not None:
        return refusal
    limit = _limit(ctx, item, data, face) if trimmed else None
    if isinstance(limit, Refusal):
        return limit
    refusal = _tangent_refusal(data, face)
    if refusal is not None:
        return refusal
    for path in ("offset_x", "offset_y", "rotation_deg"):
        values.pin(ctx, item, path, "it sets how far %s moves its outline" % item.get("name", "an emboss"))
    built = {
        "operation": "join" if depth > 0 else "cut",
        # The extrude starts on the face, which the copy follows, so the sketch plane itself places nothing.
        "profiles": [dict(p, on_start_face=True) for p in profiles],
        "start": {"kind": "fromEntity", "plane": face["plane"], "entity_type": "BRepFace",
                  "face_point": face["face_point"]},
        "extent_type": "one",
        "side_one": {"kind": "distance", "distance": depth, "taper_deg": 0.0,
                     "direction": _direction(data, face, depth)},
        "side_two": None,
        "symmetric": None,
        "thin": False,
        "participants": data.get("participants") or [],
        "target_box_before": data.get("target_box_before"),
        "end_offset": data.get("end_offset"),
        "profile_area": data["areas"][0],
        "end_area": data.get("end_area"),
    }
    if "depth" in (data.get("params") or {}):
        built["params"] = {"side_one.distance": data["params"]["depth"]}
    outcome = extrude.handle(ctx, design.as_read(dict(item, data=built)))
    values.handled(ctx, item, "depth", same_as="side_one.distance")
    if limit is not None and isinstance(outcome, StepResult):
        for entry in outcome.entries:
            entry.step["within"] = _within(ctx, limit)
    return outcome
