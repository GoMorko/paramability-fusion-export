"""The outlines of a loft's sections, in section order: a sketch outline as the reader gives it, or a flat loop of the
part used as a section, written as measured.

Fusion takes two kinds of flat loop of the part as a section: a closed chain of body edges (or sketch curves) that it
gives as a path, and a flat face. Each is an outline record (a frame and its loops, as a sketch outline has). A chain
of edges gets a frame on its plane turned like the sketch outline of the other section where there is one, so
outlines of the same shape are not taken for turned ones; a face keeps the frame the reader gave it.

The copy keeps such a loop as measured, so the sizes that may move it are marked: for edges those behind the steps
written so far, or any size for edges of another body (`sweep_marks.mark_path`); for a face as for an extrude's flat
face outline (`face_outline`)."""
from . import face_outline, vec
from .path_curves import arc_of, chain
from .path_writing import flat_frame
from .result import Refusal
from .sweep_marks import mark_path

POINT = "Lofts that start or end in a point are not copied yet."
NOT_AN_OUTLINE = "A loft section is not a closed sketch outline."
PATH_OPEN = "A loft section made of edges is not a closed loop, which is not copied yet."
PATH_NOT_FLAT = "The edges of a loft section do not lie in one plane, which is not copied yet."
PATH_CURVE = "A loft section made of edges has a curve that is not copied yet."
FACE_CURVED = "A loft section that is a curved face is not copied yet."
FACE_UNREAD = "A flat face used as a loft section could not be read from Fusion, so it is not copied."


class Section:
    """One section as an outline: `profile` (frame and loops), `number` (its place among the item's sketch outlines,
    None for a loop of the part) and `source` (the section record)."""

    def __init__(self, profile, number, source):
        self.profile, self.number, self.source = profile, number, source

    @property
    def measured(self):
        return self.number is None


def refusal(section):
    """A Refusal for a section kind the copy does not take, else None."""
    kind = section.get("kind")
    if kind == "point":
        return Refusal(POINT)
    if kind == "face" and not isinstance(section.get("face"), dict):
        return Refusal(FACE_UNREAD)
    if kind not in ("profile", "path", "face"):
        return Refusal(NOT_AN_OUTLINE)
    return None


def outlines(sections, profiles):
    """The `Section` of each section record, or a Refusal. Sketch outlines come first, so a loop of the part can be
    turned like one of them."""
    sketched = [s for s in sections if s.get("kind") == "profile"]
    if any(not isinstance(s.get("profile"), int) or not 0 <= s["profile"] < len(profiles) for s in sketched):
        return Refusal(NOT_AN_OUTLINE)
    like = next((profiles[s["profile"]].get("frame") for s in sketched
                 if isinstance(profiles[s["profile"]], dict)), None)
    out = []
    for section in sections:
        if section["kind"] == "profile":
            out.append(Section(profiles[section["profile"]], section["profile"], section))
            continue
        made = (_face_outline(section["face"]) if section["kind"] == "face"
                else _path_outline(section.get("path"), like))
        if isinstance(made, Refusal):
            return made
        out.append(Section(made, None, section))
    return out


def mark_measured(ctx, item, section):
    """Mark the sizes that may move a loop of the part the copy keeps as measured."""
    if ctx.table is None:
        return
    if section.source["kind"] == "path":
        mark_path(ctx, item, section.source["path"])
        return
    face_outline.doubt(ctx, item, face_outline.may_change(ctx, section.source["face"]))


def _face_outline(face):
    if face.get("surface") not in (None, "Plane"):
        return Refusal(FACE_CURVED)
    if "loops" not in face or not isinstance(face.get("frame"), dict) or face.get("problem"):
        return Refusal(FACE_UNREAD)
    return {k: v for k, v in face.items() if k != "face"}


def _path_outline(path, like):
    if not isinstance(path, dict) or not isinstance(path.get("curves"), list) or not path["curves"]:
        return Refusal(NOT_AN_OUTLINE)
    if path.get("truncated") or any(not isinstance(c, dict) for c in path["curves"]):
        return Refusal(PATH_CURVE)
    curves = path["curves"]
    if any(c.get("kind") not in ("line", "arc", "circle") for c in curves):
        return Refusal(PATH_CURVE)
    if len(curves) == 1 and curves[0]["kind"] == "circle":
        c = curves[0]
        frame = _frame_like(c["center"], c["normal"], None, like)
        return _record(frame, [{"kind": "circle", "center": [0.0, 0.0], "radius": c["radius"]}])
    if any(c["kind"] == "circle" for c in curves):
        return Refusal(PATH_CURVE)
    found = chain(curves)
    if found is None or not found[1]:
        return Refusal(PATH_OPEN)
    ordered = found[0]
    plane = flat_frame(None, ordered)
    if plane is None:
        return Refusal(PATH_NOT_FLAT)
    first = ordered[0]
    frame = _frame_like(first["start"], plane["z"], vec.sub(first["end"], first["start"]), like)
    return _record(frame, [_flat_curve(c, frame) for c in ordered])


def _record(frame, curves):
    return {"frame": frame, "loops": [{"outer": True, "curves": curves}], "space": "sketch", "sketch": ""}


def _frame_like(origin, normal, fallback_x, like):
    """A frame on the plane through `origin` square to `normal`, its normal and x turned like the frame `like` where
    that fits (else x along `fallback_x`, or any direction in the plane)."""
    z = vec.unit(normal)
    if like is not None and vec.dot(z, like["z"]) < 0:
        z = vec.scale(z, -1.0)
    x = None
    for wanted in ([like["x"]] if like is not None else []) + ([fallback_x] if fallback_x is not None else []):
        flat = vec.sub(wanted, vec.scale(z, vec.dot(wanted, z)))
        if vec.length(flat) > 1e-6:
            x = vec.unit(flat)
            break
    if x is None:
        x = vec.unit(vec.cross(z, [1, 0, 0] if abs(z[0]) < 0.9 else [0, 1, 0]))
    return {"origin": list(origin), "x": x, "y": vec.cross(z, x), "z": z}


def _local(frame, p):
    d = vec.sub(p, frame["origin"])
    return [vec.dot(d, frame["x"]), vec.dot(d, frame["y"])]


def _flat_curve(curve, frame):
    """A chained 3D line or arc as a 2D outline curve in `frame`."""
    if curve["kind"] == "line":
        return {"kind": "line", "start": _local(frame, curve["start"]), "end": _local(frame, curve["end"])}
    centre, radius, _, _ = arc_of(curve)
    return {"kind": "arc", "start": _local(frame, curve["start"]), "mid": _local(frame, curve["mid"]),
            "end": _local(frame, curve["end"]), "center": _local(frame, centre), "radius": radius}
