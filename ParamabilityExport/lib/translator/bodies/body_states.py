"""An item seen from a body other than the exported one, with what the reader measured on that body.

The feature readers measure the exported body around each item (`volume_before`, `target_box_before`,
`target_changed`). A walk of a tool body, and the walk of the exported body before the split that made it, build
another body: the reader's `body_states[token]` holds that body's box and volumes around the item instead.
"""
from ...geometry.combine_volume import intersect_model, same_volume

# What the reader measured on the body itself, under the names the handlers read for their target.
_FIELDS = (("box_before", "target_box_before"), ("volume_before", "volume_before"), ("volume_after", "volume_after"))


def measured(item, body):
    """True when the reader measured `body` around the item."""
    return isinstance((item.get("body_states") or {}).get((body or {}).get("token")), dict)


def seen_on(item, body, exported=False):
    """The item as a walk of `body` reads it: in the body's component, with what was measured on the body itself. What
    the capture says about the exported body does not apply to another body: without measures of it the fields are
    null, so handlers refuse or skip their checks. `exported` is True when `body` is the exported body."""
    data = item.get("data")
    state = (item.get("body_states") or {}).get(body.get("token"))
    state = state if isinstance(state, dict) else {}
    if isinstance(data, dict) and not exported:
        data = dict(data, **{field: state.get(key) for key, field in _FIELDS})
        if "intersect_volumes" in data:
            data["intersect_model"] = intersect_model(data["intersect_volumes"], data["volume_after"])
    before, after = state.get("volume_before"), state.get("volume_after")
    unchanged = before is not None and after is not None and same_volume(before, after)
    return dict(item, data=data, in_target_component=True, target_changed=False if unchanged else None)
