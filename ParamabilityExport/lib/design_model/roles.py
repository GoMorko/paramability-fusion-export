"""What each timeline item is for the body a walk builds, and which measures of that body apply to it.

A walk builds one body: the exported body, or a tool body of a Combine. When the exported body was made by a Split
Body, the walk builds the body it was split from up to that split (`capture_model.lineage`). `held` lists the bodies
the walk builds around one item, and `role_of` says what the item is for them:

- SUPPRESSED: suppressed in Fusion.
- NOT_A_STEP: a sketch, construction geometry or another item that never changes a body (`step_kinds.skipped`).
- ASSEMBLY: an occurrence, joint or other assembly item. In component coordinates it never changes the shape.
- TOOL_ELSEWHERE: a step of another component that built a tool body of a Combine (`helper_of`). The Combine reads it.
- OTHER_COMPONENT: any other step of another component.
- BUILDS: a step of the body's component that lists a body the walk builds (`touches`).
- HELPER: a step of the body's component that lists no body the walk builds.

The role also gives the body before and after the item, the bodies the item makes that did not exist before it
(`new_bodies`), and whether those are copies of other bodies (`copies_bodies`). The reader measures the exported body
around each item; `seen_on` gives the item with the measures of another body instead. The split facts
(`other_pieces`, `used_later`) say which bodies a Split Body leaves besides the one the walk follows, and which later
step uses one of them together with that body.

These are facts only. Each translator decides from them whether a step is copied, left out or stops the copy.
Pure: it reads capture dicts only.
"""
from dataclasses import dataclass

from ..capture_model import lineage, step_kinds
from ..capture_model.capture import outside_component, renamed_target, same_body
from ..geometry.combine_volume import intersect_model, same_volume

SUPPRESSED, NOT_A_STEP, ASSEMBLY = "suppressed", "notAStep", "assembly"
TOOL_ELSEWHERE, OTHER_COMPONENT = "toolElsewhere", "otherComponent"
BUILDS, HELPER = "builds", "helper"

# What the reader measured on a body itself, under the names the handlers read for their target.
_FIELDS = (("box_before", "target_box_before"), ("volume_before", "volume_before"), ("volume_after", "volume_after"))


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class Role:
    """What an item is for the body a walk builds.

    kind: one of the kinds above. before, after: the body the walk builds just before and just after the item (they
    differ only at a split of the lineage). bodies: every body the walk builds around the item (`held`). touches: the
    item lists one of those bodies (`touches`). new_bodies: the bodies it lists after it that the walk does not build
    and that did not exist before it. copies: the item makes bodies that copy others (`copies_bodies`). changed: the
    reader's `target_changed` (True, False or None). lost: the item lists a body with the target's name under another
    token (`lost`).
    """

    kind: str
    before: dict
    after: dict
    bodies: tuple
    touches: bool
    new_bodies: tuple
    copies: bool
    changed: object
    lost: bool

    @property
    def makes_other(self):
        """The item makes another body that is not a copy of a body (a split piece, a second new body)."""
        return bool(self.new_bodies) and not self.copies


def held(target, chain, index):
    """The bodies a walk of `target` builds around the item at `index`: the target and, with a `lineage` chain, the
    bodies of the chain just before and just after the item."""
    before, after = lineage.at(chain or [], target, index)
    found = [target]
    for body in (before, after):
        if not any(same_body(body, other) for other in found):
            found.append(body)
    return found


def _is_held(body, bodies):
    return any(same_body(body, b) for b in bodies)


def touches(item, bodies):
    """The item lists one of `bodies` among the bodies after it, or its data names one as the body it works on."""
    if any(_is_held(b, bodies) for b in item.get("bodies_after") or []):
        return True
    data = _data(item)
    if _is_held(data.get("target"), bodies) or any(_is_held(b, bodies) for b in data.get("bodies") or []):
        return True
    if data.get("operation") != "newBody":
        return any(_is_held(b, bodies) for b in data.get("participants") or [])
    return False


def existing_bodies(item):
    """Bodies that existed before the item: the reader's `bodies_before`, else the bodies the item's data names."""
    before = item.get("bodies_before")
    if isinstance(before, list):
        return before
    data = _data(item)
    named = list(data.get("participants") or []) + list(data.get("tools") or []) + list(data.get("bodies") or [])
    if data.get("target"):
        named.append(data["target"])
    return named


def new_bodies(item, bodies):
    """Bodies the item lists after it that are not among `bodies` and did not exist before it."""
    existing = existing_bodies(item)
    return [b for b in item.get("bodies_after") or []
            if not _is_held(b, bodies) and not any(same_body(b, e) for e in existing)]


def copies_bodies(item):
    """The item makes bodies that copy others: a Paste, or a pattern or mirror of bodies."""
    spec = step_kinds.step_type(item.get("type"))
    return spec is not None and spec.makes_bodies and _data(item).get("entity_type", "bodies") == "bodies"


def changes_named_bodies(item):
    """The item copies or moves bodies, so one that lists no body may still have changed the part."""
    spec = step_kinds.step_type(item.get("type"))
    return copies_bodies(item) or (spec is not None and spec.moves_bodies)


