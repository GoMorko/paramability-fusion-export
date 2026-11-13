"""When the walk may copy a step that leaves more than one body.

Such a step stops the copy, since later steps may belong to the other body and no single missing step can stand for
it. A Split Body is the exception when the body the walk builds comes out of it as one piece and the other pieces stay
apart from it: nothing after the split puts them back into it or changes them together with it (a later Combine may
still take one as a tool, which its own handler checks). The split then becomes the removal of the other side
(split.py). Pure: it reads the capture dict only.
"""
from ..capture_model import lineage
from ..capture_model.capture import outside_component, same_body

ANOTHER_BODY = "This step splits the part or makes another body, which is not copied yet."
NOT_READ = ("What this split cuts with was not read. Exporting again with this version of the add-in reads it.")


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _listed(item):
    """The bodies an item changes or works on, without the tools of a Combine."""
    data = _data(item)
    found = list(item.get("bodies_after") or [])
    found += [data.get("target")] if isinstance(data.get("target"), dict) else []
    for key in ("participants", "bodies", "source_bodies"):
        found += [b for b in data.get(key) or () if isinstance(b, dict)]
    return found


def _holds(ctx, index):
    """The bodies the walk builds around the item at `index`."""
    return [ctx.target, *ctx.lineage_at(index)]


def used_later(ctx, item, body):
    """The first later item of the target's component that changes or works on `body` together with the body the
    walk builds, else None. A later split of `body` is not such a use: its own pieces are checked at that split."""
    for later in ctx.timeline:
        if later.get("index", 0) <= item.get("index", 0) or later.get("suppressed") or outside_component(later):
            continue
        if lineage.is_split(later):
            continue
        listed = _listed(later)
        if any(same_body(b, body) for b in listed) and any(
                same_body(b, held) for b in listed for held in _holds(ctx, later.get("index", 0))):
            return later
    return None


def is_split(item):
    return lineage.is_split(item)


def _other_pieces(item, ctx, kept):
    """The bodies the split leaves besides `kept`: those it lists after it, and every piece of the body it split."""
    before = ctx.lineage_at(item.get("index", 0))[0]
    pieces = [p for p in _data(item).get("pieces") or () if isinstance(p, dict)
              and same_body(lineage.parent_of(item, p) or {}, before)]
    found = []
    for body in list(item.get("bodies_after") or []) + pieces:
        if not same_body(body, kept) and not any(same_body(body, other) for other in found):
            found.append(body)
    return found


def stop_reason(item, ctx):
    """None when the walk may run the split handler on `item`, a step that leaves more than one body; else the reason
    the copy stops."""
    if not lineage.is_split(item):
        return ANOTHER_BODY
    if not isinstance(_data(item).get("tool"), dict):
        return NOT_READ
    kept = ctx.lineage_at(item.get("index", 0))[1]
    after = item.get("bodies_after") or []
    if not any(same_body(b, kept) for b in after):
        return ANOTHER_BODY
    for body in _other_pieces(item, ctx, kept):
        later = used_later(ctx, item, body)
        if later is not None:
            return ("%s changes %s, another piece of this split, together with the part. That is not copied yet."
                    % (later.get("name") or "A later step", body.get("name") or "a body"))
    return None
