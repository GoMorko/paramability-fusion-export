"""Outlines taken from another component's sketch in a step that has no placer to check them against the part.

Bringing such an outline in (dropping `foreign`, naming the component in `borrowed`) is in `design_model/borrowed.py`.
A step that keeps the outline must also keep meeting the part over the size range (`faces/meets_part.py`, run when
the step is added); a sweep or a loft cannot check that, so `mark_unchecked` marks the sizes that may move the sketch.
"""
from ...design_model import borrowed


def mark_unchecked(ctx, item, profile):
    """The outline of a step with no placer that checks it against the part (a sweep, a loft) was taken from another
    component: the sizes that may move that sketch (`borrowed.movers`, kept on the profile when it was brought in) are
    marked, since the copy cannot tell that it still meets the part. The sketch is never looked up by its name, which
    a sketch of the part may share; a profile that was not brought in that way marks every ticked size."""
    if not profile.get("borrowed") or ctx.table is None:
        return
    found = profile.get(borrowed.MOVERS)
    names = [name for name in (ctx.table.ticked if found is None else found) if name in ctx.table.ticked]
    if names:
        ctx.doubt(names, "%s cannot check that its outline from %s still meets the part"
                  % (item.get("name", "a step"), profile.get("sketch") or "another component"))
