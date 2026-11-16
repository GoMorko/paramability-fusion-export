"""Where the holes of a hole step sit in Orca, and which sizes move them.

Orca drills a hole at (`hole_x`, `hole_y`) on its plane, along the plane normal. When the capture holds the frame of
the sketch the hole points are on (`sketch_frame`) and the graph of that sketch, the plane is the sketch plane, turned
so that its normal is the drilling direction, and `hole_x` and `hole_y` are each point's sketch coordinates: formulas
of the sizes where the sketch's dimensions give them (`sketches.SketchFormulas`). Otherwise the plane sits at each hole
centre and the centres keep their place; the sizes that move the sketch get the reason.

A centre follows only sizes that the copy so far follows everywhere: a size some earlier step does not follow (a
rectangle that grows about its centre in Orca while Fusion also moves it, a left out step) would put the hole in
another place on the part than Fusion does, so such a size keeps its current value in the hole's formula and gets the
reason. Orca cannot move a plane with a variable: a sketch that a size moves as a whole (one on a face of the part, or
on an offset plane) keeps its place, and the sizes that may move it get the reason (`reach.hole_plane_sizes`), as for the sketch
of an extrude. A hole placed on a face without a sketch keeps its place the same way.
"""
from ..design_model import reach
from ..design_model.dimension_sizes import size_env
from ..geometry import vec
from ..sketch_values.expr import ExprDomainError
from ..design_model.values import Quantity
from .sketches import UNCONFIRMED, SketchFormulas, reads_input

# A hole point lies on its sketch plane, and matches a graph point, when it is this close (mm).
POINT_TOL = 1e-4


class Place:
    """The plane of one hole (capture coordinates: `origin`, unit `x`, `y` and `normal`, the drilling direction) and
    the hole's place on it (`x_value`, `y_value`, `Quantity`s)."""

    def __init__(self, origin, x, y, normal, x_value=None, y_value=None):
        self.origin, self.x, self.y, self.normal = list(origin), list(x), list(y), list(normal)
        self.x_value = x_value or Quantity(0.0)
        self.y_value = y_value or Quantity(0.0)

    def centre(self):
        return vec.add(self.origin, vec.add(vec.scale(self.x, self.x_value.n),
                                            vec.scale(self.y, self.y_value.n)))

    def plane(self, place):
        """The Orca sketch plane (`place.Placement.plane`)."""
        return place.plane(self.origin, self.x, self.y, self.normal)


def _perpendicular(n):
    helper = [0.0, 0.0, 1.0] if abs(n[2]) < 0.9 else [1.0, 0.0, 0.0]
    return vec.unit(vec.cross(helper, n))


def _at_centre(position, normal):
    x = _perpendicular(normal)
    return Place(position, x, vec.cross(normal, x), normal)


def _graph(ctx, data):
    token = data.get("sketch_token")
    for record in ctx.capture.get("sketch_graphs") or []:
        if isinstance(record, dict) and token and record.get("token") == token \
                and not record.get("error") and not record.get("cut"):
            return record
    return None


def _sketch_sizes(ctx, data):
    """Fusion names of the free sizes that move the hole's sketch: those its dimensions read."""
    if not data.get("sketch") or ctx.table is None:
        return ()
    return tuple(reach.profile_sizes(ctx.table, {"sketch": data["sketch"]}, _graph(ctx, data)))


def _point_id(record, token, uv):
    """The graph point of a hole point: by its token, else the one point at its sketch coordinates."""
    points = [p for p in record.get("points") or [] if isinstance(p, dict) and isinstance(p.get("id"), int)]
    if token:
        found = [p["id"] for p in points if p.get("token") == token]
        if len(found) == 1:
            return found[0]
    found = [p["id"] for p in points if p.get("xy") and abs(p["xy"][0] - uv[0]) <= POINT_TOL
             and abs(p["xy"][1] - uv[1]) <= POINT_TOL]
    return found[0] if len(found) == 1 else None


def _free_reads(table, size_names):
    """Fusion names of the free sizes behind recipe size names."""
    out = {}
    for e in table.entries:
        if e.size_name in size_names:
            out.update(dict.fromkeys([e.name] if e.state == "free" else list(e.reads)))
    return tuple(out)


