"""Corner tools in the Orca recipe: the outlines they are cut from, where their features go, and the copy of a round
or chamfer step as corner tools (`corner_tools` gives the formulas and the checks).

A corner tool must be cut from the body that holds the outline before that body goes into the part, so its
features go back into the list of features, inside the steps that wrote the outline (`Host`):

- an outline built from plane cuts (`outline_cuts`): after the last feature that built the body of the corner's node
  of the half-plane formula (`outline_cuts.Built.marks`), on the outline's own square sketch;
- a rectangle whose width and height follow variables: right after its extrude, on a square sketch of its own. When
  the extrude adds to or cuts from a part that is already there, it starts a body of its own instead, and a Boolean
  after its tools adds it to the part or cuts it away, as the extrude did. Orca's rectangle grows about its centre,
  which keeps its place, so the corners of its tools are that centre plus or less half the width and the height
  (`rectangle_planned`), whatever else moves the rectangle in Fusion (that is told on the parameters' lines already).

Each tool is a body of its own, through all, cut by its lines and drilled by its Hole, then a Boolean cuts it from
the body. The tool body comes and goes between two features, so the index of every body after it stays as it was;
the features after it that read a sketch by its index move up (`_insert`). Every change has its way back in
`Context.undo`, so a step that is left out later puts the recipe back as it was.

The steps of a tool body are written again for each Combine, pattern or mirror that uses it, so one extrude may write
its outline more than once: each writing has a `Host` of its own. `rebuilt` works out the outlines with their corners
at other sizes, for the limits of a later round of a face group of the part (`finishes`).
"""
import math

from ..design_model.dimension_sizes import expr_of, size_env
from ..geometry import vec
from ..orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType, SketchShape
from ..orca_recipe.feature import CadFeature, shift_refs
from ..params.expressions.errors import ExpressionError
from ..sketch_values.expr import num
from . import causes, corner_tools, halfplanes, limits, outline_cuts
from .context import Body, Value
from .formulas import OrcaFormulaError
from .sketches import rectangle_of
from .skip import Skip
from .solid import Prism, Solid

# At most this many Orca features of corner tools on one outline.
MAX_FEATURES = 100
# A corner of the copy and a corner of the outline's formulas are the same corner within this (mm), and so are the
# ends of a curve of the outline as the copy holds it and as its formulas give it.
_SAME_CORNER = 1e-4


class Host:
    """The outline of one copied extrude (timeline index `maker`) with corner tools: its `planned` formulas, its
    sketch `frame`, its `name`, how it goes into the part (`mode`), the `specs` of its tools so far, and where tools
    go (`slots`: node label -> [the feature to write after, the index of the body to cut from, the sketch for the
    tools or None]). `told` holds the limits told for the outline, `count` the tools written (for their names). A
    rectangle keeps its `extrude` and the `scope` body it went into (None when it started that body); `built` is the
    `outline_cuts.Built` of an outline built from cuts. A step may be written more than once (a tool body built for
    a Combine and again for a pattern of it): `key` (the `built` record, or the extrude feature) tells which writing
    of the outline this host belongs to."""

    def __init__(self, maker, key, planned, frame, name, mode):
        self.maker, self.key, self.planned, self.frame, self.name, self.mode = maker, key, planned, frame, name, mode
        self.specs, self.slots, self.told = [], {}, {}
        self.count = 0
        self.built = self.extrude = self.scope = None

    @property
    def rectangle(self):
        return self.built is None


def _frame(prism):
    return {"origin": list(prism.origin), "x": list(prism.x), "y": list(prism.y), "z": list(prism.z)}


def _key(ctx, prism, maker):
    """What tells the writing of the outline of `prism` apart: its `outline_cuts.Built` record (None when it is no
    longer in the copy), or the extrude feature of a rectangle."""
    if prism.built is not None:
        return next((b for b in ctx.cut_built.get(maker) or [] if b.planned is prism.built), None)
    return prism.sketch[1]


