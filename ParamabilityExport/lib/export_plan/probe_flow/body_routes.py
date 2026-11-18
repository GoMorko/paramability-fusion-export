"""Which sizes change the part only by routes the copy follows. Pure: capture dicts and the size table.

A size whose try of its own changes the body but moves no sketch or measured reference the probe follows changes the
part by a route the copy does not model (`SizeProbe._body_only`, `Motion.body_moved`), and the translator marks it.
One route the copy follows never shows in the followed sketches: a value of a step that builds the part (an extrude
distance, a taper angle, a fillet radius). The copy writes that value as a formula of the size. A size that the part
shares with another component meets this case often: a sketch of the part is tied to that component, so the probe
tries the size, and the try changes the body through the part's own values while the tied sketch stays where it is.

`explained` gives the sizes whose body change has such a route, and only when every other way the size can reach
the part is one the probe reads. When in doubt the size is not explained, and the mark stays.
"""
from ...design_model import step_links
from ...design_model.reach import makers_of, value_sizes
from ..body_scope import body_items, tied_body_sketches

# The makers of model parameters whose values the copy follows: a step value written as a formula, and a sketch
# dimension, which the probe reads through its sketch.
_FOLLOWED_MAKERS = ("feature", "sketchDimension")


def explained(capture, table, followed, refs):
    """Fusion names of the ticked sizes whose body change in a try of their own is explained by the values of the
    part's steps. `followed` are the names of the sketches the probe follows, `refs` the keys of the measured
    references it reads. A size is explained when all of these hold:

    - a value of a step that builds the part reads it (`body_scope.body_items`, `reach.value_sizes`);
    - the capture says where it acts (its user parameter lists `dependents`), and it acts on no item that may place an
      occurrence (`step_links.placing`): a joint or a Move may carry the part;
    - every model parameter behind it is a step value or a dimension of a followed sketch (`reach.makers_of`): a
      construction plane, a joint or a maker the capture does not name may move the part without a sketch to show it;
    - every sketch of the part tied to another component is followed (`body_scope.tied_body_sketches`), so a move
      through the geometry of that component would show, and every measured reference that a geometry link of the
      size names is read.

    Empty when the capture does not say which body is picked."""
    try:
        items = body_items(capture)
    except (KeyError, TypeError):
        return set()
    fed = value_sizes(table, items)
    followed = set(followed)
    if not fed or not set(tied_body_sketches(capture)) <= followed:
        return set()
    users = {p.get("name"): p for p in ((capture.get("parameters") or {}).get("user") or []) if isinstance(p, dict)}
    placing = step_links.placing(capture)
    out = set()
    for name in fed:
        param = users.get(name)
        if param is None or "dependents" not in param or name in placing:
            continue
        makers = makers_of(table, name)
        if any(kind not in _FOLLOWED_MAKERS or (kind == "sketchDimension" and sketch not in followed)
               for kind, sketch in makers):
            continue
        if any(link.get("ref") and link["ref"] not in refs for link in table.links_of(name)):
            continue
        out.add(name)
    return out
