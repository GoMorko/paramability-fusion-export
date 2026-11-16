"""The recipe `sizes` and the sizes that cannot follow, around the size table.

The size table lists every size the person ticked. The recipe keeps only the sizes that a written formula reads, and
the sizes those formulas read in turn. A size that moves a joint cannot be followed. Sketch values follow sizes through
the probe's motion file; without one, no size that moves a sketch or construction geometry can be followed, and with
one, neither can a size behind a sketch the probe did not measure (`sketch_answer`). The driver keeps such sizes free
with a warning (`translate`).

Which sizes reach a sketch, a plane, a face or a joint is shared with the Orca output (`design_model/reach.py`). What
stays here is the recipe's own: how the motion file answers (`sketch_answer`, `unmeasured_sizes`), the sizes it does
not try (`untried_reasons`, `construction_only`), the words of a sketch text (`text_reasons`) and the sizes the
written steps read (`used_sizes`).
"""
from ..design_model.reach import STATIC_KINDS, placed_offsets, reasons, sketch_sizes, text_sizes
from ..params.expressions.formula import tokenize_formula
from ..sketch_values.coverage import MOVED, NOT_MEASURED, NOT_TRIED, STILL, Answer, tried
from ..sketch_values.motion import Affine, Stuck, Terms


def untried_reasons(table):
    """{ Fusion name: why } for each ticked size that a sketch dimension, construction plane or axis, or joint
    reads. Used when the export could not try sketches at other values, so their numbers stay as measured."""
    return reasons(table, tuple(STATIC_KINDS),
                    lambda what: "it changes %s, which could not be tried at other values" % what)


def text_reasons(table, capture):
    """{ Fusion name: why } for each ticked size that reaches a parameter of a sketch text (its height). The copy
    keeps the letters as outlines at their current size, so such a size cannot follow."""
    return {size: "it changes the size of the text in %s, which is copied as it is now" % sketch
            for size, sketch in text_sizes(table, capture).items()}


def construction_only(table, capture):
    """Fusion names of the ticked sizes whose every use is the own distance of an offset plane that a step places
    (`placed_offsets`): no other model parameter reads them, and no geometry of another component. They move that
    plane alone, and the step follows it (or marks them when the measured plane does not match), in table order."""
    followed = placed_offsets(table, capture)
    other = set()
    for m in table.model_params.values():
        if m["name"] not in followed:
            other |= table.depends(m["name"])
    for link in table.links:
        other |= table.depends(link["param"])
    reached = set()
    for name in followed:
        reached |= table.depends(name)
    return [name for name in table.ticked if name in reached and name not in other]


def _driven(table, value):
    """Fusion names of the free sizes behind a motion value (an Affine's terms, a Stuck's movers and its rest)."""
    if isinstance(value, Stuck):
        names = set(value.movers) | (set(value.rest.terms) if value.rest is not None else set())
    elif isinstance(value, Affine):
        names = set(value.terms)
    elif isinstance(value, Terms):
        names = set(value.names())
    else:
        names = set()
    out = set()
    for name in names:
        out |= table.depends(name)
    return out


def sketch_answer(table, motion, sketch, size):
    """What the motion file says about size `size` (a Fusion name) and the sketch named `sketch`: an `Answer` of
    `STILL`, `MOVED` or `NOT_MEASURED`. A size the sketch does not read (`sketch_sizes`) cannot move it, so it is
    still whatever the probe did."""
    if size not in sketch_sizes(table, sketch):
        return Answer(STILL)
    reason = getattr(motion, "unmeasured", {}).get(sketch)
    if reason:
        return Answer(NOT_MEASURED, reason=reason)
    if size in getattr(motion, "untried", ()) or not tried(motion, size):
        return Answer(NOT_MEASURED, reason=NOT_TRIED)
    moved = [key for key, value in motion.values.items()
             if getattr(value, "sketch", "") == sketch and size in _driven(table, value)]
    return Answer(MOVED, moved) if moved else Answer(STILL)


def unmeasured_sizes(table, motion, sketch):
    """Fusion names of the free sizes whose effect on the sketch named `sketch` the probe did not measure."""
    if not getattr(motion, "unmeasured", {}).get(sketch):
        return []
    return [size for size in sketch_sizes(table, sketch)
            if sketch_answer(table, motion, sketch, size).kind == NOT_MEASURED]


def _identifiers(node, found):
    if isinstance(node, dict):
        expr = node.get("expr")
        if isinstance(expr, str):
            found.update(tok[1] for tok in tokenize_formula(expr) if tok[0] == "id")
        for value in node.values():
            _identifiers(value, found)
    elif isinstance(node, list):
        for value in node:
            _identifiers(value, found)


def used_sizes(features, sizes):
    """The entries of `sizes` (recipe name to size dict) that the written steps read, directly or through formulas."""
    wanted = set()
    _identifiers(features, wanted)
    used = {}
    pending = [name for name in sizes if name in wanted]
    while pending:
        name = pending.pop()
        if name in used:
            continue
        used[name] = sizes[name]
        reads = set()
        _identifiers({"expr": sizes[name].get("expr")}, reads)
        pending.extend(n for n in sizes if n in reads and n not in used)
    return {name: used[name] for name in sizes if name in used}
