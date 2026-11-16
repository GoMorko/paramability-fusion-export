"""Modeled threads as Orca threads: a ThreadFeature on a cylinder face, and the thread of a tapped hole.

Orca's thread (with `thread_major_nominal`) cuts a V groove along a right hand helix: `thread_radius` is half the
major diameter, `thread_depth` half the difference of the major and minor diameters, `thread_height` its length from
its plane along the plane normal, `thread_x` and `thread_y` its axis on that plane. An outside thread cuts the groove
into the rod; an inside thread bores to the minor diameter and cuts the groove out to the major one. The groove is
Orca's own V, reaching about 0.42 of a pitch along the axis on each side of its helix, so the profile can differ a
little from Fusion's.

A groove that runs out through an end face of the part did not always build in Orca 2.5.1: about one in four such
threads removed nothing, or less than it should, depending on where the helix starts; starting or stopping it a pitch
outside the part failed as often. Every thread that stays inside the part built. So the Orca thread starts and stops
`INSET` of a pitch inside each end of Fusion's thread, and each end is judged from the part the copy built (`_end`):
- Closed (the part goes on past the end all round the thread's ring: the bottom of a blind hole, a shoulder, the
  rest of a rod): nothing more. The groove reaches past its helix, so it does not cut into the material past the
  end, and the last half turn keeps its plain size.
- Open (nothing of the part past the end where the groove runs out): a lead-in at that end takes the half turn the
  thread leaves out down to where a bolt or nut fits (`_lead`): in a hole, a shallow hole a little wider than the
  major diameter; on a rod, a ring cut from the minor radius to a little past the major one. It is `LEAD_SHORT`
  shallower than the inset, and Orca cuts it after the thread; built that way, every one of 204 live threads (M3 to
  M12, through and blind holes, free rods, rods on a shoulder, part length threads, six start angles) built as
  worked out. Without it the plain half turn at the face would stop a bolt or nut.
- Neither (part of the ring is material, or a round may have taken it): the thread is left out.

Orca stops the whole rebuild on a thread outside its limits (`orca_limits`) or one that removes nothing, so such a
thread is left out, and so is a left hand thread (Orca makes right hand threads only); a thread whose length follows
a variable gets the shortest length Orca makes on its parameter's line (`limits`). The numbers come from Fusion's
thread info (`design_model/steps/thread.py`: metric and Unified threads only). A cosmetic thread changes no shape:
a ThreadFeature writes nothing, and a tapped hole is drilled at its drill size.
"""
import copy
import math

from ..capture_model import gap_hints
from ..geometry import vec
from ..orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType
from ..orca_recipe.feature import CadFeature
from . import causes, finish_body, kept_refs, limits
from ..design_model.problem import Problem
from ..design_model.steps import hole as hole_facts, thread as facts
from ..design_model.values import Quantity
from ..design_model import words as shared
from .sketches import entities_of
from .solid import CUT, Prism
from .skip import Skip

# The pitches (mm) the Orca copy writes a thread for.
PITCHES = (0.2, 10.0)
# Orca's thread limits (CadDocument, Thread), kept with this share of margin.
LIMIT_MARGIN = 0.02
# How far inside each end of Fusion's thread the Orca thread starts and stops, in pitches.
INSET = 0.5
# A lead-in at an open end is this much (mm) shallower than the inset, and this much (mm) wider than the major
# diameter in a hole, or past the major radius on a rod; it must be at least LEAD_LEAST (mm) deep.
LEAD_SHORT = 0.05
LEAD_WIDER = 0.1
LEAD_LEAST = 0.05
# The rings tested past an end start this far (mm) past it, and are this many pitches long.
END_GAP = 0.02
END_RING = 0.5
# Lines along the axis that test a ring: this many around, at this many radii.
_AROUND = 12
_RADII = 4
OPEN, CLOSED = "open", "closed"
COSMETIC_NOTE = "%s: the thread is cosmetic in Fusion, so the hole is drilled at its drill size."
THREAD_NOTE = ("%s: Orca cuts its own V shaped thread, which can differ a little from Fusion's. It starts and stops "
               "half a turn inside the ends of the thread, since Orca does not always build a thread that runs out "
               "of the part.")
