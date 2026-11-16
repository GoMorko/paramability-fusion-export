"""The sides of an extrude, read from its capture record as facts for any destination.

An extrude starts on its sketch plane, at an offset from it, or on a flat face or plane square to its sketch normal
(`start_of`). From there each side goes along the sketch normal or against it (`read_sides`, one `SidePlan` per side):

- DISTANCE: a set length. Fusion stores it signed: a negative distance goes against the sketch normal.
- REACH: up to a flat face or plane square to the sketch normal (`Target`), plus Fusion's offset past it. Fusion can
  also stop at the faces next to a face (`chained`); such a side is read only when every outline lands on the face
  itself (`outline_on_face`), else it is a Problem (CHAINED).
- UP_TO: up to a tilted or curved face of the part (`Target` with its `face_point`, its plane None when curved). Only a
  caller that asks (`read_sides(..., faces=True)`) gets it, for one side; for any other caller such a face stays a
  Problem. Where Fusion may end it elsewhere than on the face (`_up_to`), every outline must land on the face.
- THROUGH: through all to one side.
- THROUGH_BOTH: through all both ways (a symmetric extrude through all, or two sides through all). There is one plan
  per Fusion side, for the taper of each.
- SYMMETRIC: one length centred on the start.

The direction of a side (`sign`, +1 along the sketch normal):

- One side with a distance or through all: the measured end face (`end_offset`) wins over the stored direction, since
  Fusion can store the direction two ways. A side that carries `direction` (a step written again as an extrude) goes
  that way. The legacy "all" extent stores no direction, so only a measured end face gives one.
- A side up to a face or plane goes to the side of the start that the face or plane lies on.
- Two sides: side two goes against side one. A face or plane of either side sets the direction. Else the stored
  direction of side one stands, and the measured end face turns it only when the face fits the turned sides and not
  the stored ones (the end face of a two sided extrude can lie on either side).

The checks against what Fusion measured (the end face, the taper, the volume) are in `extrude_checks.py`. A `Problem`
(`design_model/problem.py`) says why the extrude cannot be read or placed, in one plain sentence, with its `code`
below. Each destination decides what it copies from these facts.
Pure: it reads capture dicts only.
"""
import math
from dataclasses import dataclass
from typing import Optional

from ...capture_model import gap_hints
from ...geometry import region_inside, vec
from ...geometry.combine_volume import profile_area
from ..problem import Problem
from ..values import Quantity
from .. import words

DISTANCE, REACH, THROUGH, THROUGH_BOTH, SYMMETRIC = "distance", "reach", "through", "throughBoth", "symmetric"
UP_TO = "upTo"
SKETCH_PLANE, OFFSET, FACE = "sketchPlane", "offset", "face"
AT_END, SHORT, ELSEWHERE = "atEnd", "short", "elsewhere"

# Two lengths (mm) that agree within this are the same; an end face this near the start shows no direction.
LENGTH_TOL = 1e-3
# A face or plane this near (mm) to where the extrude starts gives it no length.
SIGN_TOL = 1e-9
PARALLEL_TOL = 1e-9
# Sine of a wall lean that counts as a taper: about 0.006 degrees.
LEAN_TOL = 1e-4
# A measured end face is an end cap when its area is an outline's area within this share plus this many mm2
# (`end_is_cap`). Fusion's face area and the area of the captured outline agree far closer; a face the extrude made
# that is not a cap (a wall it cut, a cap merged with a face of the part or partly in air) misses by more.
CAP_RELATIVE_TOL = 1e-3
CAP_ABSOLUTE_TOL = 1e-3
# A recorded end face normal is parallel to the sketch normal when the sine between them is at most this (the reader
# rounds unit vectors).
CAP_NORMAL_TOL = 1e-6

