"""When the walk may copy a step that leaves more than one body.

Such a step stops the copy, since later steps may belong to the other body and no single missing step can stand for
it. A Split Body is the exception when the body the walk builds comes out of it as one piece and the other pieces stay
apart from it: nothing after the split puts them back into it or changes them together with it (a later Combine may
still take one as a tool, which its own handler checks). The split then becomes the removal of the other side
(bodies/split.py). Which pieces a split leaves and which later step uses one are facts of the shared layer
(`design_model/roles.py`, `other_pieces`, `used_later`); this module turns them into the stop. Pure: it reads the
capture dict only.
"""
from ...capture_model import lineage
from ...capture_model.capture import same_body
from ...design_model import roles

ANOTHER_BODY = "This step splits the part or makes another body, which is not copied yet."
NOT_READ = ("What this split cuts with was not read. Exporting again with this version of the add-in reads it.")


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def is_split(item):
    return lineage.is_split(item)


def stop_reason(item, ctx):
    """None when the walk may run the split handler on `item`, a step that leaves more than one body; else the reason
    the copy stops."""
    if not lineage.is_split(item):
        return ANOTHER_BODY
    if not isinstance(_data(item).get("tool"), dict):
        return NOT_READ
    before, kept = ctx.lineage_at(item.get("index", 0))
    after = item.get("bodies_after") or []
    if not any(same_body(b, kept) for b in after):
        return ANOTHER_BODY
    for body in roles.other_pieces(item, before, kept):
        later = roles.used_later(ctx.timeline, item, body, ctx.target, ctx.lineage)
        if later is not None:
            return ("%s changes %s, another piece of this split, together with the part. That is not copied yet."
                    % (later.get("name") or "A later step", body.get("name") or "a body"))
    return None
