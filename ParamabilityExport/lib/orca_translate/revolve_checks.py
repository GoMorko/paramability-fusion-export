"""Checks of a revolve of several outlines, or of two halves, against the part, and the limits of its angle.

Orca stops the whole rebuild on a revolve cut that removes nothing, and it writes the revolves of one step one after
the other. So each revolve of a cut must meet the part as the revolves before it left it (`cut_order`), not only the
part before the step: outlines on the two sides of the axis turned a full circle make the same ring, and the second
cut would remove nothing. An outline whose whole turn lies inside what the outlines before it cut adds nothing to the
cut, so it is left out of the step with a note; that holds at other values only while its angle is a fixed number.

A join, a new body or an intersect of several outlines joins their turns. Orca joins shapes that overlap in a way the
copy cannot check, so outlines whose turns overlap leave such a step out (`overlap`).

`revolve_angle` follows a variable. Orca's revolve fails at an angle of 0 or below and over a full turn, and a cut
or intersect that a smaller angle moves off the part fails as well (`angle_floor`), so `tell_angle` puts how far the
variable may go on the parameter's line (`limits.tell`). When the floor cannot be told, the caller writes the angle
as a number.
"""
from ..orca_recipe.enums import FeatureType
from . import limits
from .solid import ADD, CUT, MEET_TOL, Solid, Turned

FULL_TURN_DEG = 360.0
HALF_TURN_DEG = 180.0
# Halvings toward the smallest angle at which a cut or intersect still works, and the angles then tested above it.
_HALVINGS = 10
_SAMPLES = 8
# Lines per side of a shape's box when the copy checks that nothing of it lies outside other shapes.
_LINES = 16
_AXES = ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])


def turns(part, plan, angle):
    """The shapes of the Orca revolves of `part`'s outline, in the order Orca makes them, each turned `angle`
    degrees: one turn from the plan's start, or the two halves of a symmetric turn."""
    if len(plan.flips) > 1:
        return [Turned(part.frame, part.loops, plan.point, plan.axis, angle, 0.0),
                Turned(part.frame, part.loops, plan.point, plan.axis, angle, -angle)]
    return [Turned(part.frame, part.loops, plan.point, plan.axis, angle, plan.start)]


def whole(part, plan, angle):
    """The shape of all revolves of `part` together."""
    if len(plan.flips) > 1:
        return Turned(part.frame, part.loops, plan.point, plan.axis, 2.0 * angle, -angle)
    return Turned(part.frame, part.loops, plan.point, plan.axis, angle, plan.start)


def within(tool, shapes):
    """True when no material of `tool` lies outside the shapes, along lines through the box of `tool`."""
    rest = Solid([(ADD, tool)] + [(CUT, s) for s in shapes])
    box = tool.bounds()
    for axis in range(3):
        others = [i for i in range(3) if i != axis]
        for a in _grid(box["min"][others[0]], box["max"][others[0]]):
            for b in _grid(box["min"][others[1]], box["max"][others[1]]):
                start = [0.0, 0.0, 0.0]
                start[others[0]], start[others[1]] = a, b
                if sum(t1 - t0 for t0, t1 in rest.material(start, _AXES[axis])) > MEET_TOL:
                    return False
    return True


def _grid(lo, hi):
    if hi - lo < 1e-9:
        return [(lo + hi) / 2.0]
    return [lo + (hi - lo) * (k + 0.5) / _LINES for k in range(_LINES)]


def _held(solid):
    held = Solid(list(solid.pieces))
    held.unsure = list(solid.unsure)
    return held


def cut_order(solid, parts, plan, angle, fixed):
    """`(parts to write, how many lie inside earlier cuts)` for a cut of `parts` from the body `solid` with each
    revolve turned `angle` degrees, or None when a revolve would remove nothing and the outline cannot be left out
    exactly. An outline whose whole turn lies inside what the outlines before it cut is left out only when the angle
    is `fixed` (a number): at another angle its turn can reach elsewhere."""
    held = _held(solid)
    done, kept, inside = [], [], 0
    for part in parts:
        shape = whole(part, plan, angle)
        if done and within(shape, done):
            if not fixed:
                return None
            inside += 1
            continue
        for piece in turns(part, plan, angle):
            if not held.meets(piece):
                return None
            held.add(CUT, piece)
        done.append(shape)
        kept.append(part)
    return kept, inside


def overlap(parts):
    """True when the turn of an outline shares material with the turn of an outline before it."""
    for n in range(1, len(parts)):
        if Solid([(ADD, p.shape) for p in parts[:n]]).meets(parts[n].shape, sure=False):
            return True
    return False


def _holds(solid, parts, plan, operation, angle):
    """True when the revolves of `parts`, each turned `angle` degrees, still work on the body `solid`: every cut
    removes material, one after the other, and an intersect meets it."""
    if operation == "cut":
        found = cut_order(solid, parts, plan, angle, False)
        return found is not None and len(found[0]) == len(parts)
    return any(solid.meets(whole(part, plan, angle)) for part in parts)


def angle_floor(solid, parts, plan, operation):
    """The smallest angle (degrees) of each revolve at which a cut or intersect of `parts` still works on the body
    `solid` (`_holds`), found by halving from the current angle; 0 for a join or new body or an angle that keeps its
    number. None when it cannot be told: the step does not hold at an angle tested between that floor and the largest
    angle (half a circle for two halves, a full circle else)."""
    if plan.angle.text is None or operation not in ("cut", "intersect"):
        return 0.0
    top = HALF_TURN_DEG if len(plan.flips) > 1 else FULL_TURN_DEG
    good, bad = plan.angle.n, 0.0
    if not _holds(solid, parts, plan, operation, good):
        return None
    for _ in range(_HALVINGS):
        middle = (good + bad) / 2.0
        if _holds(solid, parts, plan, operation, middle):
            good = middle
        else:
            bad = middle
    for k in range(1, _SAMPLES + 1):
        if not _holds(solid, parts, plan, operation, good + (top - good) * k / _SAMPLES):
            return None
    return good


def tell_angle(ctx, written, floor):
    """Put the limits of the variable that turns the revolves `written` on its parameter's line: each angle above
    `floor` (`angle_floor`) and at most a full circle."""
    fields = [(f, "revolve_angle") for f in written if f.type == FeatureType.REVOLVE and "revolve_angle" in f.expr]
    if fields:
        limits.tell(ctx, fields, lambda numbers: limits.stop(numbers[0] >= floor, limits.REVOLVE_MISSES)
                    and numbers[0] <= FULL_TURN_DEG)