# Problem codes.
UNREADABLE = "unreadable"
EXTENT_KIND = "extentKind"
SIDE_KIND = "sideKind"
START_KIND = "startKind"
NO_LENGTH = "noLength"
NO_READABLE_LENGTH = "noReadableLength"
FOREIGN = "foreign"
NOT_FLAT = "notFlat"
TILTED = "tilted"
ON_START = "onStart"
SAME_SIDE = "sameSide"
START_OFFSET = "startOffset"
TAPER_WAY = "taperWay"
TAPER_UNMEASURED = "taperUnmeasured"
TAPER_WAY_UNMEASURED = "taperWayUnmeasured"
TAPER_NO_CHANGE = "taperNoChange"
VOLUME_UNMEASURED = "volumeUnmeasured"
VOLUME_DIFFERS = "volumeDiffers"
WAY_UNSURE = "wayUnsure"
CHAINED = "chained"
FACE_UNREAD = "faceUnread"
PAST_CURVED = "pastCurved"

_THROUGH_KINDS = ("throughAll", "all")
# The surfaces of a face record (`surface`, `read_geometry.surface_kind`) that are not flat.
CURVED_SURFACES = ("Cylinder", "Cone", "other")
# What a face or plane is to the extrude, by the capture field that holds it.
_SLOT_WORDS = {"start": "starts from", "side_one": "ends on", "side_two": "ends on"}


_WORDS = {
    UNREADABLE: (words.EXTRUDE_UNREADABLE, None),
    EXTENT_KIND: (words.EXTRUDE_EXTENT_KIND, None),
    SIDE_KIND: (words.EXTRUDE_SIDE_KIND, None),
    START_KIND: (words.EXTRUDE_START_KIND, None),
    NO_LENGTH: (words.EXTRUDE_NO_LENGTH, None),
    NO_READABLE_LENGTH: (words.EXTRUDE_NO_READABLE_LENGTH, None),
    FOREIGN: (words.EXTRUDE_FOREIGN, gap_hints.OTHER_COMPONENT),
    NOT_FLAT: (words.EXTRUDE_NOT_FLAT, gap_hints.EXTRUDE_END_FACE),
    TILTED: (words.EXTRUDE_TILTED, gap_hints.EXTRUDE_END_FACE),
    ON_START: (words.EXTRUDE_ON_START, None),
    SAME_SIDE: (words.EXTRUDE_SAME_SIDE, gap_hints.EXTRUDE_END_FACE),
    START_OFFSET: (words.EXTRUDE_START_OFFSET, gap_hints.EXTRUDE_END_FACE),
    TAPER_WAY: (words.TAPER_WAY, None),
    TAPER_UNMEASURED: (words.TAPER_UNMEASURED, None),
    TAPER_WAY_UNMEASURED: (words.TAPER_WAY_UNMEASURED, None),
    TAPER_NO_CHANGE: (words.TAPER_NO_CHANGE, None),
    VOLUME_UNMEASURED: (words.VOLUME_UNMEASURED, None),
    VOLUME_DIFFERS: (words.VOLUME_DIFFERS, None),
    WAY_UNSURE: (words.EXTRUDE_WAY_UNSURE, None),
    CHAINED: (words.EXTRUDE_CHAINED, gap_hints.EXTRUDE_END_FACE),
    FACE_UNREAD: (words.EXTRUDE_FACE_UNREAD, gap_hints.EXTRUDE_END_FACE),
    PAST_CURVED: (words.EXTRUDE_PAST_CURVED, gap_hints.EXTRUDE_END_FACE),
}


def problem(code, slot=None):
    """The `Problem` of `code` (`design_model/problem.py`), worded for the capture field `slot` (`start`, `side_one`,
    `side_two`) when its sentence names one."""
    text, cause = _WORDS[code]
    if "%s" in text:
        text = text % _SLOT_WORDS.get(slot, "ends on")
    return Problem(code, text, cause)


def sign_of(value):
    return -1 if value < 0 else 1


def parallel(a, b):
    return vec.length(vec.cross(vec.unit(a), vec.unit(b))) <= PARALLEL_TOL


@dataclass(frozen=True)
class Target:
    """A face or plane an extrude starts from or reaches to: its capture record (the `start`, `side_one` or
    `side_two` field), its plane (`point`, `normal`; None for the curved face of an UP_TO side) and its signed
    distance (mm) along the unit sketch normal from where the extrude starts (from the sketch plane, for the start
    itself). For an UP_TO side the distance is the one of its `face_point`."""
    record: dict
    plane: dict
    distance: float


