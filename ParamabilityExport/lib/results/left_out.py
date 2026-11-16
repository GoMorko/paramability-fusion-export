"""The record of a step left out of the copy, in one shape for both outputs: `{name, type, reason}` and `hint`, what
to change in Fusion so the step copies, when the output has one for the cause (`capture_model.gap_hints`). Each output
adds its own keys after the shared ones. Pure: no Fusion imports."""
from ..design_model.words import type_words

MAX_NAME = 120


def item_name(item, limit=MAX_NAME):
    """The name of the item, or its type in words when the name is empty or only spaces, or "A step"."""
    return (str(item.get("name") or "").strip()[:limit].strip()
            or type_words(item.get("type") or "").strip() or "A step")


def left_out(item, reason, hint=None, name_limit=MAX_NAME, type_limit=None, **extra):
    """The record of a step left out of the copy. `hint` is the tip for the person, or None when there is none."""
    kind = str(item.get("type") or "")
    record = {"name": item_name(item, name_limit), "type": kind[:type_limit] if type_limit else kind,
              "reason": reason}
    if hint:
        record["hint"] = hint
    record.update(extra)
    return record