def found(ctx, prism, maker):
    """The `Host` of the outline of `prism` (made by step `maker`) when corner tools were cut from it, else None."""
    key = _key(ctx, prism, maker)
    return next((h for h in ctx.corner_hosts.get(maker) or () if key is not None and h.key is key), None)


def hosts_of(ctx, maker):
    """Every `Host` of an outline step `maker` wrote, one for each time the step was written."""
    return list(ctx.corner_hosts.get(maker) or ())


def host_of(ctx, prism, maker, noun):
    """The `Host` of the outline of `prism` (made by step `maker`), made on first use, or a Skip."""
    known = found(ctx, prism, maker)
    if known is not None:
        return known
    if prism.built is not None:
        built = _key(ctx, prism, maker)
        if built is None:
            return Skip("The outline this %s is on is no longer in the Orca copy." % noun, causes.CORNER_CHANGED)
        host = Host(maker, built, built.planned, built.frame, built.name, built.mode)
        host.built, host.told = built, dict(built.told)
        host.slots = {label: [feature, body, built.features[0]] for label, (feature, body) in built.marks.items()}
    else:
        made, extrude = prism.sketch
        planned = rectangle_planned(ctx, made) if prism.slot is not None else None
        if not isinstance(planned, outline_cuts.Planned):
            why = planned or "the copy cuts round corners only from a rectangle"
            names = ", ".join(dict.fromkeys(n for _, (_, reads) in made.bound.items() for n in reads)) or \
                "a variable"
            return Skip("Orca cannot round these corners and keep the sizes that follow %s: %s. The sizes are kept "
                        "and the %s is left out." % (names, why, noun), causes.ROUND_UNBINDS)
        host = Host(maker, extrude, planned, _frame(prism), extrude.name, extrude.mode)
        host.extrude, host.scope = extrude, prism.slot[1]
        host.slots = {"": [extrude, prism.slot[0], None]}
    ctx.corner_hosts.setdefault(maker, []).append(host)

    def back():
        hosts = ctx.corner_hosts.get(maker) or []
        hosts[:] = [h for h in hosts if h is not host]
        if not hosts:
            ctx.corner_hosts.pop(maker, None)
    ctx.undo.append(back)
    return host