@dataclass(frozen=True)
class Start:
    """Where an extrude starts: `kind` (SKETCH_PLANE, OFFSET or FACE) and `shift`, the signed distance (mm) along the
    unit sketch normal from the sketch plane. An OFFSET reads its parameter at `start.offset`; a FACE has its
    `target`, and `offset` is how far (mm, along the sketch normal) it starts from that face: Fusion's `start.offset`
    times `way`, the sign that puts the start where Fusion measured it (0 without an offset)."""
    kind: str
    shift: float
    target: Optional[Target] = None
    path: str = "start.offset"
    offset: float = 0.0
    way: int = 1


@dataclass
class SidePlan:
    """One side of an extrude as Fusion made it.

    kind: DISTANCE, REACH, UP_TO, THROUGH, THROUGH_BOTH or SYMMETRIC. which: the capture field of the side
    (`side_one`, `side_two`, or `symmetric`), also the start of its parameter paths. sign: the travel along the sketch
    normal (+1 along it, -1 against it; 1 for SYMMETRIC and THROUGH_BOTH). length: the length (mm) as a `Quantity` of
    the number (the full length for SYMMETRIC; None for through all and UP_TO). taper: Fusion's taper in degrees
    (positive widens the outline going away from the sketch). reach: the face or plane a REACH or UP_TO side ends on,
    and offset Fusion's offset past it. measured: the measured end face (mm along the sketch normal from the start),
    or None. stored: the direction Fusion stored, None when it stores none. fixed: the direction is given and no
    measure turns it (a face or plane gives it, or the step that wrote the side set it). value: the number Fusion
    stores at `path` for the length (signed for DISTANCE), and scale what it is multiplied by (2 for a symmetric
    extrude whose distance is half its length).
    """
    kind: str
    which: str
    sign: int
    length: Optional[Quantity]
    taper: float
    reach: Optional[Target] = None
    offset: float = 0.0
    measured: Optional[float] = None
    stored: Optional[int] = None
    fixed: bool = False
    value: Optional[float] = None
    scale: float = 1.0

    @property
    def path(self):
        """The parameter path of the stored length."""
        return self.which + ".distance"

    @property
    def taper_path(self):
        return self.which + ".taper_deg"

    @property
    def offset_path(self):
        return self.which + ".offset"

    @property
    def turned(self):
        """True when the measured end face turned the direction Fusion stored."""
        return self.stored is not None and self.sign != self.stored


# ---- the start ---------------------------------------------------------------------------------------------------

def _plane_of(record, z, slot):
    """The plane of a face or plane square to the unit sketch normal `z`, or a Problem."""
    if record.get("foreign"):
        return problem(FOREIGN, slot)
    plane = record.get("plane")
    if not isinstance(plane, dict) or not plane.get("point") or not plane.get("normal"):
        return problem(NOT_FLAT, slot)
    if not parallel(plane["normal"], z):
        return problem(TILTED, slot)
    return plane


def _param_value(data, path):
    held = (data.get("params") or {}).get(path)
    return float(held.get("value") or 0.0) if isinstance(held, dict) else None


def _offset_start(data, record, plane, shift, offset):
    """The `Start` at `offset` (mm, Fusion's `start.offset`) from the face or plane `record` that lies `shift` along
    the sketch normal, or a Problem. Fusion measures the offset along the face normal, whose direction the reader does
    not read; the measured start face (`start_offset`) decides. Exactly one sign must put the start there."""
    measured = data.get("start_offset")
    if not _number(measured):
        return problem(START_OFFSET, "start")
    fits = [way for way in (1, -1) if abs(shift + way * offset - measured) <= LENGTH_TOL]
    if len(fits) != 1:
        return problem(START_OFFSET, "start")
    return Start(FACE, shift + fits[0] * offset, Target(record, plane, shift), offset=fits[0] * offset, way=fits[0])