LEAD_NOTE = {True: " Where the thread runs out of the part, the hole is a little wider than the thread for that half "
                   "turn, so a bolt still goes in.",
             False: " Where the thread runs out of the part, the rod is cut down to the thread's root for that half "
                    "turn, so a nut still goes on."}


def orca_limits(major, minor, pitch, height):
    """The reason Orca would refuse a thread, or None."""
    radius, depth = major / 2.0, (major - minor) / 2.0
    keep = 1.0 - LIMIT_MARGIN
    if radius < 0.5 / keep:
        return "it is thinner than Orca's smallest thread"
    if pitch <= 0.1 / keep:
        return "its pitch is finer than Orca makes"
    if not 1e-3 < depth < 0.7 * pitch * keep or depth >= 0.45 * radius * keep:
        return "its depth is outside what Orca makes for this size"
    if height <= 0.5 * pitch / keep:
        return "it is shorter than Orca makes"
    if height / pitch >= 400.0 * keep:
        return "it has more turns than Orca makes"
    return None


def inset(length, pitch):
    """The length of the Orca thread inside a Fusion thread of `length` (a `Quantity`)."""
    return length.plus(-2.0 * INSET * pitch)


def _ring_lines(point, axis, low, high):
    """Start points of lines along `axis` through a ring about it between radii `low` and `high`."""
    x = _perpendicular(axis)
    y = vec.cross(axis, x)
    out = []
    for k in range(_RADII):
        radius = low + (high - low) * k / (_RADII - 1)
        for n in range(_AROUND):
            angle = 2.0 * math.pi * (n + 0.5) / _AROUND
            out.append(vec.add(point, vec.add(vec.scale(x, radius * math.cos(angle)),
                                              vec.scale(y, radius * math.sin(angle)))))
    return out


def _covered(spans, low, high):
    return sum(max(0.0, min(b, high) - max(a, low)) for a, b in spans)


def _end(solid, point, out, spec, internal, wall):
    """OPEN, CLOSED or None for the end of a thread at `point` on its axis, `out` the unit direction away from the
    thread there; `wall` is the radius of the face the thread is on. The ring between the wall and the thread's other
    radius, just past the end: no material at all is open; firm material all round (no round may have taken it) is
    closed."""
    radius, depth = spec.major / 2.0, (spec.major - spec.minor) / 2.0
    low, high = (wall, radius) if internal else (radius - depth, wall)
    if high - low <= 1e-6:
        return None
    trim = 0.15 * (high - low)
    lines = _ring_lines(point, out, low + trim, high - trim)
    reach = END_GAP + END_RING * spec.pitch
    if all(_covered(solid.material(p, out), END_GAP, reach) <= 1e-6 for p in lines):
        return OPEN
    if all(_covered(solid.firm(p, out), END_GAP, reach) >= reach - END_GAP - 1e-6 for p in lines):
        return CLOSED
    return None


def _lead_prism(point, inward, spec, internal):
    """The shape a lead-in takes at an open end at `point`, cut along `inward`: a disc a little wider than the major
    diameter in a hole, a ring from the minor radius to a little past the major one on a rod."""
    radius, depth = spec.major / 2.0, (spec.major - spec.minor) / 2.0
    x = _perpendicular(inward)
    frame = {"origin": list(point), "x": x, "y": vec.cross(inward, x), "z": list(inward)}
    outer = [{"kind": "circle", "center": [0.0, 0.0], "radius": radius + (LEAD_WIDER / 2.0 if internal
                                                                           else LEAD_WIDER)}]
    loops = [outer] if internal else [outer, [{"kind": "circle", "center": [0.0, 0.0], "radius": radius - depth}]]
    return Prism(frame, loops, 0.0, INSET * spec.pitch - LEAD_SHORT)


class Ends:
    """The two ends of one thread on its axis: `points` (start, end), `rise` the direction from start to end, and
    `kinds` (OPEN or CLOSED) of each."""

    def __init__(self, points, rise, kinds):
        self.points, self.rise, self.kinds = points, rise, kinds

    @property
    def open(self):
        return [n for n, kind in enumerate(self.kinds) if kind == OPEN]


