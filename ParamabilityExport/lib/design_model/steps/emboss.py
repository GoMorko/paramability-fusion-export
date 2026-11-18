"""What an emboss step measured, as facts for any destination: whether the change of the part matches the outline
area times the depth, the face an outline that runs past its face is trimmed to, and, for an emboss on a flat face,
the extrude it stands for (`as_extrude`, after `flat_faces`, `settings_problem`, `tilted` and `tangent_problem`). A
`Problem` (`design_model/problem.py`) says why the emboss cannot be read. Pure: it reads capture dicts only."""
from ...geometry import vec
from ..problem import Problem
from .. import words

ZERO_TOL = 1e-6
VOLUME_RELATIVE_TOL = 0.01
VOLUME_ABSOLUTE_TOL = 1e-3

UNMEASURED = Problem("unmeasured", words.EMBOSS_UNMEASURED)
NOT_MATCHING = Problem("not_matching", words.EMBOSS_NOT_MATCHING)
WRONG_WAY = Problem("wrong_way", words.EMBOSS_WRONG_WAY)


def _matches(change, expected):
    return abs(abs(change) - expected) <= VOLUME_RELATIVE_TOL * expected + VOLUME_ABSOLUTE_TOL


def volume_check(data, depth):
    """`(problem, trimmed)`: a problem when the measured change of the part is neither the outline area times the
    depth nor, with an end face smaller than the outline, the end face area times the depth, or goes the way the sign
    of the depth does not say; `trimmed` is True when Fusion kept only what lies on the face."""
    areas, before, after = data.get("areas"), data.get("volume_before"), data.get("volume_after")
    if (not isinstance(areas, list) or len(areas) != len(data["profiles"]) or any(a is None for a in areas)
            or before is None or after is None):
        return UNMEASURED, False
    expected = sum(areas) * abs(depth)
    change = after - before
    trimmed = False
    if not _matches(change, expected):
        end = data.get("end_area")
        if not (isinstance(end, (int, float)) and end < sum(areas) and _matches(change, end * abs(depth))):
            return NOT_MATCHING, False
        trimmed = True
    if (change > 0) != (depth > 0):
        return WRONG_WAY, False
    return None, trimmed


def trimmed_face(data):
    """The outline record of the lone face an emboss is trimmed to (written as `within`), or None."""
    faces, depth = data.get("faces"), data.get("depth")
    if (not isinstance(faces, list) or len(faces) != 1 or not isinstance(faces[0], dict)
            or not isinstance(depth, (int, float)) or abs(depth) <= ZERO_TOL or not data.get("profiles")):
        return None
    problem, trimmed = volume_check(data, depth)
    outline = faces[0].get("outline")
    return outline if problem is None and trimmed and isinstance(outline, dict) else None


# ---- an emboss on a flat face, as the extrude it stands for ---------------------------------------------------------

PLANE_TOL = 1e-4
SIGN_TOL = 1e-9
PARALLEL_TOL = 1e-9

UNREADABLE = Problem("unreadable", words.EMBOSS_UNREADABLE)
CURVED = Problem("curved", words.EMBOSS_CURVED)
PLANES = Problem("planes", words.EMBOSS_PLANES)
NO_DEPTH = Problem("no_depth", words.EMBOSS_NO_DEPTH)
MOVED = Problem("moved", words.EMBOSS_MOVED)
NO_OUTLINE = Problem("no_outline", words.EMBOSS_NO_OUTLINE)
TILTED = Problem("tilted", words.EMBOSS_TILTED)
TANGENT = Problem("tangent", words.EMBOSS_TANGENT)

# The settings that move or turn the outline on its face (each read as its number, zero when the copy holds).
PLACE_SETTINGS = ("offset_x", "offset_y", "rotation_deg")


def flat_faces(faces):
    """The input faces when all are flat, readable and on one plane facing one way; else a Problem."""
    if not faces or any(not isinstance(f, dict) for f in faces):
        return UNREADABLE
    if any(f.get("surface") is None for f in faces):
        return UNREADABLE
    if any(f["surface"] != "Plane" for f in faces):
        return CURVED
    if any(not f.get("plane") or not f.get("outward") or not f.get("face_point") for f in faces):
        return UNREADABLE
    first = faces[0]
    normal = vec.unit(first["outward"])
    for face in faces[1:]:
        same_way = vec.dot(vec.unit(face["outward"]), normal) > 1.0 - SIGN_TOL
        lies_in = abs(vec.dot(vec.sub(face["plane"]["point"], first["plane"]["point"]), normal)) <= PLANE_TOL
        if not (same_way and lies_in):
            return PLANES
    return faces


def moved(data):
    """True when the outline is shifted or turned on the face; None when a setting could not be read."""
    settings = [data.get(key) for key in PLACE_SETTINGS]
    if any(not isinstance(v, (int, float)) for v in settings):
        return None
    return any(abs(v) > ZERO_TOL for v in settings)


def settings_problem(data):
    """A Problem when the depth or the place settings cannot be read, the depth is zero, the outline is moved or
    turned on its face, or there is no outline; else None."""
    depth, shifted = data.get("depth"), moved(data)
    if not isinstance(depth, (int, float)) or shifted is None:
        return UNREADABLE
    if abs(depth) <= ZERO_TOL:
        return NO_DEPTH
    if shifted:
        return MOVED
    if not data.get("profiles"):
        return NO_OUTLINE
    return None


def _parallel(a, b):
    return vec.length(vec.cross(vec.unit(a), vec.unit(b))) <= PARALLEL_TOL


def tilted(profiles, normal):
    """True when a sketch plane is not parallel to the face."""
    return any(isinstance(p.get("frame"), dict) and not _parallel(p["frame"]["z"], normal) for p in profiles)


def _on_plane(face, plane):
    """True when a neighbour record is a flat face on the plane of the input face."""
    own = face.get("plane") if isinstance(face, dict) else None
    if own is None or face.get("surface") != "Plane":
        return False
    same_way = abs(abs(vec.dot(vec.unit(own["normal"]), vec.unit(plane["normal"]))) - 1.0) <= SIGN_TOL
    return same_way and abs(vec.dot(vec.sub(own["point"], plane["point"]), vec.unit(plane["normal"]))) <= PLANE_TOL


def tangent_problem(data, face):
    """TANGENT when Tangent Chain is on (or unknown) and the outline could wrap onto a face that is not on the input
    plane, else None. Without the neighbours the made faces tell: any curved one gives the problem; none listed
    holds."""
    if data.get("tangent_chain") is False:
        return None
    neighbours = data.get("tangent_faces")
    if isinstance(neighbours, list):
        return TANGENT if any(not _on_plane(n, face["plane"]) for n in neighbours) else None
    made = data.get("made_surfaces")
    if isinstance(made, list) and any(kind not in (None, "Plane") for kind in made):
        return TANGENT
    return None


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


def as_extrude(data, face, depth):
    """The data of the extrude an emboss on the flat `face` stands for: its outlines extruded from the face by the
    depth, joined for a positive depth (raised) and cut for a negative one (sunk). The depth's model parameter is the
    extrude's distance (`side_one.distance`)."""
    built = {
        "operation": "join" if depth > 0 else "cut",
        # The extrude starts on the face, so the sketch plane itself places nothing.
        "profiles": [dict(p, on_start_face=True) for p in data["profiles"]],
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
    return built
