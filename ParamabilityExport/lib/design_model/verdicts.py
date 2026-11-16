"""One shape for what an output says about a timeline item: its verdict, and the record of a step left out of the copy.

Both outputs (the recipe translator and the Orca translator) build their verdicts and left out records here, so the
dialogs and the report read one shape. Each output adds its own keys after the shared ones: the recipe translator the
steps it wrote and the id of its gap, the Orca translator its cause and the error of a failed step. The words of a
verdict kind differ between the outputs (`TRANSLATED` and `COPIED` both mean a copied step); `LEFT_OUT` and `SKIPPED`
mean the same in both. Pure: no Fusion imports.

Verdict: `{index, name, type, verdict, note}`.
Left out record: `{name, type, reason}` and `hint`, what to change in Fusion so the step copies, when the output has
one for the cause (`capture_model.gap_hints`).
"""
from .words import type_words

TRANSLATED, NOTED, COPIED = "translated", "translatedWithNote", "copied"
SKIPPED, UNSUPPORTED, LEFT_OUT = "skipped", "unsupported", "leftOut"

MAX_NAME = 120


def item_name(item, limit=MAX_NAME):
    """The name of the item, or its type in words when the name is empty or only spaces, or "A step"."""
    return (str(item.get("name") or "").strip()[:limit].strip()
            or type_words(item.get("type") or "").strip() or "A step")


def verdict(item, kind, note="", **extra):
    """The verdict of `kind` about a timeline item, with the keys of the output after the shared ones."""
    return {"index": item.get("index"), "name": item.get("name", ""), "type": item.get("type", ""),
            "verdict": kind, "note": note, **extra}


def left_out(item, reason, hint=None, name_limit=MAX_NAME, type_limit=None, **extra):
    """The record of a step left out of the copy. `hint` is the tip for the person, or None when there is none."""
    kind = str(item.get("type") or "")
    record = {"name": item_name(item, name_limit), "type": kind[:type_limit] if type_limit else kind,
              "reason": reason}
    if hint:
        record["hint"] = hint
    record.update(extra)
    return record