def _ends(ctx, start, rise, length, spec, internal, wall, what):
    """The `Ends` of a Fusion thread from `start` along `rise` for `length` mm, or a Skip when an end cannot be told
    or its lead-in cannot be cut."""
    points = [list(start), vec.add(start, vec.scale(rise, length))]
    outs = [vec.scale(rise, -1.0), list(rise)]
    kinds = [_end(ctx.solid, p, o, spec, internal, wall) for p, o in zip(points, outs)]
    if None in kinds:
        return Skip("The copy cannot tell whether the thread of %s runs out of the part at %s, and a thread with a "
                    "plain end where it runs out would stop a bolt or nut, so it is left out."
                    % (what, "its start" if kinds[0] is None else "its end"), causes.THREAD_END)
    if (OPEN in kinds) and INSET * spec.pitch - LEAD_SHORT < LEAD_LEAST:
        return Skip("The pitch of the thread of %s is too fine for the lead-in Orca needs where it runs out of the "
                    "part, so it is left out." % what, gap_hints.THREAD_LIMITS)
    for n in [n for n, kind in enumerate(kinds) if kind == OPEN]:
        if not ctx.solid.meets(_lead_prism(points[n], vec.scale(outs[n], -1.0), spec, internal)):
            return _misses(ctx)
    return Ends(points, list(rise), kinds)


def _lead(ctx, name, ends, n, spec, internal, place=None):
    """Write the lead-in at open end `n` of a thread after the thread, and add it to the part's shape. `place` is the
    tapped hole's `hole_place.Place` (its centre may follow variables), None for a ThreadFeature."""
    point, inward = ends.points[n], vec.scale(ends.rise, 1.0 if n == 0 else -1.0)
    prism = _lead_prism(point, inward, spec, internal)
    ctx.solid.add(CUT, prism)
    deep = Quantity(INSET * spec.pitch - LEAD_SHORT)
    label = "%s lead-in%s" % (name, "" if n == 0 else " (end)")
    if internal:
        if place is not None:
            plane, xy = _hole_end_plane(ctx, place, point, n)
        else:
            plane, xy = ctx.place.plane(point, prism.x, prism.y, inward), (Quantity(0.0), Quantity(0.0))
        feature = CadFeature(type=FeatureType.HOLE, name=label, plane=plane, hole_style=0, hole_through=False,
                             thread_major_nominal=True, pattern_inclusive=True)
        ctx.bind(feature, "hole_x", xy[0], "%s place" % label)
        ctx.bind(feature, "hole_y", xy[1], "%s place" % label)
        ctx.bind(feature, "hole_diameter", Quantity(spec.major + LEAD_WIDER), label)
        ctx.bind(feature, "hole_depth", deep, label)
        ctx.add(feature)
        return [feature]
    sketch = CadFeature(type=FeatureType.SKETCH, name=label + " sketch",
                        plane=ctx.place.plane(point, prism.x, prism.y, inward),
                        entities=entities_of(prism.loops))
    cut = CadFeature(type=FeatureType.EXTRUDE, name=label, sketch_ref=ctx.add(sketch), mode=BooleanMode.CUT,
                     extrude_end=ExtrudeEnd.BLIND, thread_major_nominal=True, pattern_inclusive=True)
    ctx.bind(cut, "distance", deep, label)
    ctx.add(cut)
    return [sketch, cut]


def _hole_end_plane(ctx, place, point, n):
    """The plane and the (x, y) `Quantity`s of a lead-in at end `n` of a tapped hole: the hole's own plane at its
    start, and at its far end that plane moved to the end and turned to face back into the part."""
    if n == 0:
        moved = copy.copy(place)
        moved.origin = vec.add(place.origin, vec.scale(place.normal, vec.dot(vec.sub(point, place.centre()),
                                                                             place.normal)))
        return moved.plane(ctx.place), (place.x_value, place.y_value)
    back = vec.scale(place.normal, -1.0)
    origin = vec.add(place.origin, vec.scale(place.normal, vec.dot(vec.sub(point, place.origin), place.normal)))
    return (ctx.place.plane(origin, place.x, vec.cross(back, place.x), back),
            (place.x_value, place.y_value.scaled(-1)))


