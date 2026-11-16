"""Extrude steps of the capture as Orca features. The handler returns the features it wrote, or a `Skip` with the
reason the step is left out of the copy.

Extrude: one side, symmetric and two sides; new body, join, cut and intersect; a distance, an end on a face or
plane, or through all for a cut or intersect (a join through all ends where the part ends, which no Orca length
follows). A start offset or a start on a face or plane moves the sketch plane. A taper is a Blind extrude's
`taper_deg`, two Blind halves for symmetric and two sided extrudes (`extents` has these rules). Orca's "through all"
goes both ways from the sketch, so a one way through all becomes Orca's through all only when the part lies on that
side of the sketch; otherwise a long blind cut.
A cut or intersect that does not meet the part the copy built (`solid.Solid`) is left out: Orca stops the whole
rebuild on a cut that removes nothing. A one way cut through all has no measured end, so it goes to the side where its
outline meets that part when Fusion's stored direction meets none (`toward_material`).

An outline of straight lines whose corners follow sizes is built from plane cuts (`outline_cuts`, `_cut_built`)
instead of drawn, when the extrude has one side without taper.

The other handlers that write outlines or cuts share these helpers: `misses_reason` (a cut that meets nothing), and
for holes `toward_material`, `behind`, `LONG` and `SIDE_TOL`. The sizes an outline sketch follows or keeps are
worked out in `sketch_sizes`.
"""
import math

from ..capture_model import gap_hints
from ..design_model import roles
from ..geometry import vec
from ..orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType
from ..orca_recipe.feature import CadFeature
from . import causes, drilled, extents, outline_cuts
from .context import Value
from .skip import Skip
from .sketch_sizes import sketch_doubts, sketch_formulas
from .sketches import Outline, outline_sketch, outlines_of
from .solid import ADD, CUT, INTERSECT, Prism, Tapered

# Length of an extrude or hole that stands for "through all" one way (mm).
LONG = 1000.0
SIDE_TOL = 1e-3
_MODES = {"join": BooleanMode.ADD, "cut": BooleanMode.CUT, "intersect": BooleanMode.INTERSECT}
_SOLID_MODES = {"newBody": ADD, "join": ADD, "cut": CUT, "intersect": INTERSECT}


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _label(item):
    return item.get("name") or "the step"


# ---- extrude ---------------------------------------------------------------------------------------------------

class _Side:
    """How one Orca extrude ends: `end` (ExtrudeEnd), `flip`, the `distance` and `distance2` values, Fusion's
    `taper` of that side in degrees with `taper_path`, the parameter path of its angle, and `through` for a long
    blind extrude that stands for through all. Orca tapers only a blind extrude, so a tapered symmetric or two sided
    extrude is two blind sides, one flipped."""

    def __init__(self, end, flip=False, distance=None, distance2=None, taper=0.0, taper_path=None, through=False):
        self.end, self.flip, self.distance, self.distance2 = end, flip, distance, distance2
        self.taper, self.taper_path, self.through = taper, taper_path, through

    def ends(self, feature=None):
        """The `context.Value`s of the lowest and highest height the side covers, or None for through all. With the
        Orca `feature` written from the side, a length whose field is not bound there (Orca could not hold its
        formula, or `limits.guard` unbound it) is its number, so an end follows only what Orca follows."""
        if self.through or self.end == ExtrudeEnd.THROUGH_ALL:
            return None
        distance, distance2 = self.distance, self.distance2
        if feature is not None:
            distance = distance if "distance" in feature.expr else Value(distance.number)
            if distance2 is not None and "distance2" not in feature.expr:
                distance2 = Value(distance2.number)
        if self.end == ExtrudeEnd.SYMMETRIC:
            return distance.scaled(-0.5), distance.scaled(0.5)
        if self.end == ExtrudeEnd.TWO_SIDED:
            return distance2.scaled(-1.0), distance
        return (distance.scaled(-1.0), Value(0.0)) if self.flip else (Value(0.0), distance)


def _sign(value):
    return 1 if value > 0 else -1