def start_of(data, frame, offsets=False):
    """Where the extrude starts (`Start`), or a Problem. A capture without a start (an older one) starts on the
    sketch plane. A start on a face or plane at a distance from it is a Problem, unless the caller asks for `offsets`:
    then the measured start face decides which way the distance goes (`_offset_start`)."""
    if "start" not in data:
        return Start(SKETCH_PLANE, 0.0)
    start = data["start"]
    if not isinstance(start, dict):
        return problem(UNREADABLE, "start")
    kind = start.get("kind", "profilePlane")
    if kind == "profilePlane":
        return Start(SKETCH_PLANE, 0.0)
    if kind == "offset":
        if start.get("offset") is None:
            return problem(UNREADABLE, "start")
        return Start(OFFSET, float(start["offset"]))
    if kind == "fromEntity":
        z = vec.unit(frame["z"])
        plane = _plane_of(start, z, "start")
        if isinstance(plane, Problem):
            return plane
        held = _param_value(data, "start.offset")
        shift = vec.dot(vec.sub(plane["point"], frame["origin"]), z)
        if held is not None and abs(held) > SIGN_TOL:
            return _offset_start(data, start, plane, shift, held) if offsets else problem(START_OFFSET, "start")
        return Start(FACE, shift, Target(start, plane, shift))
    return problem(START_KIND, "start")


# ---- a face chained to the faces next to it -------------------------------------------------------------------

# A point this near (mm) to the boundary of a face or an outline counts as on it.
ON_FACE_TOL = 1e-3


def joins_next_faces(record):
    """True when Fusion may also stop the extrude at the faces next to the face `record` (`chained` true or not read),
    instead of extending the face to its whole surface. Only a face can be chained; a construction plane cannot."""
    return record.get("entity_type") == "BRepFace" and record.get("chained") is not False


def _along(p, z, frame):
    """`p` moved along the unit direction `z` onto the plane of `frame`, in that frame's own coordinates; None when
    `z` lies in the plane."""
    normal = vec.unit(frame["z"])
    across = vec.dot(z, normal)
    if abs(across) < PARALLEL_TOL:
        return None
    on = vec.add(p, vec.scale(z, vec.dot(vec.sub(frame["origin"], p), normal) / across))
    return vec.frame_to_local(frame, on)[:2]


def outline_on_face(data, record, z):
    """Whether every outline of the extrude in `data`, moved along the unit sketch normal `z`, lands on the flat face
    `record` (its `face_outline`, `read_face.face_loops` at the step): True, False, or None when it cannot be told (no
    face outline, an outline without loops or with a curve that does not read, or a face along `z`).

    The face's loops are moved along `z` into the sketch plane of each outline, and the outline must lie in the face
    region (outer loop less its holes) within `ON_FACE_TOL`: no edge of the face may cross it, and no hole of the face
    may lie under it (`region_inside.inside`). Then the extrude ends on that face alone, whether Fusion extends it or
    also takes the faces next to it."""
    face = record.get("face_outline")
    profiles = data.get("profiles") or []
    if not isinstance(face, dict) or not isinstance(face.get("frame"), dict) or not face.get("loops") or not profiles:
        return None
    exact = parallel(face["frame"]["z"], z)
    for profile in profiles:
        if not isinstance(profile, dict) or not isinstance(profile.get("frame"), dict) or not profile.get("loops"):
            return None
        frame = profile["frame"]
        try:
            loops = region_inside.moved_loops(
                face["loops"], lambda uv: _along(vec.frame_apply(face["frame"], [uv[0], uv[1], 0.0]), z, frame), exact)
            if loops is None:
                return None
            if not region_inside.inside(profile["loops"], loops, ON_FACE_TOL):
                return False
        except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError):
            return None
    return True


# ---- the sides ---------------------------------------------------------------------------------------------------

def taper_of(data, side, which):
    """Fusion's taper of a side in degrees, or None when it cannot be read. A side that reaches to a face keeps its
    taper in its parameter (`<which>.taper_deg`) only. Without an angle anywhere, the measured side walls (or, without
    them, the end face area) must show no taper."""
    if "taper_deg" in (side or {}):
        return side["taper_deg"]
    held = _param_value(data, which + ".taper_deg")
    if held is not None:
        return held
    leans = data.get("side_leans")
    if isinstance(leans, list) and leans:
        return None if any(not isinstance(n, (int, float)) or abs(n) > LEAN_TOL for n in leans) else 0.0
    start, end = data.get("profile_area"), data.get("end_area")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and abs(end - start) > 1e-6 * abs(start):
        return None
    return 0.0


