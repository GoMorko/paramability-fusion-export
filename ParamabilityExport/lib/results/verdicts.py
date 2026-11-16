"""The verdict of a timeline item, in one shape for both outputs (the recipe translator and the Orca translator), so
the dialogs and the report read one shape. Each output adds its own keys after the shared ones: the recipe translator
the steps it wrote and the id of its gap, the Orca translator its cause and the error of a failed step. The words of a
verdict kind differ between the outputs (`TRANSLATED` and `COPIED` both mean a copied step); `LEFT_OUT` and `SKIPPED`
mean the same in both. Pure: no Fusion imports.

Verdict: `{index, name, type, verdict, note}`.
"""

TRANSLATED, NOTED, COPIED = "translated", "translatedWithNote", "copied"
SKIPPED, UNSUPPORTED, LEFT_OUT = "skipped", "unsupported", "leftOut"


def verdict(item, kind, note="", **extra):
    """The verdict of `kind` about a timeline item, with the keys of the output after the shared ones."""
    return {"index": item.get("index"), "name": item.get("name", ""), "type": item.get("type", ""),
            "verdict": kind, "note": note, **extra}
