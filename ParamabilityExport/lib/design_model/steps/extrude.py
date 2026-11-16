"""The sides of an extrude, read from its capture record as facts for any destination.

An extrude starts on its sketch plane, at an offset from it, or on a flat face or plane square to its sketch normal
(`start_of`). From there each side goes along the sketch normal or against it (`read_sides`, one `SidePlan` per side):

- DISTANCE: a set length. Fusion stores it signed: a negative distance goes against the sketch normal.
- REACH: up to a flat face or plane square to the sketch normal (`Target`), plus Fusion's offset past it.
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

The checks against what Fusion measured are facts too: where the measured end face lies against the lengths
(`end_check`, and `passes_box` for a face nearer than its side's end), whether the side walls and the end face show the taper (`taper_problem`), and whether the volume of an
extrude of text or free curves agrees with its outlines (`volume_problem`). A `Problem` (`design_model/problem.py`)
says why the extrude cannot be read or placed, in one plain sentence, with its `code` below. Each destination decides what it copies from these facts.
Pure: it reads capture dicts only.
"""
import math
from dataclasses import dataclass, replace
from typing import Optional

from ...capture_model import gap_hints
from ...geometry import vec
from ...geometry.combine_volume import profile_area
from ..problem import Problem
from ..values import Quantity
from .. import words

DISTANCE, REACH, THROUGH, THROUGH_BOTH, SYMMETRIC = "distance", "reach", "through", "throughBoth", "symmetric"
SKETCH_PLANE, OFFSET, FACE = "sketchPlane", "offset", "face"
AT_END, SHORT, ELSEWHERE = "atEnd", "short", "elsewhere"

# Two lengths (mm) that agree within this are the same; an end face this near the start shows no direction.
LENGTH_TOL = 1e-3
# A face or plane this near (mm) to where the extrude starts gives it no length.
SIGN_TOL = 1e-9
PARALLEL_TOL = 1e-9
# Sine of a wall lean that counts as a taper: about 0.006 degrees.
LEAN_TOL = 1e-4
AREA_RELATIVE_TOL = 1e-6
VOLUME_RELATIVE_TOL = 0.01
VOLUME_ABSOLUTE_TOL = 1e-3
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

_THROUGH_KINDS = ("throughAll", "all")
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
    """A flat face or plane an extrude starts from or reaches to: its capture record (the `start`, `side_one` or
    `side_two` field), its plane (`point`, `normal`) and its signed distance (mm) along the unit sketch normal from
    where the extrude starts (from the sketch plane, for the start itself)."""
    record: dict
    plane: dict
    distance: float


@dataclass(frozen=True)
class Start:
    """Where an extrude starts: `kind` (SKETCH_PLANE, OFFSET or FACE) and `shift`, the signed distance (mm) along the
    unit sketch normal from the sketch plane. An OFFSET reads its parameter at `start.offset`; a FACE has its
    `target`."""
    kind: str
    shift: float
    target: Optional[Target] = None
    path: str = "start.offset"