def _through(side):
    return isinstance(side, dict) and side.get("kind") in _THROUGH_KINDS


def _up_to(data, side, which, origin, z, taper, found):
    """The UP_TO SidePlan of a side whose face is tilted or curved, or a Problem. The side goes toward the face's
    point (`face_point`). The record must be a face of the part with that point, else the Problem `found` stands.

    The app extends a flat face to its whole plane and takes a curved face as it is, so the outline must land on the
    face itself where Fusion may end the extrude elsewhere: on the faces next to the face (Chain Faces on, `chained`
    not false), or on the surface of a curved face extended past its edges (Chain Faces off). A tilted flat face
    is checked by its outline (`outline_on_face`); a curved face with Chain Faces on has no outline, and one with Chain
    Faces off needs the reader's rays (`outline_hits_face`). A face without a plane whose surface is flat or unknown
    is a Problem: it may be a flat face whose plane did not read."""
    point = side.get("face_point")
    if side.get("entity_type") != "BRepFace" or not (isinstance(point, list) and len(point) == 3
                                                     and all(_number(n) for n in point)):
        return found
    to = vec.dot(vec.sub(point, origin), z)
    if abs(to) < SIGN_TOL:
        return problem(ON_START, which)
    if "offset" in side and side["offset"] is None:
        return problem(UNREADABLE, which)
    if found.code == TILTED:
        plane = side.get("plane")
        if joins_next_faces(side) and outline_on_face(data, side, z) is not True:
            return problem(CHAINED, which)
    else:
        plane = None
        if side.get("surface") not in CURVED_SURFACES:
            return problem(FACE_UNREAD, which)
        if joins_next_faces(side):
            return problem(CHAINED, which)
        if side.get("outline_hits_face") is not True:
            return problem(PAST_CURVED, which)
    return SidePlan(UP_TO, which, sign_of(to), None, taper, Target(side, plane, to), float(side.get("offset", 0.0)),
                    stored=sign_of(to), fixed=True)


def _side(data, side, which, origin, z, measured, faces=False):
    """The SidePlan of one Fusion side with its stored direction as `sign` (None when it stores none), or a Problem.
    With `faces`, a side up to a tilted or curved face of the part is an UP_TO side (`_up_to`)."""
    kind = side.get("kind")
    if kind not in ("distance", "toEntity") + _THROUGH_KINDS:
        return problem(SIDE_KIND, which)
    taper = taper_of(data, side, which)
    if taper is None:
        return problem(UNREADABLE, which)
    if kind == "distance":
        if not isinstance(side.get("distance"), (int, float)):
            return problem(UNREADABLE, which)
        raw = float(side["distance"])
        if raw == 0:
            return problem(NO_LENGTH, which)
        fixed = side.get("direction") in (1, -1)
        stored = side["direction"] if fixed else sign_of(raw)
        return SidePlan(DISTANCE, which, stored, Quantity(abs(raw)), taper, measured=measured, stored=stored,
                        fixed=fixed, value=raw)
    if kind in _THROUGH_KINDS:
        positive = side.get("positive", True) if kind == "throughAll" else None
        if kind == "throughAll" and positive is None:
            return problem(UNREADABLE, which)
        stored = None if positive is None else (1 if positive else -1)
        return SidePlan(THROUGH, which, stored, None, taper, measured=measured, stored=stored)
    plane = _plane_of(side, z, which)
    if isinstance(plane, Problem):
        if faces and plane.code in (NOT_FLAT, TILTED):
            return _up_to(data, side, which, origin, z, taper, plane)
        return plane
    to = vec.dot(vec.sub(plane["point"], origin), z)
    if abs(to) < SIGN_TOL:
        return problem(ON_START, which)
    if "offset" in side and side["offset"] is None:
        return problem(UNREADABLE, which)
    if joins_next_faces(side) and outline_on_face(data, side, z) is not True:
        return problem(CHAINED, which)
    offset = float(side.get("offset", 0.0))
    length = abs(to) + offset
    if not length > 0:
        return problem(NO_LENGTH, which)
    return SidePlan(REACH, which, sign_of(to), Quantity(length), taper, Target(side, plane, to), offset,
                    measured=measured, stored=sign_of(to), fixed=True)