def _direction(raw, end_offset, shift):
    """The travel along the sketch normal: the measured end face wins over the stored sign."""
    if end_offset is not None and abs(end_offset - shift) > SIDE_TOL:
        return _sign(end_offset - shift)
    return _sign(raw)


def behind(box, origin, normal, sign):
    """True when part of `box` lies behind the sketch plane (against `sign` along `normal`). An unknown box is taken
    to lie in front."""
    if not box:
        return False
    lo, hi = box["min"], box["max"]
    for x in (lo[0], hi[0]):
        for y in (lo[1], hi[1]):
            for z in (lo[2], hi[2]):
                if sign * vec.dot(vec.sub([x, y, z], origin), normal) < -SIDE_TOL:
                    return True
    return False


def _length(ctx, item, side, which, origin, z, sign=None):
    """`(sign, length Value)` of a side with a distance or one that reaches to a face or plane, or a Skip. `sign`
    sets the direction of a second side."""
    if side.get("kind") == "toEntity":
        return extents.reach(ctx, item, which, side, origin, z, sign)
    if side.get("kind") != "distance":
        return Skip("A two sided extrude is copied only when both sides have a distance or end on a face or plane.",
                    gap_hints.EXTRUDE_END_FACE)
    raw = float(side["distance"])
    if raw == 0:
        return Skip("This extrude has no length.")
    return sign if sign is not None else _sign(raw), ctx.quantity(item, which + ".distance", raw).magnitude()


def _measured_side(ctx, data, frame, end_offset, sides, operation):
    """A Skip when the measured end face of a two sided extrude is not where the side on its side of the sketch puts
    it, else None. `sides` are the `(length Value, way, taper)` of both sides; each side is checked against the end
    on its own side only, never against the end of the other side."""
    if abs(end_offset) <= SIDE_TOL:
        return Skip("The measured end of this extrude does not match its length, so it is not copied.")
    length, way, taper = next(side for side in sides if side[1] == _sign(end_offset))
    return extents.measured_gap(data, 0.0, length.number, way, operation,
                                _holds(ctx, data, frame, 0.0, way, taper))


def _holds(ctx, data, frame, shift, sign, taper):
    """`holds(low, high)` for `extents.measured_gap`: whether the part may have material inside an extrude's
    outlines (moved in or out by its taper) between two heights from its start. None holds there when the far height
    lies past the whole Fusion part (`target_box_before`), or when no step of the body was left out before and the
    part the copy built holds no material there, also none a round or chamfer may have taken. When an outline cannot
    be read, material may lie anywhere."""
    tools = _extrude_tools(data.get("profiles") or [], shift, taper)
    origin = vec.add(frame["origin"], vec.scale(vec.unit(frame["z"]), shift))
    box = data.get("target_box_before")

    def holds(low, high):
        if _past(box, origin, frame["z"], sign, high if sign > 0 else -low):
            return False
        if tools is None or ctx.left_out:
            return True
        return any(ctx.solid.meets(t, sure=False) for t in tools(low, high))

    return holds


