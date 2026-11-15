"""The values of a coil step: how its diameter, section size, height, pitch and revolutions follow the sizes.

A coil's parameters rule the wire's size (`SectionSize`), where it sits (`Diameter`, with the wire inside, on or outside
that diameter) and the rise (`Revolutions` with `Height` or `Pitch`, or `Height` with `Pitch`). Fusion does not say how
they combine, so each formula is tried against what was measured and written only when it gives the measured number.
A value that matches no formula stays a number and marks the sizes behind it.
"""
from .. import values
from ..ranges import kept_ranges
from ..values import Quantity
from . import coil_limits as limits

# Where the wire sits against the diameter, as a multiple of its half size: inside, on, and outside the diameter.
POSITIONS = (-1.0, 0.0, 1.0)
# The room (mm, or turns) the guards keep: the wire from the axis, a turn from the next, the turns from their cap.
GUARD_MM = 0.01


def _same(measured, found):
    return abs(found - measured) <= limits.LEN_TOL + limits.REL_TOL * abs(measured)


def _plain(ctx, reads, why):
    """The sizes in `reads` cannot follow a value: mark them."""
    if reads:
        ctx.doubt(reads, why)


class Section:
    """The wire as the values see it: `size` is the Quantity of the section size and `half` that of half its size, both
    None when the section does not follow a size; `axial` is the wire's height along the axis."""

    def __init__(self, size=None, half=None, axial=None):
        self.size, self.half, self.axial = size, half, axial


def section_values(ctx, item, params, shape, loop, axial_mm):
    """The `Section` of the wire (`shape` is circle, square or other) and the written size of its loop."""
    ref = params.get("section_size")
    if ref is None or shape == "other":
        if ref is not None:
            values.pin(ctx, item, "section_size", "the wire of %s is not a plain round or square one" % item.get("name", "a coil"))
        return Section(axial=Quantity(axial_mm))
    measured = loop["radius"] * 2.0 if shape == "circle" else loop["width"]
    if not _same(measured, ref["value"]):
        values.pin(ctx, item, "section_size", "its size in %s does not match the wire Fusion made" % item.get("name", "a coil"))
        return Section(axial=Quantity(axial_mm))
    size = values.quantity(ctx, item, "section_size", ref["value"], absolute=True)
    return Section(size, size.scaled(0.5), size)


def rho_value(ctx, item, params, section, rho_mm):
    """The Quantity of the distance from the axis to the wire's centre."""
    ref = params.get("diameter")
    if ref is None:
        return Quantity(rho_mm)
    if section.half is None:
        values.pin(ctx, item, "diameter", "the wire of %s is not a plain round or square one" % item.get("name", "a coil"))
        return Quantity(rho_mm)
    half = section.half.n
    for place in POSITIONS:
        if _same(rho_mm, ref["value"] / 2.0 + place * half):
            diameter = values.quantity(ctx, item, "diameter", ref["value"], absolute=True)
            return diameter.scaled(0.5).plus(section.half.scaled(place)) if place else diameter.scaled(0.5)
    values.pin(ctx, item, "diameter", "the wire of %s sits in a place the copy cannot follow" % item.get("name", "a coil"))
    return Quantity(rho_mm)


def _rise_value(ctx, item, params, section, rise_mm):
    """The Quantity of the rise of the helix from the `height` parameter, or None when no formula gives the measured
    rise (the sizes behind it are marked)."""
    ref = params["height"]
    sign = -1 if ref["value"] < 0 else 1
    found = values.quantity(ctx, item, "height", abs(ref["value"]), sign=sign, absolute=True)
    wire = section.axial
    for candidate in (found, found.plus(wire.scaled(-1.0)), found.plus(wire)):
        if _same(rise_mm, candidate.n):
            return candidate
    _plain(ctx, found.reads, "its height in %s is not the rise of the coil Fusion made" % item.get("name", "a coil"))
    return None


def rise_values(ctx, item, params, kind, section, rise_mm, pitch_mm, turns_mm):
    """`(pitch, turns)` Quantities of the helix. `kind` is revolutions_height, revolutions_pitch or height_pitch."""
    name = item.get("name", "a coil")
    if kind == "revolutions_pitch":
        ref = params["pitch"]
        pitch = values.quantity(ctx, item, "pitch", abs(ref["value"]), sign=-1 if ref["value"] < 0 else 1, absolute=True)
        turns = values.quantity(ctx, item, "revolutions", turns_mm, dim="scalar", absolute=True)
        return pitch, turns
    if kind == "revolutions_height":
        turns = values.quantity(ctx, item, "revolutions", turns_mm, dim="scalar", absolute=True)
        rise = _rise_value(ctx, item, params, section, rise_mm)
        if rise is None:
            return _fixed_rise(ctx, name, Quantity(pitch_mm), Quantity(turns_mm), turns.reads)
        return rise.divided_by(turns), turns
    ref = params["pitch"]
    pitch = values.quantity(ctx, item, "pitch", abs(ref["value"]), sign=-1 if ref["value"] < 0 else 1, absolute=True)
    rise = _rise_value(ctx, item, params, section, rise_mm)
    if rise is None:
        return _fixed_rise(ctx, name, Quantity(pitch_mm), Quantity(turns_mm), pitch.reads)
    return pitch, rise.divided_by(pitch)


def _fixed_rise(ctx, name, pitch, turns, reads):
    """`(pitch, turns)` as plain numbers: the height gives no formula for the rise, so following only one of the two
    would change the rise when its size moves, where Fusion keeps the height. The sizes of the other value are marked."""
    _plain(ctx, reads, "the rise of %s is set by a height that its other values do not explain" % name)
    return pitch, turns


def keep_inside_ranges(ctx, item, section, rho, pitch, turns, axial_mm, turns_left):
    """`(section, rho, pitch, turns)` that hold at every size setting. The wire must clear the axis, the turns must stay
    apart and they must not pass what is left of the recipe's turns: the ranges of the sizes are cut to the values where
    all three hold. When no cut keeps them, every value is a plain number and its sizes are marked."""
    name = item.get("name", "a coil")
    rules = []
    if section.half is not None and rho.sized:
        rules.append(rho.plus(section.half.scaled(-1.0)))
    if pitch.sized or section.size is not None:
        rules.append(pitch.plus(section.axial.scaled(-1.0)))
    if turns.sized:
        rules.append(Quantity(turns_left).plus(turns.scaled(-1.0)))
    rules = [q for q in rules if q.sized]
    if not rules or ctx.table is None:
        return section, rho, pitch, turns
    why = ("%s needs its wire clear of the axis, its turns apart and at most %d turns of coils and threads in all"
           % (name, limits.MAX_TURNS_TOTAL))
    found = kept_ranges.holding_ranges(ctx.table, [(q, 1) for q in rules], GUARD_MM)
    if found:
        ctx.cut(found, why)
    elif found is None:
        reads = rho.reads + pitch.reads + turns.reads + (section.size.reads if section.size is not None else ())
        ctx.doubt(tuple(dict.fromkeys(reads)), why)
        return Section(axial=Quantity(axial_mm)), Quantity(rho.n), Quantity(pitch.n), Quantity(turns.n)
    return section, rho, pitch, turns