def _reach_limit(plan):
    """How far a side can reach from the start (mm): its length, or no limit through all."""
    return math.inf if plan.length is None else plan.length.n


def _fits(sign, measured, reach, other):
    """True when an end face at `measured` can lie in an extrude that goes `reach` along `sign` and `other` the other
    way."""
    limit = reach if sign_of(measured) == sign else other
    return abs(measured) <= limit + LENGTH_TOL


def _one_way(plan):
    """The direction of the only side of an extrude: a face or plane, a set `direction`, else the measured end face
    over the stored direction. None when none of them gives one."""
    if plan.fixed:
        return plan.stored
    if plan.measured is not None and abs(plan.measured) > LENGTH_TOL:
        return sign_of(plan.measured)
    return plan.stored


def _two_ways(first, second):
    """The direction of side one of a two sided extrude; None when nothing gives one."""
    if first.fixed:
        return first.stored
    if second.kind == REACH:
        return -second.stored
    stored, measured = first.stored, first.measured
    if measured is None or abs(measured) <= LENGTH_TOL:
        return stored
    found = sign_of(measured)
    if stored is None or found == stored:
        return found
    reach, other = _reach_limit(first), _reach_limit(second)
    if _fits(stored, measured, reach, other) or not _fits(-stored, measured, reach, other):
        return stored
    return found


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _tapered(data):
    """True when a side of the extrude may be tapered (a taper angle that is not zero or cannot be read)."""
    for slot in ("side_one", "side_two", "symmetric"):
        side = data.get(slot)
        if isinstance(side, dict) and "taper_deg" in side and side["taper_deg"] != 0:
            return True
    return any(path.endswith(".taper_deg") and (not isinstance(held, dict) or held.get("value"))
               for path, held in (data.get("params") or {}).items())


def end_is_cap(data, z):
    """Whether the measured end face (`endFaces[0]`, `end_offset`) is an end cap of the extrude: True, False, or None
    when the capture cannot tell.

    Fusion can list a face that is not a cap first, such as a wall that a cut made where it went through a rib of the
    part. Such a face lies anywhere on the extrude's way and tells nothing about its length or direction. A face whose
    normal the reader recorded (`end_normal`) is a cap when that normal is parallel to the unit sketch normal `z`.
    Without it, the face is a cap when its area (`end_area`) is the area of an outline, or of all outlines together,
    within `CAP_RELATIVE_TOL` and `CAP_ABSOLUTE_TOL`. A tapered or thin extrude has caps of other areas, and an outline
    whose area cannot be worked out (text, free curves) gives no area to compare: both are None."""
    normal = data.get("end_normal")
    if isinstance(normal, list) and len(normal) == 3 and all(_number(n) for n in normal) and vec.length(normal) > 0:
        return vec.length(vec.cross(vec.unit(normal), z)) <= CAP_NORMAL_TOL
    end = data.get("end_area")
    if not _number(end) or data.get("thin") or _tapered(data):
        return None
    profiles = data.get("profiles") or []
    listed = data.get("areas") if isinstance(data.get("areas"), list) else []
    areas = []
    for n, profile in enumerate(profiles):
        area = profile_area(profile) if isinstance(profile, dict) else None
        if area is None and n < len(listed) and _number(listed[n]):
            area = float(listed[n])
        if area is None and n == 0 and _number(data.get("profile_area")):
            area = float(data["profile_area"])
        if area is None or area <= 0:
            return None
        areas.append(area)
    if not areas:
        return None
    candidates = areas + ([sum(areas)] if len(areas) > 1 else [])
    return any(abs(end - area) <= CAP_RELATIVE_TOL * area + CAP_ABSOLUTE_TOL for area in candidates)