def _tell_limits(ctx, feature, spec, longest=None):
    """Tell how short (or long) the variables behind a thread's bound length may go before Orca cannot make it, or
    before it is longer than `longest` (mm, the Orca thread on the whole face)."""
    def ok(heights):
        fits = orca_limits(spec.major, spec.minor, spec.pitch, heights[0]) is None
        return limits.stop(fits and (longest is None or heights[0] <= longest + 1e-9), limits.THREAD_NO_FIT)
    limits.tell(ctx, [(feature, "thread_height")], ok)


def note(what, internal, leads):
    """The note on a copied thread; `leads` when it has a lead-in where it runs out of the part."""
    return THREAD_NOTE % what + (LEAD_NOTE[bool(internal)] if leads else "")


def _check(spec, height, what):
    """A Skip for a thread Orca cannot make, else None. `height` is the length of the Orca thread."""
    if not spec.right:
        return Skip("Orca makes right hand threads only, so this left hand thread is left out.")
    why = orca_limits(spec.major, spec.minor, spec.pitch, height)
    if why:
        return Skip("Orca cannot make the thread of %s (%s), and a thread it cannot make stops the whole rebuild, so "
                    "it is left out." % (what, why), gap_hints.THREAD_LIMITS)
    return None


def _perpendicular(n):
    helper = [0.0, 0.0, 1.0] if abs(n[2]) < 0.9 else [1.0, 0.0, 0.0]
    return vec.unit(vec.cross(helper, n))


def _groove(origin, axis, spec, height):
    """The ring between the minor and major radius along the thread: material there is what the groove cuts."""
    x = _perpendicular(axis)
    frame = {"origin": list(origin), "x": x, "y": vec.cross(axis, x), "z": list(axis)}
    loops = [[{"kind": "circle", "center": [0.0, 0.0], "radius": spec.major / 2.0}],
             [{"kind": "circle", "center": [0.0, 0.0], "radius": spec.minor / 2.0}]]
    return Prism(frame, loops, 0.0, height)


def _feature(ctx, name, plane, spec, height, internal, xy=None, longest=None):
    """Write one Orca thread. `height` is a `Quantity`; `xy` the (x, y) `Quantity`s of its axis on the plane, or None;
    `longest` how long it may get (mm) when a variable sets its length."""
    feature = CadFeature(type=FeatureType.THREAD, name=name, plane=plane, thread_radius=spec.major / 2.0,
                         thread_pitch=spec.pitch, thread_depth=(spec.major - spec.minor) / 2.0,
                         thread_internal=bool(internal), thread_major_nominal=True, pattern_inclusive=True)
    ctx.bind(feature, "thread_height", height, "%s length" % name)
    if xy is not None:
        ctx.bind(feature, "thread_x", xy[0], "%s place" % name)
        ctx.bind(feature, "thread_y", xy[1], "%s place" % name)
    ctx.add(feature)
    finish_body.changed(ctx.scope, feature)
    _tell_limits(ctx, feature, spec, longest)
    return feature


def _misses(ctx):
    gap = bool(ctx.left_out)
    return Skip("This thread does not meet the part as the Orca copy builds it%s, and Orca stops the whole rebuild "
                "on a thread that removes nothing, so it is left out." % (" (a step before it is left out)" if gap
                                                                          else ""),
                gap_hints.AFTER_GAP if gap else causes.MISSES_PART)


# ---- ThreadFeature ---------------------------------------------------------------------------------------------