def rectangle_planned(ctx, made):
    """The corners of an Orca rectangle (`sketches.SketchOut`) whose width or height follows sizes, as an
    `outline_cuts.Planned`: its centre now plus or less half its width and height, along its sides. None, or why not
    (a plain phrase), when they cannot be written so."""
    if made.shape != "rectangle" or made.source is None or made.source[1] is None:
        return None
    outline, formulas = made.source
    found = rectangle_of(outline.outer)
    if found is None:
        return None
    (cx, cy), (ux, uy), width, height = found
    vx, vy = -uy, ux
    # A size a later check unbound (`limits.guard`) is a number in Orca, so it is one here too.
    bound = {field: entry for field, entry in made.bound.items() if field in made.feature.expr}
    sizes = []
    for field, number in (("width", width), ("height", height)):
        text = (bound.get(field) or (None,))[0]
        try:
            sizes.append(expr_of(text) if text is not None else num(number))
        except ExpressionError:
            return "its %s has a formula the corner tools cannot use" % field
    half_w, half_h = sizes[0] * 0.5, sizes[1] * 0.5
    corners = [(num(cx) + half_w * (a * ux) + half_h * (b * vx), num(cy) + half_w * (a * uy) + half_h * (b * vy))
               for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    env = size_env(ctx.table, {})
    now = [(x.value(env), y.value(env)) for x, y in corners]
    turn = math.degrees(math.atan2(uy, ux))
    sides = [outline_cuts.Side(i, num(turn + 90.0 * i), corners[i]) for i in range(4)]
    planned = outline_cuts.Planned(formulas, corners, sides, halfplanes.formula(now), now)
    planned.bound = bound
    if not planned.fits(env):
        return "its corners do not give the rectangle as drawn"
    return planned


# ---- the features of one tool ----------------------------------------------------------------------------------

def _feature(kind, name, **values):
    return CadFeature(type=kind, name=name, thread_major_nominal=True, pattern_inclusive=True, **values)


def _tool(ctx, host, spec, sketch_ref, body, bind, name):
    """The features of one corner tool: its block, through all on the square sketch at `sketch_ref`; its cuts,
    between two Transforms for each turn they follow; the Hole of a round; and the Boolean that cuts it, body
    `body + 1`, from body `body`. `bind(feature, field, value, where)` writes each value."""
    env = size_env(ctx.table, {})
    origin = [float(c) for c in host.frame["origin"]]
    x, y = vec.unit(list(host.frame["x"])), vec.unit(list(host.frame["y"]))
    axis = vec.unit(vec.cross(x, y))
    where = "%s corners" % host.name
    out = [_feature(FeatureType.EXTRUDE, name, sketch_ref=sketch_ref, extrude_end=ExtrudeEnd.THROUGH_ALL,
                    mode=BooleanMode.NEW)]

    def value(expr):
        return spec.value(expr, host.planned.formulas, env)

    def turn(angle, label):
        made = _feature(FeatureType.TRANSFORM, "%s %s" % (name, label), xf_axis=tuple(ctx.place.direction(axis)),
                        xf_pivot=tuple(ctx.place.point(origin)))
        bind(made, "xf_angle_deg", value(angle), where)
        out.append(made)

    groups = {}
    for angle, offset, what in spec.cuts():
        const, turning = corner_tools.turn_of(angle)
        key = turning.key() if turning is not None else None
        groups.setdefault(key, (turning, []))[1].append((const, offset, what))
    for n, (turning, members) in enumerate(groups.values()):
        if turning is not None:
            turn(-turning, "turn %d" % (n + 1))
        for const, offset, what in members:
            normal = vec.add(vec.scale(x, _cos(const)), vec.scale(y, _sin(const)))
            along = vec.add(vec.scale(x, -_sin(const)), vec.scale(y, _cos(const)))
            plane = ctx.place.plane(origin, along, vec.cross(normal, along), normal)
            made = _feature(FeatureType.CUT, "%s %s" % (name, what), plane=plane, cut_keep_upper=False,
                            cut_keep_lower=True)
            bind(made, "cut_offset", value(offset), where)
            out.append(made)
        if turning is not None:
            turn(turning, "turn back %d" % (n + 1))
    if not spec.chamfer:
        cx, cy = spec.centre()
        hole = _feature(FeatureType.HOLE, "%s arc" % name, plane=ctx.place.plane(origin, x, y, axis), hole_style=0,
                        hole_through=True)
        bind(hole, "hole_x", value(cx), where)
        bind(hole, "hole_y", value(cy), where)
        bind(hole, "hole_diameter", value(spec.r * 2.0), where)
        out.append(hole)
    out.append(_feature(FeatureType.BOOLEAN, "%s cut" % name, mode=BooleanMode.CUT, target_body=body,
                        bool_tool_body=body + 1, bool_keep_tool=False))
    return out


def _cos(degrees):
    return math.cos(math.radians(degrees))


def _sin(degrees):
    return math.sin(math.radians(degrees))


def _square(ctx, host, name):
    """A square sketch around the outline, as large as the block of an outline built from cuts."""
    planned, frame = host.planned, host.frame
    x, y = vec.unit(list(frame["x"])), vec.unit(list(frame["y"]))
    centre = vec.add([float(c) for c in frame["origin"]],
                     vec.add(vec.scale(x, planned.centre[0]), vec.scale(y, planned.centre[1])))
    return _feature(FeatureType.SKETCH, name, shape=SketchShape.RECTANGLE,
                    plane=ctx.place.plane(centre, x, y, vec.unit(vec.cross(x, y))), width=2.0 * planned.half,
                    height=2.0 * planned.half)


def _checked(ctx):
    """A binder that writes the number and checks that Orca can hold the formula, without binding it."""
    def bind(feature, field, value, where):
        setattr(feature, field, value.number)
        if value.formula is not None:
            ctx.orca_formula(value.formula)
    return bind


def _quiet(ctx):
    """A binder for a tool written again (a pattern's tool): it binds the formula without a new line for the
    parameters, as `outline_cuts.again` does."""
    def bind(feature, field, value, where):
        setattr(feature, field, value.number)
        if value.formula is None:
            return
        text = ctx.orca_formula(value.formula)
        feature.bind(field, text)
        ctx.bound.append({"feature": feature.name, "field": field, "formula": text, "reads": list(value.reads)})
    return bind


# ---- writing into the list of features -------------------------------------------------------------------------

def _at(features, feature):
    return next(n for n, f in enumerate(features) if f is feature)


def _insert(ctx, after, build):
    """Insert the features `build(at)` gives right after the feature `after`, `at` being the index the first one
    gets; the features after them that read a feature by its index follow. Returns the features."""
    at = _at(ctx.features, after) + 1
    made = build(at)
    for feature in ctx.features[at:]:
        shift_refs(feature, at, len(made))
    ctx.features[at:at] = made

    def put_back():
        start = _at(ctx.features, made[0])
        del ctx.features[start:start + len(made)]
        for feature in ctx.features[start:]:
            shift_refs(feature, start + len(made), -len(made))

    ctx.undo.append(put_back)
    return made


def _write(ctx, host, specs, noun):
    """Write the tools of `specs` into the recipe, each into its slot. Returns the features."""
    out = []
    for label in dict.fromkeys(spec.label for spec in specs):
        slot = host.slots[label]
        mine = [spec for spec in specs if spec.label == label]
        old = list(slot)
        convert = host.rectangle and slot[2] is None and host.scope is not None

        def build(at, slot=slot, mine=mine, convert=convert):
            made = []
            if slot[2] is None:
                slot[2] = _square(ctx, host, "%s %s sketch" % (host.name, noun))
                made.append(slot[2])
                sketch_ref = at
            else:
                sketch_ref = _at(ctx.features, slot[2])
            for spec in mine:
                host.count += 1
                made += _tool(ctx, host, spec, sketch_ref, slot[1], ctx.bind,
                              "%s %s %d" % (host.name, noun, host.count))
            slot[0] = made[-1]
            if convert:
                made.append(_feature(FeatureType.BOOLEAN, "%s into the part" % host.name, mode=host.mode,
                                     target_body=host.scope, bool_tool_body=slot[1], bool_keep_tool=False))
            return made

        count = host.count
        out += _insert(ctx, old[0], build)
        if convert:
            kept = (host.extrude.mode, host.extrude.target_body)
            host.extrude.mode, host.extrude.target_body = BooleanMode.NEW, -1

            def back_mode(kept=kept):
                host.extrude.mode, host.extrude.target_body = kept
            ctx.undo.append(back_mode)

        def back_slot(slot=slot, old=old, count=count):
            slot[:] = old
            host.count = count
        ctx.undo.append(back_slot)
    return out


# ---- the step ----------------------------------------------------------------------------------------------------

def _specs(ctx, host, item, on, its, chamfer, noun):
    """The `Spec` of each corner `on` (with its measured `_Shape` in `its`), or a Skip."""
    env = size_env(ctx.table, {})
    points = host.planned.points(env)
    n = len(points)
    out = []
    for corner, shape in zip(on, its):
        k = next((k for k, p in enumerate(points) if abs(p[0] - corner.point[0]) <= _SAME_CORNER
                  and abs(p[1] - corner.point[1]) <= _SAME_CORNER), None)
        if k is None:
            return Skip("The Orca copy cannot find the corner of this %s on the outline as its sizes give it, so it "
                        "is left out." % noun, causes.CORNER_TOOLS)
        label = corner_tools.meeting(host.planned.tree, (k - 1) % n, k)
        size = corner.pick.value
        if size.formula is not None:
            try:
                ctx.orca_formula(size.formula)
            except OrcaFormulaError as exc:
                ctx.doubt(size.reads, "%s: its size stays a number in Orca: %s" % (
                    item.get("name") or "the step", str(exc).rstrip(".")))
                size = Value(size.number)
        spec = corner_tools.Spec(host.planned, k, chamfer, size, item.get("index"), label,
                                 len(host.specs) + len(out), corner.pick.by_angle)
        spec.settle(env)
        if label not in host.slots or not corner_tools.agrees(spec, env, shape):
            return Skip("The Orca copy cannot cut this %s so that it gives the corner Fusion makes, so it is left "
                        "out." % noun, causes.CORNER_TOOLS)
        out.append(spec)
    return out


def copy(ctx, item, pieces, chamfer, noun):
    """Cut the corners of a round or chamfer step from the outlines that follow sizes: `pieces` holds, for each such
    outline, `(maker, corners, their shapes)` (`outline_rounds._Corner`, `outline_rounds._Shape`). Returns the
    features written and the `Host` of each outline (in the order of `pieces`), or a Skip; the caller puts the
    redrawn prism into the copy's shape."""
    hosts = []
    for maker, on, its in pieces:
        host = host_of(ctx, on[0].prism, maker, noun)
        if isinstance(host, Skip):
            return host
        specs = _specs(ctx, host, item, on, its, chamfer, noun)
        if isinstance(specs, Skip):
            return specs
        hosts.append((host, specs))
    env = size_env(ctx.table, {})
    found = []
    for host, specs in hosts:
        every = host.specs + specs
        try:
            count = sum(len(_tool(ctx, host, s, 0, 0, _checked(ctx), "")) for s in every)
        except OrcaFormulaError as exc:
            return Skip("Orca cannot write a formula it needs to cut the corners of this %s (%s), so it is left out."
                        % (noun, str(exc).rstrip(".")), causes.CORNER_TOOLS)
        if count > MAX_FEATURES:
            return Skip("Cutting the corners of this %s would take too many Orca steps, so it is left out." % noun,
                        causes.CORNER_TOOLS)
        if not (host.planned.fits(env) and corner_tools.holds(host.planned, every, env)):
            return Skip("Cutting the corners of this %s would not give the corners Fusion makes (a side is too short, "
                        "or the corner lies too near another side), so it is left out." % noun, causes.CORNER_TOOLS)
        walked = corner_tools.walk(ctx, host.planned, every)
        if not isinstance(walked, str) and limits.lineless(ctx, walked):
            walked = ", ".join(limits.lineless(ctx, walked))
        if isinstance(walked, str):
            return Skip("The Orca copy cannot tell how far %s may change with the corners of this %s, so it is left "
                        "out." % (walked, noun), causes.CORNER_TOOLS)
        found.append(walked)
    out = []
    for n, (host, specs) in enumerate(hosts):
        out += _write(ctx, host, specs, noun)
        _tell(ctx, host, found[n])
        kept = list(host.specs)
        host.specs += specs
        ctx.corner_steps.setdefault(item.get("index"), []).append(host)

        def back(host=host, kept=kept, index=item.get("index")):
            host.specs[:] = kept
            held = ctx.corner_steps.get(index) or []
            held[:] = [h for h in held if h is not host]
            if not held:
                ctx.corner_steps.pop(index, None)
        ctx.undo.append(back)
    return out, [host for host, _ in hosts]


def _tell(ctx, host, found):
    """Tell the limits `found` on the parameters' lines, in place of the ones told for the outline before."""
    kept = dict(host.told)
    for variable in found:
        old = host.told.pop(variable, None)
        if old is None:
            continue
        for where in ctx.follows.values():
            if old in where:
                where.remove(old)
    # Every variable of `found` has a parameter line to tell its limits on: `copy` leaves the step out otherwise.
    told, _ = limits.tell_found(ctx, found)
    host.told.update(told)

    def back():
        host.told.clear()
        host.told.update(kept)
    ctx.undo.append(back)


# ---- patterns of an outline with corner tools ------------------------------------------------------------------

def for_again(ctx, maker, built, steps):
    """`{node label: [write(writer)]}` for `outline_cuts.again`: the corner tools cut from the outline `built`
    (`outline_cuts.Built`, written by step `maker`) whose rounds are among the timeline indexes `steps` (all of them,
    `repeats`), written into the tool body being built."""
    host = next((h for h in hosts_of(ctx, maker) if h.key is built), None)
    if host is None:
        return {}
    out, written = {}, [0]
    for spec in host.specs:
        if spec.step not in steps:
            continue

        def write(writer, spec=spec):
            written[0] += 1
            name = "%s corner %d" % (writer.name, written[0])
            body = ctx.scope.index
            made = _tool(ctx, host, spec, writer.sketch_at, body, _quiet(ctx), name)
            tool = ctx.push(Body(None, name))
            for feature in made[:-1]:
                ctx.add(feature)
            ctx.has_body = True
            ctx.pop()
            made[-1].target_body, made[-1].bool_tool_body = body, tool.index
            ctx.add(made[-1])
            ctx.consume(tool)
        out.setdefault(spec.label, []).append(write)
    return out


def repeats(ctx, maker, steps):
    """True when a tool body that repeats the timeline indexes `steps` may repeat step `maker`: every step that cut
    corner tools from its outline is repeated too. Orca's pattern also writes its first copy where the outline is, so
    an outline repeated without its rounds would put the sharp corners back on the original."""
    return all(spec.step in steps for host in hosts_of(ctx, maker) for spec in host.specs)


# ---- the outlines in a body's shape, at other sizes ------------------------------------------------------------

def _host_of_piece(ctx, prism):
    """The `Host` whose corner tools shaped the prism `prism` of a body's shape, or None."""
    for hosts in ctx.corner_hosts.values():
        for host in hosts:
            if not host.specs:
                continue
            if host.built is not None and getattr(prism, "built", None) is host.planned:
                return host
            sketch = getattr(prism, "sketch", None)
            if host.built is None and sketch is not None and sketch[1] is host.extrude:
                return host
    return None


def _same_curve(a, b):
    if a["kind"] != b["kind"] or (a["kind"] == "arc" and abs(a["radius"] - b["radius"]) > _SAME_CORNER):
        return False

    def near(p, q):
        return abs(p[0] - q[0]) <= _SAME_CORNER and abs(p[1] - q[1]) <= _SAME_CORNER
    return (near(a["start"], b["start"]) and near(a["end"], b["end"])) or \
        (near(a["start"], b["end"]) and near(a["end"], b["start"]))


def _same_loop(made, held):
    """True when the curves `made` are the curves `held`, in any order and either way along."""
    if made is None or len(made) != len(held):
        return False
    left = list(held)
    for curve in made:
        match = next((n for n, other in enumerate(left) if _same_curve(curve, other)), None)
        if match is None:
            return False
        del left[match]
    return True


def rebuilt(ctx, solid):
    """`(reads, at)` for the outlines in the shape `solid` (`solid.Solid`) whose corners were cut by corner tools:
    `reads` the Fusion names of the free sizes the outlines and their tools read, and `at(env)` the shape with each
    such outline and its corners worked out at the size values `env` (None when a formula fails there). `((), None)`
    when the shape holds no such outline. None when the copy cannot work them out again: an outline with holes, or
    one whose formulas do not give the outline the shape holds now."""
    held = []
    for n, (mode, prism) in enumerate(getattr(solid, "pieces", None) or []):
        host = _host_of_piece(ctx, prism)
        if host is None:
            continue
        env = size_env(ctx.table, {})
        if len(prism.loops) != 1 or not _same_loop(corner_tools.loop_at(host.planned, host.specs, env),
                                                   prism.loops[0]):
            return None
        held.append((n, mode, prism, host))
    if not held:
        return (), None
    reads = tuple(dict.fromkeys(name for _, _, _, host in held
                                for name in corner_tools.reads(host.planned, host.specs)))

    def at(values):
        pieces = list(solid.pieces)
        for n, mode, prism, host in held:
            loop = corner_tools.loop_at(host.planned, host.specs, values)
            if loop is None:
                return None
            frame = {"origin": prism.origin, "x": prism.x, "y": prism.y, "z": prism.z}
            pieces[n] = (mode, Prism(frame, [loop], prism.low, prism.high))
        return Solid(pieces)
    return reads, at