def read_sides(data, frame, shift=0.0, faces=False):
    """The sides of the extrude in `data` as `SidePlan`s, or a Problem. `frame` is the sketch frame of its first
    outline and `shift` (mm) where it starts along the sketch normal from that sketch plane (`Start.shift`).

    With `faces`, one side up to a tilted or curved face of the part is an UP_TO side. A curved face can lie on both
    sides of the sketch, so its direction must agree with the measured end face (`end_offset`, a face on the curved
    face, which is no end cap); else the direction is a Problem (WAY_UNSURE). A flat face reaches the sketch normal
    on one side only."""
    extent = data.get("extent_type", "one")
    if extent not in ("one", "two", "symmetric"):
        return problem(EXTENT_KIND)
    z = vec.unit(frame["z"])
    measured = data.get("end_offset")
    # A face that is not an end cap is no measure: the stored direction and length stand (`end_is_cap`).
    not_cap = measured is not None and end_is_cap(data, z) is False
    if measured is not None:
        measured = None if not_cap else measured - shift
    origin = vec.add(frame["origin"], vec.scale(z, shift))

    if extent == "symmetric":
        side = data.get("side_one")
        if _through(side):
            taper = taper_of(data, side, "symmetric")
            if taper is None:
                return problem(UNREADABLE, "symmetric")
            return [SidePlan(THROUGH_BOTH, "symmetric", 1, None, taper)]
        sym = data.get("symmetric")
        if not isinstance(sym, dict) or not isinstance(sym.get("distance"), (int, float)):
            return problem(NO_READABLE_LENGTH)
        taper = taper_of(data, sym, "symmetric")
        if taper is None or sym.get("full_length") is None:
            return problem(UNREADABLE, "symmetric")
        value = float(sym["distance"])
        scale = 1.0 if sym["full_length"] else 2.0
        if not abs(value) * scale > 0:
            return problem(NO_LENGTH)
        return [SidePlan(SYMMETRIC, "symmetric", 1, Quantity(abs(value) * scale), taper, measured=measured,
                         value=value, scale=scale)]

    if extent == "two":
        one, two = data.get("side_one"), data.get("side_two")
        if not isinstance(one, dict) or not isinstance(two, dict):
            return problem(NO_READABLE_LENGTH)
        if _through(one) and _through(two):
            plans = []
            for side, which in ((one, "side_one"), (two, "side_two")):
                taper = taper_of(data, side, which)
                if taper is None:
                    return problem(UNREADABLE, which)
                plans.append(SidePlan(THROUGH_BOTH, which, 1, None, taper))
            return plans
        first = _side(data, one, "side_one", origin, z, measured)
        if isinstance(first, Problem):
            return first
        second = _side(data, two, "side_two", origin, z, measured)
        if isinstance(second, Problem):
            return second
        sign = _two_ways(first, second)
        if sign is None:
            return problem(UNREADABLE, "side_one")
        for plan, way in ((first, sign), (second, -sign)):
            if plan.kind == REACH and plan.stored != way:
                return problem(SAME_SIDE, plan.which)
        first.sign = sign
        second.sign, second.stored = -sign, -sign
        return [first, second]

    side = data.get("side_one")
    if not isinstance(side, dict):
        return problem(NO_READABLE_LENGTH)
    plan = _side(data, side, "side_one", origin, z, measured, faces)
    if isinstance(plan, Problem):
        return plan
    if plan.kind == UP_TO and plan.reach.plane is None:
        raw = data.get("end_offset")
        if not _number(raw) or abs(raw - shift) <= LENGTH_TOL or sign_of(raw - shift) != plan.sign:
            return problem(WAY_UNSURE, "side_one")
    if not_cap and not plan.fixed and abs(data["end_offset"] - shift) > LENGTH_TOL and (
            plan.stored is None or sign_of(data["end_offset"] - shift) != plan.stored):
        # Fusion can store the direction of one side two ways, and the measured end face would decide it, but that
        # face is not an end cap: the direction is not known for sure.
        return problem(WAY_UNSURE, "side_one")
    sign = _one_way(plan)
    if sign is None:
        return problem(UNREADABLE, "side_one")
    plan.sign = sign
    return [plan]
