"""The sides of an extrude: the direction of each, how it ends and its length."""
import math

from .. import gap_hints, values, vec
from ..result import Refusal
from .common import LENGTH_TOL, SIGN_TOL, UNREADABLE, parallel, sign_of
from .reach import distance_quantity, keep_reaches_positive, reach_quantity
from .taper import taper_degrees, taper_quantity


def _fits(sign, rel_end, reach, other):
    """True when a face at `rel_end` can lie in an extrude that goes `reach` along `sign` and `other` the other way."""
    limit = reach if sign_of(rel_end) == sign else other
    return abs(rel_end) <= limit + LENGTH_TOL


def _choose_sign(ctx, geometric, rel_end, reach=None, other=None):
    """Direction (+1 along the sketch normal, -1 against it): the measured end face wins over the stored sign.

    A two sided extrude passes `reach` (this side) and `other` (the other side): its end faces lie on both sides, so
    the measured face turns the direction only when it fits the turned extrude and not the stored one."""
    if rel_end is None or abs(rel_end) < SIGN_TOL:
        return geometric
    measured = sign_of(rel_end)
    if measured != geometric and reach is not None and other is not None and (
            _fits(geometric, rel_end, reach, other) or not _fits(-geometric, rel_end, reach, other)):
        return geometric
    if measured != geometric:
        ctx.note("Fusion stored the extrude direction two ways; the measured end of the extrude was used.")
    return measured


def _reach_of(side):
    """How far a side of a two sided extrude can reach from the sketch plane, or None when that is not known here."""
    kind = (side or {}).get("kind")
    if kind == "distance" and isinstance(side.get("distance"), (int, float)):
        return abs(float(side["distance"]))
    return math.inf if kind in ("throughAll", "all") else None


def _is_through(side):
    return side is not None and side.get("kind") in ("throughAll", "all")


def _through_both(ctx, item, sides):
    """The plan of a cut through all both ways, or a Refusal when a side is tapered or its taper cannot be read.
    `sides` holds each side with the parameter path of its taper, which is pinned: a taper of zero cannot follow a
    size. A side recorded without a taper (older exports) has none."""
    for side, path in sides:
        taper = side.get("taper_deg", 0.0)
        if taper is None:
            return Refusal(UNREADABLE)
        if taper:
            return Refusal("A tapered cut through all both ways is not copied yet.", cause=gap_hints.TAPER_CUT_BOTH)
        values.pin(ctx, item, path, "a taper of zero cannot follow it")
    return [{"extent": "through", "sign": 1, "distance": None, "taper": 0.0}]