@dataclass
class SidePlan:
    """One side of an extrude as Fusion made it.

    kind: DISTANCE, REACH, THROUGH, THROUGH_BOTH or SYMMETRIC. which: the capture field of the side (`side_one`,
    `side_two`, or `symmetric`), also the start of its parameter paths. sign: the travel along the sketch normal (+1
    along it, -1 against it; 1 for SYMMETRIC and THROUGH_BOTH). length: the length (mm) as a `Quantity` of the number
    (the full length for SYMMETRIC; None for through all). taper: Fusion's taper in degrees (positive widens the
    outline going away from the sketch). reach: the face or plane a REACH side ends on, and offset Fusion's offset past
    it. measured: the measured end face (mm along the sketch normal from the start), or None. stored: the direction
    Fusion stored, None when it stores none. fixed: the direction is given and no measure turns it (a face or plane
    gives it, or the step that wrote the side set it). value: the number Fusion stores at `path` for the length
    (signed for DISTANCE), and scale what it is multiplied by (2 for a symmetric extrude whose distance is half its
    length).
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


def start_of(data, frame):
    """Where the extrude starts (`Start`), or a Problem. A capture without a start (an older one) starts on the
    sketch plane. A start on a face or plane at a distance from it is a Problem: which way Fusion measures that
    distance is not read."""
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
        if held is not None and abs(held) > SIGN_TOL:
            return problem(START_OFFSET, "start")
        shift = vec.dot(vec.sub(plane["point"], frame["origin"]), z)
        return Start(FACE, shift, Target(start, plane, shift))
    return problem(START_KIND, "start")


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


def _side(data, side, which, origin, z, measured):
    """The SidePlan of one Fusion side with its stored direction as `sign` (None when it stores none), or a Problem."""
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
        return plane
    to = vec.dot(vec.sub(plane["point"], origin), z)
    if abs(to) < SIGN_TOL:
        return problem(ON_START, which)
    if "offset" in side and side["offset"] is None:
        return problem(UNREADABLE, which)
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


def read_sides(data, frame, shift=0.0):
    """The sides of the extrude in `data` as `SidePlan`s, or a Problem. `frame` is the sketch frame of its first
    outline and `shift` (mm) where it starts along the sketch normal from that sketch plane (`Start.shift`)."""
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
    plan = _side(data, side, "side_one", origin, z, measured)
    if isinstance(plan, Problem):
        return plan
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


# ---- what Fusion measured ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class EndCheck:
    """Where the measured end face lies against the sides: `fact` is AT_END (at the end of `side`), SHORT (on the
    side's way but nearer than its end, as for a cut that leaves the part before its end) or ELSEWHERE (on no side's
    way, or past its end). `side` is the side whose way the face lies on (None for ELSEWHERE on no side), `way` that
    way along the sketch normal (+1 or -1), `at` the face's distance from the start along it (mm), and `length` that
    side's length (half the length, for SYMMETRIC)."""
    fact: str
    side: Optional[SidePlan] = None
    way: int = 1
    at: float = 0.0
    length: float = 0.0


def end_check(sides):
    """The `EndCheck` of the measured end face against `sides` (from `read_sides`), or None when there is no measured
    end face or the side it lies on has no length (through all)."""
    if not sides or sides[0].measured is None:
        return None
    measured = sides[0].measured
    if sides[0].kind == SYMMETRIC:
        side, sign, length = sides[0], sign_of(measured), sides[0].length.n / 2.0
    elif len(sides) == 1:
        side, sign = sides[0], sides[0].sign
        length = None if side.length is None else side.length.n
    else:
        if abs(measured) <= LENGTH_TOL:
            return EndCheck(ELSEWHERE)
        side = next((s for s in sides if s.sign == sign_of(measured)), None)
        if side is None:
            return EndCheck(ELSEWHERE)
        sign, length = side.sign, None if side.length is None else side.length.n
    if length is None:
        return None
    at = measured * sign
    if abs(at - length) <= LENGTH_TOL:
        return EndCheck(AT_END, side, sign, at, length)
    if -LENGTH_TOL <= at < length:
        return EndCheck(SHORT, side, sign, at, length)
    return EndCheck(ELSEWHERE, side, sign, at, length)


def passes_box(box, start, z, way, length):
    """True when a side `length` (mm) long from `start` along the unit sketch normal `z` (against it for a negative
    `way`) ends past every corner of `box` (`{"min", "max"}`); False without a box.

    A side of a cut that ends past the part makes no end face of its own: the measured end face on that side is then a
    wall the cut went through, nearer than the side's end (SHORT in `end_check`). The measured face tells nothing about
    a side on the other side of the sketch, so only the side that the face lies on (`EndCheck.side`, `way` and
    `length`) can excuse a SHORT face."""
    if not box:
        return False
    lo, hi = box["min"], box["max"]
    corners = [[x, y, c] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for c in (lo[2], hi[2])]
    return length > max(way * vec.dot(vec.sub(corner, start), z) for corner in corners) + LENGTH_TOL


