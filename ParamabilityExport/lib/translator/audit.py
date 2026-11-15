"""The end of walk audit: every size that a copied step reads ends in a state the person is told about.

A ticked size ends as one of: a free size that a written formula reads (loose when a rule doubts it), fixed with a
reason, or left out of the sizes with a reason. Handlers put a size in one of the last states when they cannot follow
it. A handler that writes a value as a plain number and records nothing leaves the size in no state, so the shape is
wrong at other values with no warning. `audit` finds those sizes; the driver then marks them loose, or leaves them
out with the reason given here.

Every value of a step in its `data.params` is checked on its own: a handler must have dealt with it
(`Context.ask`: `values.quantity`, `values.pin` or `values.handled`), or the sizes it reads end loose.

A size is read by a copied step through the model parameters in its `data.params`, through the dimensions of the
sketches it draws on or the geometry of another component those sketches are drawn around (`table.links`), and
through the construction geometry it uses.

The steps left out of the copy (gaps/stops.py) read sizes the same ways. `Audit.gap_reads` lists them per gap, so the driver
can keep a size that only such a step reads and say why it changes nothing yet.
"""
from ..sketch_values.coverage import MOVED, STILL, ref_answer
from ..sketch_values.motion import Motion
from . import ref_motion
from .notes import step_label, untried_link_reason
from .sizes import construction_fixes, linked_sizes, sketch_answer, sketch_params, sketch_sizes, used_sizes
from .step_walk import all_steps
from .values import reads_in


class Audit:
    """`forgotten`: Fusion name of a free size to why, for each size a copied step reads that has no state.
    `unmoved`: Fusion names of the sizes that copied steps read only through sketches the probe measured, and that did
    not move anything. `unmoved_links`: of those, the ones tied to such a sketch only through another component, with
    that component's name. `gap_reads`: gap id to the Fusion names of the free sizes that left out step reads.
    `follows`: names of the other components whose sizes a copied step follows through a sketch tied to them."""

    def __init__(self):
        self.forgotten = {}
        self.unmoved = set()
        self.unmoved_links = {}
        self.gap_reads = {}
        self.follows = set()