def thread(ctx, step):
    """The Orca thread of a ThreadFeature, nothing for a cosmetic one, or a Skip."""
    item, data = step.brought, step.brought_data
    if not data.get("modeled"):
        return []
    what = item.get("name") or "a thread"
    found = facts.read_feature(data, what, PITCHES)
    if isinstance(found, Problem):
        return Skip.of(found)
    spec, (origin, axis, radius, span, outward) = found.spec, found.cylinder
    internal, full, length, start = found.internal, found.full, found.length, found.start
    if full:
        height = Quantity(span[1] - span[0])
    else:
        height = ctx.quantity(item, "length", float(length))
        if height.n > span[1] - span[0] + 1e-3:
            return Skip(shared.THREAD_LONGER_THAN_FACE)
    if not ctx.has_body:
        return Skip("The part this thread is on is not in the copy.", gap_hints.AFTER_GAP)
    kept_refs.mark_faces(ctx, item, kept_refs.on_face(item, "is cut on"))
    rise = axis if start == 0 else vec.scale(axis, -1.0)
    first = vec.add(origin, vec.scale(axis, span[0] if start == 0 else span[1]))
    ends = _ends(ctx, first, rise, height.n, spec, internal, radius, what)
    if isinstance(ends, Skip):
        return ends
    height = inset(height, spec.pitch)
    problem = _check(spec, height.n, what)
    if problem:
        return problem
    begin = vec.add(first, vec.scale(rise, INSET * spec.pitch))
    if not ctx.solid.meets(_groove(begin, rise, spec, height.n)):
        return _misses(ctx)
    x = _perpendicular(rise)
    plane = ctx.place.plane(begin, x, vec.cross(rise, x), rise)
    made = [_feature(ctx, what, plane, spec, height, internal,
                     longest=None if full else span[1] - span[0] - 2.0 * INSET * spec.pitch)]
    for n in ends.open:
        made += _lead(ctx, what, ends, n, spec, internal)
    ctx.notes.append(note(what, internal, ends.open))
    return made


# ---- the thread of a tapped hole -------------------------------------------------------------------------------

def tapped(item, data):
    """(bore diameter, Spec or None) of a tapped hole, or a Skip: a cosmetic thread is drilled at the drill size and
    writes no thread; a modeled one is drilled at the thread's minor diameter and gets a thread (`hole_threads`)."""
    found = hole_facts.tapped_bore(data, item.get("name") or "a hole", PITCHES)
    return Skip.of(found) if isinstance(found, Problem) else found


def hole_lengths(item, data, spec, positions, normal, depth, ctx):
    """The length of the thread of each hole of a tapped hole as Fusion has it (`Quantity`s), or a Skip. `depth` is the
    hole's depth `Quantity`, None for a hole through all (its length is then measured from the end faces)."""
    if depth is None:
        ends = facts.measured_ends(data, len(positions))
        if isinstance(ends, Problem):
            return Skip.of(ends)
        lengths = [Quantity(abs(vec.dot(vec.sub(e, list(p)), normal))) for p, e in zip(positions, ends)]
    else:
        lengths = [depth] * len(positions)
    reach = facts.hole_depth(data)
    if isinstance(reach, Problem):
        return Skip.of(reach)
    if not reach.full:
        part = ctx.quantity(item, "thread.depth", reach.length)
        if any(part.n > s.n + 1e-6 for s in lengths):
            return Skip(shared.THREAD_DEEPER_THAN_HOLE)
        lengths = [part] * len(positions)
    return lengths


def hole_ends(ctx, where, spec, length, what):
    """The `Ends` of the thread of one tapped hole (`where`, its `hole_place.Place`, drilled along its normal), or a
    Skip. Asked before the hole is cut: the ends are judged by the part around the hole."""
    problem = _check(spec, inset(length, spec.pitch).n, what)
    if problem:
        return problem
    return _ends(ctx, where.centre(), where.normal, length.n, spec, True, spec.minor / 2.0, what)


def hole_thread(ctx, name, where, spec, length, ends):
    """The Orca thread of one tapped hole (`where`, its `hole_place.Place`): on the hole's plane moved into the part
    by the inset, its axis at the hole's place, rising into the part; then the lead-ins at its open ends. `length`
    is from `hole_lengths`, `ends` from `hole_ends`."""
    moved = copy.copy(where)
    moved.origin = vec.add(where.origin, vec.scale(where.normal, INSET * spec.pitch))
    made = [_feature(ctx, name + " thread", moved.plane(ctx.place), spec, inset(length, spec.pitch), True,
                     (where.x_value, where.y_value))]
    for n in ends.open:
        made += _lead(ctx, name, ends, n, spec, True, where)
    return made


HANDLERS = {"ThreadFeature": thread}
