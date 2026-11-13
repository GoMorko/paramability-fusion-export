"""The sketches and flat faces the probe can follow: which capture records name them, and which it leaves alone."""
from ...sketch_values import keys
from ...translator import emboss, face_outline
from ...translator.loops import profile_loops
from ...translator.result import Refusal
from ...translator.step_kinds import AXIS, HOLE_POINTS, OUTLINE_FACE, PATH, PROFILES, step_type

_CURVES = ("line", "arc", "circle", "ellipse")
_PATH_CURVES = ("line", "arc", "circle")


class Scan:
    """`targets`: the covered records (dicts with `kind` "profile", "hole", "axis", "path" or "face", `item` and what
    the fit reads; a face's `sketch_token` is its key prefix, `keys.face`).
    `covered`: sketch token to name ("" when the record has none). `uncovered`: tokens of sketches that some record
    uses in a way the probe cannot follow. `named`: the name of every sketch a record names, covered or not, by token
    (a sketch no record gives a name for is missing). `native`: tokens of the covered sketches of tool bodies from other
    components: they are read in their own component's frame, not brought into the part's (`request`). `faces`: the
    face targets' key prefix to the name reasons give the face."""

    def __init__(self):
        self.targets = []
        self.faces = {}
        self.native = set()
        self.covered = {}
        self.uncovered = set()
        self.named = {}

    def note_name(self, token, name):
        if token and isinstance(name, str) and name:
            self.named.setdefault(token, name)


def _profile_ok(profile):
    if profile.get("face") or "loops" not in profile or not profile.get("sketch_token"):
        return False
    curves = [c for loop in profile["loops"] for c in (loop.get("curves") or [])]
    if not curves or any(c.get("kind") not in _CURVES or not c.get("entity") for c in curves):
        return False
    return not isinstance(profile_loops(profile), Refusal)


