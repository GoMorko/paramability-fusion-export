"""Sizes that move a part which stays a fixed shape in a parts file. Pure: no Fusion imports.

A recipe part follows the sizes of its sketches. A part without a recipe is a copy of the STEP at the current values, so
a size that moves it moves only the other parts when somebody changes it in the app. Such a size is marked loose, with
the fixed parts named, so the person knows the fit may break.
"""
from ..package.manifest import MAX_FIXED_REASON
from ..package.text import clip
from . import body_scope
from .part_names import parts_label


def _own_names(capture):
    """Fusion names of the parameters whose value can change the picked body: its model parameters, the user
    parameters its sketches reach through other components, and the parameters behind its pattern counts."""
    try:
        model, quantities = body_scope.scope_inputs(capture)
        names = [p["name"] for p in model] + [q["name"] for q in quantities]
        return names + [link["param"] for link in body_scope.body_links(capture)]
    except (KeyError, TypeError):
        # A capture that does not say which body is picked: every parameter it read may move the part.
        params = capture.get("parameters") or {}
        return [p["name"] for p in (params.get("model") or []) + (params.get("user") or []) if p.get("name")]


def sizes_reaching(size_table, capture):
    """Recipe names of the free sizes of `size_table` that move the picked body of `capture`, in table order."""
    reaching = set()
    for name in _own_names(capture):
        reaching |= size_table.depends(name)
    return [size_table.recipe_name(name) for name in size_table.ticked if name in reaching]


def _reason(names):
    if len(names) == 1:
        return "%s stays a fixed shape in this file and does not change with this size." % names[0]
    return "%s stay fixed shapes in this file and do not change with this size." % parts_label(names)


def marked(size_table, fixed_parts, free):
    """`[{ name, reason }]`: each size in `free` that moves a part without a recipe, once, with the parts named.
    `fixed_parts` is `[(part name, capture dict)]` of the parts that are fixed shapes."""
    moved = {}
    for part, capture in fixed_parts:
        for name in sizes_reaching(size_table, capture):
            if name in free:
                moved.setdefault(name, []).append(part)
    return [{"name": name, "reason": clip(_reason(parts), MAX_FIXED_REASON)} for name, parts in moved.items()]


def joined(loose, extra):
    """`loose` with the entries of `extra` added: a size that is loose already gets the new reason in front of its own,
    so the fixed part is named even when the cut to the manifest limit shortens the old reason."""
    out = [dict(e) for e in loose]
    at = {e["name"]: e for e in out}
    for entry in extra:
        if entry["name"] in at:
            found = at[entry["name"]]
            found["reason"] = clip("%s %s" % (entry["reason"], found["reason"]), MAX_FIXED_REASON)
        else:
            out.append(dict(entry))
            at[entry["name"]] = out[-1]
    return out
