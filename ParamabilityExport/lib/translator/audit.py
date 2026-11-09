"""The end of walk audit: every size that a copied step reads ends in a state the person is told about.

A ticked size ends as one of: a free size that a written formula reads (loose when a rule doubts it), fixed with a
reason, or left out of the sizes with a reason. Handlers put a size in one of the last states when they cannot follow
it. A handler that writes a value as a plain number and records nothing leaves the size in no state, so the shape is
wrong at other values with no warning. `audit` finds those sizes; the driver then marks them loose, or leaves them
out with the reason given here.

Every value of a step in its `data.params` is checked on its own: a handler must have dealt with it
(`Context.ask`: `values.quantity`, `values.pin` or `values.handled`), or the sizes it reads end loose.

A size is read by a copied step through the model parameters in its `data.params`, through the dimensions of the
sketches it draws on, and through the construction geometry it uses.
"""
from ..sketch_values.coverage import STILL
from ..sketch_values.motion import Motion
from .notes import step_label
from .sizes import construction_fixes, sketch_answer, sketch_sizes, used_sizes
from .values import reads_in


class Audit:
    """`forgotten`: Fusion name of a free size to why, for each size a copied step reads that has no state.
    `unmoved`: Fusion names of the sizes that copied steps read only through sketches the probe measured, and that did
    not move anything."""

    def __init__(self):
        self.forgotten = {}
        self.unmoved = set()


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


def audit(capture, ctx, table, named, motion):
    """The `Audit` of one finished walk.

    `ctx` is the walk's `Context` (the recipe steps, which items made them), `table` the size table the walk used (its
    `ticked` are the free sizes), `named` the Fusion names that already have a reason (fixed or doubted), `motion` what
    the probe measured, or None."""
    out = Audit()
    free = set(table.ticked)
    reached = {name for name in free if table.size_name(name) in used_sizes(ctx.steps, table.sizes)}
    measured = isinstance(motion, Motion) and not motion.optimistic
    for item in ctx.copied_items:
        label = _label(item)
        ids = set(ctx.steps_of(item["index"]))
        own = set(reads_in([s for s in ctx.steps if s["id"] in ids])) if ids else reached
        unasked = _param_sizes(table, item, lambda path: (item.get("index"), path) not in ctx.asked)
        for name in sorted(_param_sizes(table, item) & free):
            if name not in named and (name not in own or name in unasked):
                out.forgotten.setdefault(name, "%s reads it, and the copy does not follow it" % label)
        for sketch in _sketch_names(item.get("data") or {}, {}):
            for name in sketch_sizes(table, sketch):
                if name in named or name in reached or name in out.forgotten:
                    continue
                if not measured:
                    continue
                if sketch_answer(table, motion, sketch, name).kind == STILL:
                    out.unmoved.add(name)
                else:
                    out.forgotten[name] = "%s reads it through %s, and the copy does not follow it" % (label, sketch)
        for names, _ in construction_fixes(table, item):
            for name in names:
                if name in free and name not in named and name not in reached:
                    out.forgotten.setdefault(name, "%s uses geometry that it moves, and the copy does not follow it" % label)
    out.unmoved -= set(out.forgotten) | named | reached
    return out