def _sketch_names(node, found):
    """Names of the sketches an item's data refers to, in order."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "sketch" and isinstance(value, str) and value:
                found.setdefault(value, None)
            else:
                _sketch_names(value, found)
    elif isinstance(node, list):
        for value in node:
            _sketch_names(value, found)
    return list(found)


def _param_sizes(table, item, only=None):
    """Fusion names of the free sizes behind the item's `data.params`: what each expression reads, and for one the
    parser cannot read, what Fusion lists for its parameter. `only(path)` picks the values to look at."""
    found = set()
    params = (item.get("data") or {}).get("params")
    for path, ref in (params.items() if isinstance(params, dict) else ()):
        if not isinstance(ref, dict) or not ref.get("expression") or (only and not only(path)):
            continue
        tr = table.translate(ref["expression"])
        found |= set(tr.reads)
        if not tr.ok and not tr.reads:
            found |= table.depends(ref.get("name") or "")
    return found


def _label(item):
    return step_label(item.get("name"), None) or "a step"


def _link_component(table, sketch, name):
    """The name of the other component through which the free size `name` may reach `sketch`."""
    for link in table.links:
        if link["sketch"] == sketch and name in table.depends(link["param"]):
            return link["component"]
    return "another component"


def _only_linked(table, sketch):
    """The free sizes that reach `sketch` through another component and not through its dimensions."""
    dimensions = set()
    for param in sketch_params(table, sketch):
        dimensions |= table.depends(param)
    return set(linked_sizes(table, sketch)) - dimensions


def _references(ctx, table, item, label, named, own, measured, motion, out):
    """The sizes that act on a component whose plane, axis, face or point the step uses (a measured reference) are
    read by the step: one that moves it must be written into the step's formulas or named, one that does not move it changes nothing, and
    without a motion file every one must be named."""
    if getattr(motion, "optimistic", False):
        return
    free = set(table.ticked)
    for entry, names in ref_motion.reaching(ctx, item):
        component = (entry["ref"].get("component") or {}).get("name") or "another component"
        for name in names:
            if name not in free or name in named or name in out.forgotten:
                continue
            answer = ref_answer(table, motion, entry["key"], name) if measured else None
            if answer is not None and answer.kind == STILL:
                out.unmoved.add(name)
                out.unmoved_links.setdefault(name, component)
            elif answer is None or answer.kind != MOVED or name not in own:
                out.forgotten[name] = "%s uses geometry of %s that it moves, and the copy does not follow it" % (
                    label, component)


def _gap_reads(ctx, table, item, measured, motion):
    """Fusion names of the free sizes a left out step reads: through its values, the sketches it names (unless the
    probe measured that a size does not move the sketch), its construction geometry and its measured references."""
    free = set(table.ticked)
    found = _param_sizes(table, item) & free
    for sketch in _sketch_names(item.get("data") or {}, {}):
        for name in sketch_sizes(table, sketch):
            if not (measured and sketch_answer(table, motion, sketch, name).kind == STILL):
                found.add(name)
    for names, _ in construction_fixes(table, item):
        found |= set(names)
    for _, names in ref_motion.reaching(ctx, item):
        found |= set(names)
    return found & free


def audit(capture, ctx, table, named, motion):
    """The `Audit` of one finished walk.

    `ctx` is the walk's `Context` (the recipe steps, which items made them), `table` the size table the walk used (its
    `ticked` are the free sizes), `named` the Fusion names that already have a reason (fixed or doubted), `motion` what
    the probe measured, or None."""
    out = Audit()
    free = set(table.ticked)
    reached = {name for name in free if table.size_name(name) in used_sizes(ctx.steps, table.sizes)}
    measured = isinstance(motion, Motion) and not motion.optimistic
    written = all_steps(ctx.steps)
    for item in ctx.copied_items:
        label = _label(item)
        ids = set(ctx.written_for(item["index"]))
        own = set(reads_in([s for s in written if s["id"] in ids])) if ids else reached
        unasked = _param_sizes(table, item, lambda path: (item.get("index"), path) not in ctx.asked)
        for name in sorted(_param_sizes(table, item) & free):
            if name not in named and (name not in own or name in unasked):
                out.forgotten.setdefault(name, "%s reads it, and the copy does not follow it" % label)
        for sketch in _sketch_names(item.get("data") or {}, {}):
            linked = _only_linked(table, sketch)
            for name in sketch_sizes(table, sketch):
                if name in linked and name in reached and name not in named and measured \
                        and sketch_answer(table, motion, sketch, name).kind == MOVED:
                    out.follows.add(_link_component(table, sketch, name))
                if name in named or name in reached or name in out.forgotten:
                    continue
                if not measured:
                    if motion is None and name in linked:
                        out.forgotten[name] = untried_link_reason(sketch, _link_component(table, sketch, name))
                    continue
                if sketch_answer(table, motion, sketch, name).kind == STILL:
                    out.unmoved.add(name)
                    if name in linked:
                        out.unmoved_links.setdefault(name, _link_component(table, sketch, name))
                else:
                    out.forgotten[name] = "%s reads it through %s, and the copy does not follow it" % (label, sketch)
        for names, _ in construction_fixes(table, item):
            for name in names:
                if name in free and name not in named and name not in reached:
                    out.forgotten.setdefault(name, "%s uses geometry that it moves, and the copy does not follow it" % label)
        _references(ctx, table, item, label, named, own, measured, motion, out)
    for gap in ctx.gaps:
        out.gap_reads[gap.id] = _gap_reads(ctx, table, gap.item, measured, motion)
    out.unmoved -= set(out.forgotten) | named | reached
    out.unmoved_links = {name: c for name, c in out.unmoved_links.items() if name in out.unmoved}
    return out