def plan_sides(item, data, frame, shift_q, combine, ctx, plane_q):
    """The sides to extrude, as dicts {extent, sign, distance, taper}; or a Refusal.

    `sign` is the travel direction relative to the sketch normal. extent is oneSide, symmetric or through. A distance
    side that carries `direction` (+1 or -1 along the sketch normal) travels that way instead of the measured end. One
    that carries `quantity` (a `values.Quantity`) writes that for its distance instead of a parameter's.
    """
    extent_type = data.get("extent_type", "one")
    if extent_type not in ("one", "two", "symmetric"):
        return Refusal("This extrude sets its length in a way that is not copied yet.")
    shift = shift_q.n
    rel_end = data.get("end_offset")
    if rel_end is not None:
        rel_end = rel_end - shift
    z = vec.unit(frame["z"])
    origin = vec.add(frame["origin"], vec.scale(z, shift))

    def one_side(side, which, forced_sign=None, measured=True, other=None):
        kind = (side or {}).get("kind")
        taper = taper_degrees(side.get("taper_deg", 0.0)) if side else 0.0
        if isinstance(taper, Refusal):
            return taper
        taper_q = None
        if kind in ("distance", "toEntity"):
            taper_q = taper_quantity(ctx, item, which + ".taper_deg", taper)
        end = rel_end if measured else None
        if kind == "distance":
            raw = float(side["distance"])
            if abs(raw) <= 0:
                return Refusal("This extrude has no length.")
            sign = forced_sign if forced_sign is not None else side.get("direction")
            if sign is None:
                sign = _choose_sign(ctx, sign_of(raw), end, abs(raw), other)
            return {"extent": "oneSide", "sign": sign, "distance": abs(raw), "taper": taper, "taper_q": taper_q,
                    "q": side.get("quantity") or distance_quantity(ctx, item, which + ".distance", raw)}
        if kind in ("throughAll", "all"):
            positive = side.get("positive", True)
            if positive is None:
                return Refusal(UNREADABLE)
            sign = forced_sign if forced_sign is not None else _choose_sign(
                ctx, 1 if positive else -1, end, math.inf, other)
            return {"extent": "through-one", "sign": sign, "distance": None, "taper": taper,
                    "taper_q": taper_quantity(ctx, item, which + ".taper_deg", taper), "adjusts": True}
        if kind == "toEntity":
            plane = side.get("plane")
            if not plane:
                return Refusal("This extrude ends on a surface that is not flat, which is not copied yet.",
                               cause=gap_hints.EXTRUDE_END_FACE)
            if not parallel(plane["normal"], z):
                return Refusal("This extrude ends on a tilted surface, which is not copied yet.",
                               cause=gap_hints.EXTRUDE_END_FACE)
            reach = vec.dot(vec.sub(plane["point"], origin), z)
            if abs(reach) < SIGN_TOL:
                return Refusal("This extrude ends on the surface it starts from.")
            sign = forced_sign if forced_sign is not None else _choose_sign(
                ctx, sign_of(reach), end, abs(reach), other)
            offset = side.get("offset", 0.0)
            if offset is None:
                return Refusal(UNREADABLE)
            values.pin(ctx, item, which + ".offset", "it sets how far %s reaches" % item.get("name", "a step"))
            distance = abs(reach) + float(offset)
            if not distance > 0:
                return Refusal("This extrude has no length.")
            return {"extent": "oneSide", "sign": sign, "distance": distance, "taper": taper,
                    "taper_q": taper_q, "adjusts": True, "reaches": True,
                    "q": reach_quantity(ctx, item, which, side, z, reach, offset, plane_q, shift_q)}
        return Refusal("This way of setting the extrude length is not copied yet.")

    if extent_type == "symmetric":
        side = data.get("side_one")
        if _is_through(side):
            return _through_both(ctx, item, [(side, "symmetric.taper_deg")])
        sym = data.get("symmetric")
        if not sym:
            return Refusal("This extrude has no readable length.")
        taper = taper_degrees(sym.get("taper_deg", 0.0))
        if isinstance(taper, Refusal):
            return taper
        full_length = sym.get("full_length", False)
        if full_length is None:
            return Refusal(UNREADABLE)
        factor = 1.0 if full_length else 2.0
        full = float(sym["distance"]) * factor
        if not abs(full) > 0:
            return Refusal("This extrude has no length.")
        half = distance_quantity(ctx, item, "symmetric.distance", float(sym["distance"]))
        return [{"extent": "symmetric", "sign": 1, "distance": abs(full), "taper": taper,
                 "taper_q": taper_quantity(ctx, item, "symmetric.taper_deg", taper),
                 "q": half.scaled(factor) if factor != 1.0 else half}]

    if extent_type == "two":
        one, two = data.get("side_one"), data.get("side_two")
        if one is None or two is None:
            return Refusal("This extrude has no readable length.")
        if _is_through(one) and _is_through(two):
            return _through_both(ctx, item, [(one, "side_one.taper_deg"), (two, "side_two.taper_deg")])
        if combine == "intersect":
            return Refusal("Two sided intersect extrudes are not copied yet.")
        first = one_side(one, "side_one", other=_reach_of(two))
        if isinstance(first, Refusal):
            return first
        second = one_side(two, "side_two", forced_sign=-first["sign"], measured=False)
        if isinstance(second, Refusal):
            return second
        keep_reaches_positive(ctx, item, [first, second])
        return [first, second]

    side = one_side(data.get("side_one"), "side_one")
    if isinstance(side, Refusal):
        return side
    keep_reaches_positive(ctx, item, [side])
    return [side]
