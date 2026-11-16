"""Outlines taken from another component's sketch in a step that has no placer to check them against the part.

Bringing such an outline in (dropping `foreign`, naming the component in `borrowed`) is in `design_model/borrowed.py`.
A step that keeps the outline must also keep meeting the part over the size range (`faces/meets_part.py`, run when
the step is added); a sweep or a loft cannot check that, so `mark_unchecked` marks the sizes of the sketch.
"""
from ...design_model.reach import sketch_sizes


def mark_unchecked(ctx, item, profile):
    """The outline of a step with no placer that checks it against the part (a sweep, a loft) was taken from another
    component: the sizes of that sketch are marked, since the copy cannot tell that it still meets the part."""
    if not profile.get("borrowed") or ctx.table is None:
        return
    names = sketch_sizes(ctx.table, profile.get("sketch") or "")
    if names:
        ctx.doubt(names, "%s cannot check that its outline from %s still meets the part"
                  % (item.get("name", "a step"), profile.get("sketch") or "another component"))