def _past(box, origin, normal, sign, length):
    """True when `length` along `normal` (against it for a negative `sign`) from `origin` lies past every corner of
    `box`."""
    if not box:
        return False
    lo, hi = box["min"], box["max"]
    corners = [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    return length > max(sign * vec.dot(vec.sub(c, origin), vec.unit(normal)) for c in corners) + SIDE_TOL


def _sides(ctx, item, data, frame, shift):
    """The `_Side`s of an extrude (one, or two blind ones for a tapered extrude to both sides), or a Skip. A one way
    cut or intersect through all with no measured end goes to the side where its outlines meet the part the copy
    built (`toward_material`)."""
    kind = data.get("extent_type", "one")
    end_offset = data.get("end_offset")
    z = vec.unit(frame["z"])
    origin = vec.add(frame["origin"], vec.scale(z, shift))
    before = data.get("target_box_before")
    operation = data.get("operation")

    def through(side):
        return (side or {}).get("kind") in ("throughAll", "all")

    def untapered(*sides):
        tapers = [(side or {}).get("taper_deg", 0.0) for side in sides]
        if any(t is None for t in tapers):
            return Skip(_UNREAD)
        if any(tapers):
            return Skip(_TAPER_THROUGH, causes.TAPER_EXTENT)
        return None

    # A join or new body through all ends where Fusion's part ends, which moves with the sizes; Orca's through all
    # and a long blind extrude would add material far past it.
    if operation not in ("cut", "intersect") and (
            through(data.get("side_one")) or (kind == "two" and through(data.get("side_two")))):
        return Skip(_THROUGH_ADDS, causes.THROUGH_ALL_ADDS)

    if kind == "symmetric":
        side = data.get("side_one")
        if through(side):
            return untapered(side) or [_Side(ExtrudeEnd.THROUGH_ALL)]
        sym = data.get("symmetric")
        if not sym or not isinstance(sym.get("distance"), (int, float)):
            return Skip("This extrude has no readable length.")
        taper = sym.get("taper_deg", 0.0)
        if taper is None or sym.get("full_length") is None:
            return Skip(_UNREAD)
        q = ctx.quantity(item, "symmetric.distance", float(sym["distance"])).magnitude()
        full, half = (q, q.scaled(0.5)) if sym["full_length"] else (q.scaled(2.0), q)
        if taper:
            return [_Side(ExtrudeEnd.BLIND, flip=flip, distance=half, taper=taper, taper_path="symmetric.taper_deg")
                    for flip in (False, True)]
        return [_Side(ExtrudeEnd.SYMMETRIC, distance=full)]

    one, two = data.get("side_one"), data.get("side_two")
    if kind == "two":
        if not one or not two:
            return Skip("This extrude has no readable length.")
        if through(one) and through(two):
            return untapered(one, two) or [_Side(ExtrudeEnd.THROUGH_ALL)]
        if shift:
            return Skip("A two sided extrude that starts away from its sketch is not copied yet.")
        first = _length(ctx, item, one, "side_one", origin, z)
        if isinstance(first, Skip):
            return first
        sign, first = first
        if one.get("kind") == "distance" and two.get("kind") == "distance" and end_offset is not None \
                and abs(end_offset) > SIDE_TOL and _sign(end_offset) != sign \
                and abs(abs(end_offset) - first.number) <= SIDE_TOL \
                and abs(abs(end_offset) - abs(float(two["distance"]))) > SIDE_TOL:
            sign = -sign
        second = _length(ctx, item, two, "side_two", origin, z, -sign)
        if isinstance(second, Skip):
            return second
        second = second[1]
        tapers = (extents.taper_of(data, one, "side_one"), extents.taper_of(data, two, "side_two"))
        if None in tapers:
            return Skip(_UNREAD)
        if "toEntity" in (one.get("kind"), two.get("kind")) and end_offset is not None:
            problem = _measured_side(ctx, data, frame, end_offset,
                                     ((first, sign, tapers[0]), (second, -sign, tapers[1])), operation)
            if problem:
                return problem
        if any(tapers):
            if operation == "intersect":
                return Skip("A tapered intersect to both sides is not copied to Orca yet.", causes.TAPER_EXTENT)
            return [_Side(ExtrudeEnd.BLIND, flip=(sign < 0) == (n == 0), distance=length, taper=taper,
                          taper_path=path)
                    for n, (length, taper, path) in enumerate(((first, tapers[0], "side_one.taper_deg"),
                                                               (second, tapers[1], "side_two.taper_deg")))]
        if sign < 0:
            first, second = second, first
        return [_Side(ExtrudeEnd.TWO_SIDED, distance=first, distance2=second)]

    if not one:
        return Skip("This extrude has no readable length.")
    if through(one):
        refused = untapered(one)
        if refused:
            return refused
        if one.get("kind") == "all":
            return [_Side(ExtrudeEnd.THROUGH_ALL)]
        sign = 1 if one.get("positive", True) else -1
        if end_offset is not None and abs(end_offset - shift) > SIDE_TOL:
            sign = _sign(end_offset - shift)
        elif operation in ("cut", "intersect"):
            sign = toward_material(ctx, item, _extrude_tools(data.get("profiles") or [], shift), sign)
        if not behind(before, origin, frame["z"], sign):
            return [_Side(ExtrudeEnd.THROUGH_ALL)]
        return [_Side(ExtrudeEnd.BLIND, flip=sign < 0, distance=Value(LONG), through=True)]
    taper = extents.taper_of(data, one, "side_one")
    if taper is None:
        return Skip(_UNREAD)
    if one.get("kind") == "distance":
        found = _length(ctx, item, one, "side_one", origin, z)
        if isinstance(found, Skip):
            return found
        sign = _direction(float(one["distance"]), end_offset, shift)
        if (data.get("start") or {}).get("kind") == "fromEntity":
            gap = extents.measured_gap(data, shift, found[1].number, sign, operation,
                                       _holds(ctx, data, frame, shift, sign, taper))
            if gap is not None:
                return gap
        return [_Side(ExtrudeEnd.BLIND, flip=sign < 0, distance=found[1], taper=taper,
                      taper_path="side_one.taper_deg")]
    if one.get("kind") == "toEntity":
        found = extents.reach(ctx, item, "side_one", one, origin, z)
        if isinstance(found, Skip):
            return found
        sign, length = found
        gap = extents.measured_gap(data, shift, length.number, sign, operation,
                                   _holds(ctx, data, frame, shift, sign, taper))
        if gap is not None:
            return gap
        return [_Side(ExtrudeEnd.BLIND, flip=sign < 0, distance=length, taper=taper,
                      taper_path="side_one.taper_deg")]
    return Skip("This way of setting the extrude length is not copied yet.")


def _reach(sign):
    """The heights a one way tool through all covers along its normal."""
    return (0.0, math.inf) if sign > 0 else (-math.inf, 0.0)


def _extrude_tools(profiles, shift, taper=0.0):
    """`maker(low, high)` giving the shapes of an extrude's outlines between two heights (prisms, or for a `taper` in
    degrees the outer loops tapered as `_shape` tapers them), or None when an outline cannot be read."""
    outlines = []
    for profile in profiles:
        outline = outlines_of(profile) if isinstance(profile.get("frame"), dict) else None
        if outline is None:
            return None
        outlines.append((_frame_at(profile["frame"], shift), [outline.outer] + outline.holes))
    if taper:
        rate = math.tan(math.radians(taper))
        return lambda low, high: [Tapered(frame, loops[0], low, high, rate) for frame, loops in outlines]
    return lambda low, high: [Prism(frame, loops, low, high) for frame, loops in outlines]


def toward_material(ctx, item, tools, sign):
    """The direction of a one way tool through all with no measured end: Fusion's stored direction can point away
    from the part, so the side whose tools meet the part the copy built wins. The stored one stays when both sides,
    or neither, meet it. `tools(low, high)` gives the tool prisms between two heights."""
    if tools is None or ctx.solid.empty:
        return sign
    ahead = any(ctx.solid.meets(t) for t in tools(*_reach(sign)))
    if ahead or not any(ctx.solid.meets(t) for t in tools(*_reach(-sign))):
        return sign
    ctx.notes.append("%s: Fusion stored its direction toward a side without material; the side it cuts through "
                     "was used." % _label(item))
    return -sign


def _heights(side, role):
    """The heights along the sketch normal the Orca extrude covers, from the sketch plane (moved for a start
    offset)."""
    if role == "hole" or side.end == ExtrudeEnd.THROUGH_ALL:
        return -math.inf, math.inf
    if side.through:
        return (-LONG, 0.0) if side.flip else (0.0, LONG)
    low, high = side.ends()
    return low.number, high.number


def _shape(side, role, frame, piece):
    """The shape one Orca extrude of `piece` builds (`solid.Prism`, or `solid.Tapered` for a tapered side). The
    values of a prism's end faces (`Prism.ends`) are set once the extrude is written and its fields bound."""
    low, high = _heights(side, role)
    if side.taper and role != "hole":
        return Tapered(frame, piece.outer, low, high, math.tan(math.radians(side.taper)))
    return Prism(frame, [piece.outer] + piece.holes, low, high)


def misses_reason(ctx, what):
    """(reason, cause) for a tool that does not meet the part the copy built."""
    gap = bool(ctx.left_out)
    return ("This %s does not meet the part as the Orca copy builds it%s, and Orca stops the whole rebuild on a %s "
            "that removes nothing, so it is left out." % (
                what, " (a step before it is left out)" if gap else "", what),
            gap_hints.AFTER_GAP if gap else causes.MISSES_PART)


_TAPER_THROUGH = "Orca does not taper an extrude through all, so this tapered extrude is left out."
_THROUGH_ADDS = "An extrude through all is copied to Orca only when it cuts or intersects."
_UNREAD = "This extrude could not be read from Fusion."


def _profile_check(profile):
    """The reason a profile record cannot be copied, or None."""
    if profile.get("face") and (profile.get("surface") != "Plane" or profile.get("problem")):
        return "This extrude uses a face of the body that is not flat, or could not be read, as its outline."
    if profile.get("text"):
        return "Sketch text is not copied to Orca yet."
    if profile.get("foreign"):
        return "This extrude uses a sketch of another component, which is not copied yet."
    if profile.get("space") not in (None, "sketch", "model") or not isinstance(profile.get("frame"), dict):
        return "The outline of this extrude could not be read."
    return None


def _area(outline):
    """The area inside an outline's outer loop, from the corners and circles of its curves (enough to order
    outlines)."""
    pts = []
    for c in outline.outer:
        if c.get("kind") == "circle":
            return math.pi * float(c["radius"]) ** 2
        pts += [c.get("start"), c.get("end"), c.get("mid")]
    pts = [p for p in pts if p]
    if len(pts) < 3:
        return 0.0
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def _frame_at(frame, shift):
    if not shift:
        return frame
    return dict(frame, origin=vec.add(frame["origin"], vec.scale(vec.unit(frame["z"]), shift)))


def extrude(ctx, item):
    """The Orca features of an extrude, or a Skip."""
    data = _data(item)
    operation = data.get("operation")
    if operation == "newComponent":
        return Skip("This extrude makes a new component, which is not copied yet.", gap_hints.NEW_COMPONENT)
    if data.get("thin") is None and "thin" in data:
        return Skip(_UNREAD)
    if data.get("thin"):
        return Skip("Thin extrudes are not copied to Orca yet.", gap_hints.THIN_OUTLINE)
    profiles = data.get("profiles") or []
    if not profiles:
        return Skip("This extrude has no outline that could be read.")
    for profile in profiles:
        problem = _profile_check(profile)
        if problem:
            return Skip(problem)
    if operation not in ("newBody", "join", "cut", "intersect"):
        return Skip("This kind of extrude is not copied yet.")
    if not ctx.has_body and operation in ("cut", "intersect"):
        return Skip("The part this %s works on is not in the copy." % ("cut" if operation == "cut" else "intersect"),
                    gap_hints.AFTER_GAP)
    others = roles.new_bodies(item, [ctx.target])
    if operation == "newBody" and len(profiles) > 1 and others:
        return Skip("This extrude makes several bodies, and the Orca copy cannot tell which outline is the part.")
    if operation == "cut" and others:
        return Skip("This cut splits the part into pieces, which is not copied to Orca yet.")
    if operation == "intersect" and len(profiles) > 1:
        return Skip("An intersect with several outlines is not copied to Orca yet.")
    first_body = not ctx.has_body
    frame = profiles[0]["frame"]
    shift = extents.start(ctx, item, data, frame)
    if isinstance(shift, Skip):
        return shift
    sides = _sides(ctx, item, data, frame, shift)
    if isinstance(sides, Skip):
        return sides
    if operation == "intersect" and len(sides) > 1:
        return Skip("A tapered intersect to both sides is not copied to Orca yet.", causes.TAPER_EXTENT)
    refused = extents.taper_measured(data, sides, len(profiles))
    if refused is not None:
        return refused
    start = data.get("start") or {}
    moved = ctx.quantity(item, "start.offset", shift).reads if start.get("kind") == "offset" else ()

    parts = []
    for profile in profiles:
        outline = outlines_of(profile)
        if outline is None:
            return Skip("The outline of this extrude could not be read.")
        parts.append((profile, outline))
    # Bigger outlines first, so an outline inside the hole of another is built after that hole is cut.
    parts.sort(key=lambda p: -_area(p[1]))

    written = []
    pieces_of = {}  # id of what each outline became -> (the outline, its profile)
    count = 0
    for profile, outline in parts:
        formulas = sketch_formulas(ctx, profile)
        frame = _frame_at(profile["frame"], shift)
        on_moving = extents.sketch_plane_sizes(ctx, item, profile)
        ctx.doubt(on_moving, ("%s: its outline is a face of the body that may change with it, and Orca draws that "
                              "face as it is now" if profile.get("face") else
                              "%s: its sketch sits on a plane or face that moves with it, and Orca cannot move a "
                              "sketch plane with a variable") % _label(item))
        held = tuple(dict.fromkeys(tuple(moved) + on_moving))
        # The first body of the part: its holes become cuts through it, so the outer outline can stay a simple
        # rectangle or circle whose size follows variables.
        pieces = [(outline, None)]
        if first_body and outline.holes:
            pieces = [(Outline(outline.outer, []), None)] + [(Outline(h, []), "hole") for h in outline.holes]
        made_pieces = []
        for piece, role in pieces:
            count += 1
            name = _label(item) if count == 1 else "%s (%d)" % (_label(item), count)
            made = outline_sketch(piece, frame, ctx.place, formulas, name + " sketch")
            if made is None:
                return Skip("The outline of this extrude has a curve the Orca copy cannot draw yet (it draws "
                            "lines, arcs, circles and splines Fusion gives exactly).")
            # The outline and its formulas, for corner tools cut from a rectangle that follows sizes.
            made.source = (piece, formulas)
            # A circle hole whose centre moves is drilled as an Orca hole, whose place follows sizes.
            if role == "hole" and len(sides) == 1:
                drilled.drill(made, formulas, frame, sides[0])
            made_pieces.append((piece, role, name, made))
        # A circle hole that keeps its place in Orca, in a rectangle that the same size moves: the rectangle stays a
        # plain one that grows about its centre, so a hole at its centre stays there. Built from cuts, the rectangle
        # would grow to one side and leave the hole behind.
        kept_holes = {n for _, role, _, made in made_pieces if role == "hole" for n in made.moves}
        for piece, role, name, made in made_pieces:
            if role is None and len(sides) == 1 and not sides[0].taper:
                if not (made.shape == "rectangle" and kept_holes & set(made.moves)):
                    made = _cut_built(ctx, piece, made, formulas)
            elif role is None and formulas is not None and (made.shape == "outline" or made.moves):
                made.notes.append("%s keeps its numbers: the copy builds an outline whose corners follow sizes "
                                  "only for an extrude without taper." % made.feature.name)
            elif role == "hole" and made.shape == "outline":
                made.notes.append("%s keeps its numbers: a hole in the outline is cut through as drawn, and only a "
                                  "plain rectangle or circle hole follows sizes." % made.feature.name)
            pieces_of[id(made)] = (piece, profile)
            for n, side in enumerate(sides if role != "hole" else sides[:1]):
                taper = None
                if side.taper and role != "hole":
                    taper = extents.taper(ctx, item, side.taper_path, side.taper, side.flip, outline,
                                          side.distance.number)
                    if isinstance(taper, Skip):
                        return taper
                shape = _shape(side, role, frame, piece)
                if isinstance(shape, Prism):
                    shape.plane_sizes = held
                written.append((made, role, name if n == 0 else "%s (other side)" % name, shape, side, taper))
    if operation in ("cut", "intersect"):
        kept = [w for w in written if ctx.solid.meets(w[3])]
        if not kept:
            return Skip(*misses_reason(ctx, "cut" if operation == "cut" else "intersect"))
        if len(kept) < len(written):
            ctx.notes.append("%s: %d of its outlines do not meet the part as the Orca copy builds it and are left "
                             "out." % (_label(item), len(written) - len(kept)))
        written = kept
    sketch_doubts(ctx, item, parts, list({id(w[0]): (w[0], pieces_of[id(w[0])][0], pieces_of[id(w[0])][1])
                                          for w in written}.values()))

    out = []
    sketches = {}
    for made, role, name, shape, side, taper in written:
        ctx.solid.add(CUT if role == "hole" else _SOLID_MODES.get(operation, ADD), shape)
        if role == "hole" and made.drill is not None:
            out.append(drilled.write(ctx, made, name))
            continue
        if isinstance(made, outline_cuts.Planned):
            mode = BooleanMode.NEW if not ctx.has_body else _MODES.get(operation, BooleanMode.ADD)
            features, sketch, block = outline_cuts.write(ctx, made, shape_frame(shape), side, mode, name,
                                                         item.get("index"))
            out.extend(features)
            shape.built = made
            extents.guard(ctx, sketch, block, side, shape.loops[0])
            shape.ends = side.ends(block)
            continue
        if id(made) not in sketches:
            sketches[id(made)] = ctx.add(made.feature)
            out.append(made.feature)
            for field, (formula, reads) in made.bound.items():
                ctx.bind(made.feature, field, Value(getattr(made.feature, field), formula, reads),
                         "%s %s" % (made.feature.name, field))
            made.feature.thread_major_nominal = made.feature.pattern_inclusive = True
        feature = CadFeature(type=FeatureType.EXTRUDE, name=name, sketch_ref=sketches[id(made)], extrude_end=side.end,
                             flip=side.flip, thread_major_nominal=True, pattern_inclusive=True)
        if role == "hole":
            feature.mode, feature.extrude_end, feature.flip = BooleanMode.CUT, ExtrudeEnd.THROUGH_ALL, False
        else:
            feature.mode = BooleanMode.NEW if not ctx.has_body else _MODES.get(operation, BooleanMode.ADD)
            feature.symmetric = side.end == ExtrudeEnd.SYMMETRIC
            if side.distance is not None:
                ctx.bind(feature, "distance", side.distance, "%s distance" % name)
            if side.distance2 is not None:
                ctx.bind(feature, "distance2", side.distance2, "%s second side" % name)
            if taper is not None:
                ctx.bind(feature, "taper_deg", taper, "%s taper" % name)
        slot = (len(ctx.bodies), ctx.scope.index)
        ctx.add(feature)
        ctx.has_body = True
        out.append(feature)
        if type(shape) is Prism:
            shape.sketch = (made, feature)
            shape.slot = slot
        if role != "hole":
            extents.guard(ctx, made.feature, feature, side, getattr(shape, "base", shape).loops[0])
            if type(shape) is Prism:
                shape.ends = side.ends(feature)
    return out


def shape_frame(prism):
    """The sketch frame of a prism (capture coordinates)."""
    return {"origin": list(prism.origin), "x": list(prism.x), "y": list(prism.y), "z": list(prism.z)}


def _cut_built(ctx, outline, made, formulas):
    """The outline built from plane cuts (`outline_cuts.Planned`) when its corners follow sizes that the drawn
    sketch `made` cannot follow (any outline of lines, a rectangle that moves or turns), else `made`. When the cuts
    cannot be planned for an outline that follows sizes, `made` gets a note why."""
    if made.shape == "circle" or (made.shape == "rectangle" and not made.moves and not made.notes):
        return made
    found = outline_cuts.plan(ctx, outline, formulas)
    if isinstance(found, outline_cuts.Planned):
        return found
    if isinstance(found, str):
        made.notes.append("%s keeps its numbers: %s." % (made.feature.name, found))
    return made


HANDLERS = {"ExtrudeFeature": extrude}