def _expected_leans(sides, operation):
    """Per side, the leans its walls can show along the sketch normal: a wall narrowing away from the sketch leans
    its outward normal along the travel; a cut shows the part's walls, which face the other way."""
    out = []
    for side in sides:
        lean = math.sin(math.radians(side.taper or 0.0)) * (1 if operation == "cut" else -1)
        out.append([-lean, lean] if side.kind in (SYMMETRIC, THROUGH_BOTH) else [side.sign * lean])
    return out


def leans_problem(sides, leans, operation):
    """A Problem when a measured wall (`leans`, the sine of each side wall's lean along the sketch normal) leans in a
    way no side gives, or a tapered side has no wall that shows its taper; else None. `operation` is Fusion's
    (`join`, `cut`, `intersect`, `newBody`)."""
    expected = _expected_leans(sides, operation)
    flat = [value for values in expected for value in values]
    if any(not any(abs(lean - value) <= LEAN_TOL for value in flat) for lean in leans):
        return problem(TAPER_WAY)
    for side, values in zip(sides, expected):
        if side.taper and not any(abs(lean - value) <= LEAN_TOL for lean in leans for value in values):
            return problem(TAPER_UNMEASURED)
    return None


def taper_problem(sides, data, operation, outlines):
    """A Problem when the taper of a side disagrees with the measured side walls (or, for one outline, the end face
    area), or cannot be measured; None when it agrees or no side is tapered. `outlines` is how many outlines the
    extrude takes."""
    if not any(side.taper for side in sides):
        return None
    leans = data.get("side_leans")
    if isinstance(leans, list) and leans:
        return leans_problem(sides, leans, operation)
    if not sides[0].taper or outlines != 1:
        return problem(TAPER_UNMEASURED)
    start, end = data.get("profile_area"), data.get("end_area")
    if not start or end is None or start <= 0:
        return problem(TAPER_WAY_UNMEASURED)
    if abs(end - start) <= AREA_RELATIVE_TOL * start:
        return problem(TAPER_NO_CHANGE)
    if (sides[0].taper < 0) != (end < start):
        return problem(TAPER_WAY)
    return None


def walls_confirm(side, leans, operation):
    """True when the measured walls (`leans`) of a tapered side lean as its direction gives, and not as the other
    direction gives: they then show which way Fusion went."""
    if not side.taper or not isinstance(leans, list) or not leans:
        return False
    turned = replace(side, sign=-side.sign)
    return leans_problem([side], leans, operation) is None and leans_problem([turned], leans, operation) is not None


def holds_free_outline(profiles):
    """True when a profile is sketch text or has a free curve (a spline)."""
    return any(p.get("text") or any(c.get("kind") == "other" for loop in p.get("loops") or []
                                    for c in loop.get("curves") or []) for p in profiles)


def volume_problem(data, sides, operation, profiles, thin):
    """A Problem when the volume Fusion made from text or spline outlines is not the outline area times the length.

    Text outlines are sorted into outer outlines and holes by the reader, and overlapping strokes can be read as a hole,
    so the area they give is checked against the measured volume. A new body must match; a join or cut may lose volume
    to material it overlaps, so it only must not exceed the expected volume or go the wrong way. Cases whose volume
    cannot be worked out here (taper, through all, thin, intersect) are not checked. A capture without the measured
    values (made before they were read) is not checked either."""
    if "areas" not in data or not holds_free_outline(profiles):
        return None
    if thin or operation == "intersect" or any(s.taper or s.length is None for s in sides):
        return None
    areas, before, after = data["areas"], data.get("volume_before"), data.get("volume_after")
    if (not isinstance(areas, list) or len(areas) != len(profiles) or any(a is None for a in areas)
            or before is None or after is None):
        return problem(VOLUME_UNMEASURED)
    expected = sum(areas) * sum(s.length.n for s in sides)
    change = after - before
    tolerance = VOLUME_RELATIVE_TOL * expected + VOLUME_ABSOLUTE_TOL
    if operation == "newBody":
        agrees = abs(change - expected) <= tolerance
    else:
        grows = operation == "join"
        agrees = abs(change) <= expected + tolerance and (change >= -VOLUME_ABSOLUTE_TOL if grows
                                                          else change <= VOLUME_ABSOLUTE_TOL)
    return None if agrees else problem(VOLUME_DIFFERS)