def lost(item, target):
    """The item lists a body with the target's name under another token: the target may have a new token, so the
    body cannot be followed by token."""
    listed = list(item.get("bodies_after") or []) + list(item.get("bodies_before") or [])
    return any(renamed_target(b, target) for b in listed)


def only_splits_faces(item, bodies):
    """A split of faces that the reader saw leave the body as it was: its solid is the same, only its faces are cut
    up."""
    spec = step_kinds.step_type(item.get("type"))
    return (spec is not None and spec.splits_faces and item.get("target_changed") is False
            and not new_bodies(item, bodies))


def kind_of(item):
    """The kind of the item, before any body is looked at (the first five kinds above), else BUILDS or HELPER by
    `touches`. Returns None for an item of the body's component, whose kind depends on the bodies."""
    if item.get("suppressed"):
        return SUPPRESSED
    if step_kinds.skipped(item.get("type")):
        return NOT_A_STEP
    if step_kinds.is_assembly(item.get("type")):
        return ASSEMBLY
    if outside_component(item):
        return TOOL_ELSEWHERE if item.get("helper_of") else OTHER_COMPONENT
    return None


def role_of(item, target, chain=()):
    """The `Role` of `item` for a walk that builds `target` through the `lineage` chain `chain`."""
    before, after = lineage.at(chain or [], target, item.get("index", 0))
    bodies = held(target, chain, item.get("index", 0))
    hit = touches(item, bodies)
    kind = kind_of(item) or (BUILDS if hit else HELPER)
    copies = copies_bodies(item)
    return Role(kind, before, after, tuple(bodies), hit, tuple(new_bodies(item, bodies)), copies,
                item.get("target_changed"), lost(item, target))


# ---- the measures of another body ---------------------------------------------------------------------------------

def measured(item, body):
    """True when the reader measured `body` around the item."""
    return isinstance((item.get("body_states") or {}).get((body or {}).get("token")), dict)


def seen_on(item, body, exported=False):
    """The item as a walk of `body` reads it: in the body's component, with what was measured on the body itself.
    What the capture says about the exported body does not apply to another body: without measures of it the fields
    are null (also the item's `target_before` and `target_after`), so handlers skip the checks that need them.
    `exported` is True when `body` is the exported body, whose measures are on the item already."""
    data = item.get("data")
    state = (item.get("body_states") or {}).get(body.get("token"))
    state = state if isinstance(state, dict) else {}
    seen = dict(item, in_target_component=True)
    if not exported:
        if isinstance(data, dict):
            data = dict(data, **{field: state.get(key) for key, field in _FIELDS})
            if "intersect_volumes" in data:
                data["intersect_model"] = intersect_model(data["intersect_volumes"], data["volume_after"])
        seen.update(target_before=None, target_after=None)
    before, after = state.get("volume_before"), state.get("volume_after")
    unchanged = before is not None and after is not None and same_volume(before, after)
    seen.update(data=data, target_changed=False if unchanged else None)
    return seen


def seen_before_split(item, target, chain):
    """Before the split that made `target`, an item of the body it was split from is read with what the reader
    measured on that body (`seen_on`). The split itself, a step of another component and an item the reader did not
    measure on that body are read as they are."""
    if not chain or lineage.is_split(item) or outside_component(item):
        return item
    before = lineage.at(chain, target, item.get("index", 0))[0]
    if same_body(before, target) or not measured(item, before):
        return item
    return seen_on(item, before)


# ---- the pieces of a split ----------------------------------------------------------------------------------------

def listed(item):
    """The bodies an item changes or works on, without the tools of a Combine."""
    data = _data(item)
    found = list(item.get("bodies_after") or [])
    found += [data.get("target")] if isinstance(data.get("target"), dict) else []
    for key in ("participants", "bodies", "source_bodies"):
        found += [b for b in data.get(key) or () if isinstance(b, dict)]
    return found


def other_pieces(item, before, kept):
    """The bodies a split leaves besides `kept`: those it lists after it, and every piece of `before`, the body it
    split."""
    pieces = [p for p in _data(item).get("pieces") or () if isinstance(p, dict)
              and same_body(lineage.parent_of(item, p) or {}, before)]
    found = []
    for body in list(item.get("bodies_after") or []) + pieces:
        if not same_body(body, kept) and not any(same_body(body, other) for other in found):
            found.append(body)
    return found


def used_later(timeline, item, body, target, chain=()):
    """The first later item of the target's component that changes or works on `body` together with a body the walk
    of `target` builds (`held`), else None. A later split of `body` is not such a use: its own pieces are a matter of
    that split."""
    for later in timeline:
        if later.get("index", 0) <= item.get("index", 0) or later.get("suppressed") or outside_component(later):
            continue
        if lineage.is_split(later):
            continue
        found = listed(later)
        if any(same_body(b, body) for b in found) and any(
                same_body(b, h) for b in found for h in held(target, chain, later.get("index", 0))):
            return later
    return None
