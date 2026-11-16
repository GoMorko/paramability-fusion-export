"""The checks of an extrude against what Fusion measured, as facts for any destination.

Where the measured end face lies against the sides (`end_check`, and `passes_box` for a face nearer than its side's
end), whether the side walls and the end face show the taper (`taper_problem`, `leans_problem`, `walls_confirm`), and
whether the volume of an extrude of text or free curves agrees with its outlines (`volume_problem`). The sides come
from `extrude.read_sides`; a `Problem` says why the extrude cannot be read or placed. Pure: it reads capture dicts only.
"""
import math
from dataclasses import dataclass, replace
from typing import Optional

from ...geometry import vec
from .extrude import (AT_END, ELSEWHERE, LEAN_TOL, LENGTH_TOL, SHORT, SYMMETRIC, TAPER_NO_CHANGE, TAPER_UNMEASURED,
                      TAPER_WAY, TAPER_WAY_UNMEASURED, THROUGH_BOTH, VOLUME_DIFFERS, VOLUME_UNMEASURED, SidePlan,
                      problem, sign_of)

AREA_RELATIVE_TOL = 1e-6
VOLUME_RELATIVE_TOL = 0.01
VOLUME_ABSOLUTE_TOL = 1e-3


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
