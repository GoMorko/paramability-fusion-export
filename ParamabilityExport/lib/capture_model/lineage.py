"""The bodies the exported body comes from, through splits.

A body that a Split Body makes is new in Fusion: the steps before the split built the body it was split from. So the
walk follows that body up to the split, and the split writes the removal of the other side (bodies/split.py). A body split
off from a body that was itself split off is followed back the same way, step by step.

`of(capture)` lists each such split as `(index, parent)`: the timeline index of the split that made the next body of
the chain and the body it split. Which split body a piece came from is read from the split's own record: its only
split body, or the one whose box holds the piece's box. Pure: it reads the capture dict only.
"""
from . import step_kinds
from .capture import outside_component, same_body

# How far (mm) a piece's box may stand out of the box of the body it came from.
BOX_TOL_MM = 1e-3
# A chain longer than this is not followed (a capture never needs more).
MAX_LINKS = 32


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def is_split(item):
    """The item is a step that cuts bodies into pieces (a Split Body)."""
    spec = step_kinds.step_type(item.get("type"))
    return spec is not None and spec.splits_bodies


def _record(records, body):
    return next((r for r in records or () if isinstance(r, dict) and same_body(r, body)), None)


def _holds(outer, inner):
    """True when the box `outer` holds the box `inner`, within BOX_TOL_MM."""
    try:
        return all(outer["min"][i] - BOX_TOL_MM <= inner["min"][i] and inner["max"][i] <= outer["max"][i] + BOX_TOL_MM
                   for i in range(3))
    except (KeyError, TypeError, IndexError):
        return False


def parent_of(item, piece):
    """The body of `item.data.bodies` that the split cut `piece` from, or None when the record cannot tell."""
    data = _data(item)
    split = [b for b in data.get("bodies") or () if isinstance(b, dict)]
    if len(split) == 1:
        return split[0]
    found = _record(data.get("pieces"), piece)
    box = found.get("box") if found else None
    if box is None:
        return None
    holders = [b for b in split if b.get("box") and _holds(b["box"], box)]
    return holders[0] if len(holders) == 1 else None


def _birth(items, body, before):
    """The first item before `before` in the target's component that lists `body` after it but not before it."""
    for item in items:
        if item.get("index", 0) >= before or outside_component(item) or item.get("suppressed"):
            continue
        after, earlier = item.get("bodies_after") or [], item.get("bodies_before")
        if any(same_body(b, body) for b in after) and isinstance(earlier, list) and not any(
                same_body(b, body) for b in earlier):
            return item
    return None


def of(capture):
    """`[(index, parent)]`, by index: each split the exported body comes through, with the body it split. Empty when
    the body was not made by a split, or when a split's record cannot tell which body a piece came from."""
    items = capture.get("items") or []
    body, before, chain = capture.get("target"), float("inf"), []
    while len(chain) < MAX_LINKS:
        made = _birth(items, body, before)
        if made is None or not is_split(made):
            break
        parent = parent_of(made, body)
        if parent is None:
            break
        chain.append((made["index"], {"token": parent.get("token"), "name": parent.get("name")}))
        body, before = parent, made["index"]
    return sorted(chain, key=lambda link: link[0])


def bodies(capture):
    """The bodies of the chain (`of`), oldest first."""
    return [parent for _, parent in of(capture)]


def at(chain, target, index):
    """`(before, after)`: the body of the chain the walk builds just before and just after the item at `index`. They
    differ only at a split of the chain."""
    def holder(strictly):
        return next((parent for at_index, parent in chain if (at_index > index if strictly else at_index >= index)),
                    target)
    return holder(False), holder(True)