def _coordinate(ctx, formulas, pair, k, number):
    """(`Quantity` of one sketch coordinate, the reason it keeps its number although sizes may move it, the Fusion names
    of the sizes held at their value). Sizes an earlier step does not follow (`ctx.held`) are held."""
    if pair is None or not pair[k].derived:
        return Quantity(number), (pair[k].reason if pair is not None and pair[k].reason else "it has no formula"), ()
    formulas.why = ""
    over = formulas.over_sizes(pair[k].expr)
    if over is None:
        return Quantity(number), formulas.why or "it has no formula", ()
    env = size_env(ctx.table, {})
    held = [n for n in over.names() if any(ctx.held(r) for r in _free_reads(ctx.table, (n,)))]
    held_reads = _free_reads(ctx.table, held)
    over = over.substitute({n: env[n] for n in held if n in env})
    if over.is_constant:
        return Quantity(number), None, held_reads
    try:
        now = over.value(env)
    except (ExprDomainError, KeyError):
        return Quantity(number), "its formula cannot be worked out", held_reads
    if abs(now - number) > 1e-6 * max(1.0, abs(number)):
        return Quantity(number), "its formula does not give its place", held_reads
    return Quantity(number, over.text(), _free_reads(ctx.table, over.names())), None, held_reads


def _followed(ctx, item, data, normal, positions):
    """The `Place`s of holes on one sketch whose frame and graph are known, or a reason why not."""
    frame = data.get("sketch_frame")
    record = _graph(ctx, data)
    if ctx.table is None or not isinstance(frame, dict) or record is None:
        return "the place of their sketch is not known"
    z = vec.unit(frame["z"])
    turn = vec.dot(normal, z)
    if abs(abs(turn) - 1.0) > 1e-6:
        return "they are not drilled straight into their sketch"
    try:
        formulas = SketchFormulas(ctx.table, record)
    except Exception:  # a sketch that cannot be solved keeps its numbers
        return "their sketch cannot be worked out"
    ctx.doubt(formulas.unconfirmed, UNCONFIRMED % (data.get("sketch") or "a sketch"))
    side = 1.0 if turn > 0 else -1.0
    x, y = vec.unit(frame["x"]), vec.scale(vec.unit(frame["y"]), side)
    tokens = data.get("point_tokens") or [None] * len(positions)
    out, reasons, held = [], [], []
    for position, token in zip(positions, tokens):
        d = vec.sub(list(position), frame["origin"])
        u, v, w = vec.dot(d, vec.unit(frame["x"])), vec.dot(d, vec.unit(frame["y"])), vec.dot(d, z)
        if abs(w) > POINT_TOL:
            return "a hole point is off its sketch plane"
        pid = _point_id(record, token, (u, v))
        pair = formulas.solution.points.get(pid) if pid is not None else None
        if pid is None:
            reasons.append("a hole point is not in the sketch record")
        if pair is not None and any(v.derived and reads_input(v.expr) for v in pair):
            ctx.doubt(reach.any_face_sizes(ctx.table, ctx.capture.get("items") or [], item),
                      "%s: the hole centres are placed by geometry projected into %s, and Orca keeps that "
                      "geometry where it is now" % (item.get("name") or "the hole",
                                                    data.get("sketch") or "their sketch"))
        hx, why_x, held_x = _coordinate(ctx, formulas, pair, 0, u)
        hy, why_y, held_y = _coordinate(ctx, formulas, pair, 1, v)
        reasons += [r for r in (why_x, why_y) if r]
        held += list(held_x) + list(held_y)
        out.append(Place(frame["origin"], x, y, normal, hx, hy.scaled(side)))
    return out, reasons, held


def places(ctx, item, data, normal, positions):
    """The `Place` of each hole position, drilled along `normal`. Sizes that move the points but that the places do
    not follow get the reason, and so do the sizes that may move the plane they sit on (`reach.hole_plane_sizes`)."""
    name = item.get("name") or "the hole"
    found = _followed(ctx, item, data, normal, positions) if data.get("sketch") else "they are not on a sketch"
    # Marked after `_followed`, which holds in the centres' formulas the sizes earlier steps do not follow: a size
    # that moves the plane still moves the centres on it.
    ctx.doubt(reach.hole_plane_sizes(ctx.table, ctx.capture.get("items") or [], item, data),
              "%s: the holes sit on a face or plane that may move with it, and Orca "
              "keeps them where they are now" % name)
    if isinstance(found, tuple):
        out, reasons, held = found
        bound = {n for p in out for v in (p.x_value, p.y_value) for n in v.reads}
        if reasons:
            loose = [n for n in _sketch_sizes(ctx, data) if n not in bound]
            ctx.doubt(loose, "%s: some hole centres keep their place in Orca (%s)" % (name, reasons[0]))
        if held:
            ctx.doubt(tuple(dict.fromkeys(held)), "%s: the hole centres do not follow it, since the part around them "
                      "does not follow it everywhere in Orca" % name)
        return out
    ctx.doubt(_sketch_sizes(ctx, data), "%s: hole centres keep their place in Orca (%s)" % (name, found))
    return [_at_centre(list(p), normal) for p in positions]