def _stray_tokens(node, out):
    """Sketch tokens that a record carries; any such record other than the ones scanned leaves its sketch uncovered."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "sketch_token" and isinstance(value, str):
                out.uncovered.add(value)
                out.note_name(value, node.get("sketch"))
            else:
                _stray_tokens(value, out)
    elif isinstance(node, list):
        for value in node:
            _stray_tokens(value, out)


def scan(capture):
    """The `Scan` of a capture: its items in the target's component, and the steps of tool bodies from other
    components (`helper_of`), that carry a profile, a hole or a revolve axis."""
    out = Scan()
    for item in capture.get("items") or []:
        data = item.get("data") or {}
        if (item.get("suppressed") or (item.get("in_target_component") is False and not item.get("helper_of"))
                or "read_error" in data):
            continue
        spec = step_type(item.get("type"))
        records = spec.sketches if spec is not None else ()
        before = len(out.targets)
        for record in records:
            _SCANNERS[record](out, item.get("index"), data)
        if not records:
            _stray_tokens(data, out)
        if item.get("helper_of"):
            # A tool body of another component is read in its own frame; its faces are not read again.
            out.targets[before:] = [t for t in out.targets[before:] if t["kind"] != FACE]
            out.native.update(t["sketch_token"] for t in out.targets[before:])
        for target in out.targets[before:]:
            if target["kind"] == FACE:
                target["sketch"] = out.faces[target["sketch_token"]] = face_outline.label(item)
    for token in out.uncovered:
        out.covered.pop(token, None)
    out.targets = [t for t in out.targets if t["sketch_token"] in out.covered or t["kind"] == FACE]
    return out


def _cover(out, token, name):
    out.note_name(token, name)
    out.covered.setdefault(token, name or "")
    if name and not out.covered[token]:
        out.covered[token] = name


def _scan_profiles(out, index, data):
    for number, profile in enumerate(data.get("profiles") or []):
        if not isinstance(profile, dict) or profile.get("foreign") or profile.get("face"):
            continue
        token = profile.get("sketch_token")
        if not _profile_ok(profile):
            if token:
                out.uncovered.add(token)
                out.note_name(token, profile.get("sketch"))
            continue
        _cover(out, token, profile.get("sketch"))
        out.targets.append({"kind": "profile", "item": index, "p": number, "profile": profile,
                            "sketch_token": token, "sketch": profile.get("sketch") or "",
                            "reference": profile.get("reference") or {}})


def _path_ok(path):
    """True when every curve of a sweep path is a sketch line, arc or circle of one sketch the probe can read again:
    a token, the curve in the sketch's own plane (`flat`), and the sketch's frame."""
    curves = path.get("curves")
    if (path.get("kind") != "sketch" or path.get("foreign") or path.get("truncated") or not path.get("sketch_token")
            or not isinstance(path.get("frame"), dict) or not isinstance(curves, list) or not curves):
        return False
    return all(isinstance(c, dict) and c.get("kind") in _PATH_CURVES and c.get("entity") and isinstance(
        c.get("flat"), dict) and c["flat"].get("kind") == c["kind"] for c in curves)


def _scan_path(out, index, data):
    """A sweep path of lines and arcs. A path with a free curve, or of body edges, is not covered and leaves its
    sketch as it is: the translator writes such a path as measured."""
    path = data.get("path")
    if not isinstance(path, dict) or not _path_ok(path):
        return
    token = path["sketch_token"]
    _cover(out, token, path.get("sketch"))
    out.targets.append({"kind": "path", "item": index, "path": path, "sketch_token": token,
                        "sketch": path.get("sketch") or "", "reference": path.get("reference") or {}})


def _scan_axis(out, index, data):
    axis = data.get("axis")
    if not isinstance(axis, dict) or "entity" not in axis:
        return
    token = axis.get("sketch_token")
    if not token or "point" not in axis or "dir" not in axis:
        if token:
            out.uncovered.add(token)
            out.note_name(token, axis.get("sketch"))
        return
    _cover(out, token, axis.get("sketch"))
    out.targets.append({"kind": "axis", "item": index, "entity": axis["entity"], "sketch_token": token,
                        "sketch": axis.get("sketch") or "", "axis": axis})


def _scan_hole(out, index, data):
    token = data.get("sketch_token")
    positions, points = data.get("positions"), data.get("point_tokens")
    if not token:
        return
    if not positions or not isinstance(points, list) or len(points) != len(positions) or not all(points):
        out.uncovered.add(token)
        out.note_name(token, data.get("sketch"))
        return
    _cover(out, token, data.get("sketch"))
    out.targets.append({"kind": "hole", "item": index, "sketch_token": token, "sketch": data.get("sketch") or "",
                        "positions": positions, "point_tokens": points})


FACE = OUTLINE_FACE


def outline_face(data):
    """The flat face record a step uses as its outline and that the probe can read again: the one face among its
    outlines, else the face a trimmed emboss is limited to (`translator.emboss.trimmed_face`). None when there is none,
    or it has no token, or its loops are not lines, arcs, circles and ellipses the translator writes."""
    faces = [p for p in data.get("profiles") or [] if isinstance(p, dict) and p.get("face")]
    record = faces[0] if len(faces) == 1 else (emboss.trimmed_face(data) if not faces else None)
    if (not isinstance(record, dict) or record.get("foreign") or not record.get("token")
            or not isinstance(record.get("frame"), dict) or not isinstance(record.get("loops"), list)):
        return None
    curves = [c for loop in record["loops"] for c in (loop.get("curves") or [])]
    if not curves or any(not isinstance(c, dict) or c.get("kind") not in _CURVES for c in curves):
        return None
    plain = {k: v for k, v in record.items() if k != "face"}
    return None if isinstance(profile_loops(plain), Refusal) else record


def _scan_face(out, index, data):
    """A flat face the step uses as its outline, keyed `keys.face`; `scan` names it after the step."""
    face = outline_face(data) if isinstance(index, int) else None
    if face is not None:
        out.targets.append({"kind": FACE, "item": index, "profile": face, "sketch_token": keys.face(index),
                            "sketch": "", "reference": {}})


_SCANNERS = {PROFILES: _scan_profiles, AXIS: _scan_axis, HOLE_POINTS: _scan_hole, PATH: _scan_path,
             OUTLINE_FACE: _scan_face}
