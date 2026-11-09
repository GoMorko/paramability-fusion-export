"""Result types shared by the driver and the feature handlers."""
from dataclasses import dataclass, field
from typing import Optional


class Refusal:
    """Returned by a handler when its item cannot be copied. `reason` is one plain sentence."""

    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return "Refusal(%r)" % (self.reason,)


VERDICTS = ("translated", "translatedWithNote", "skipped", "unsupported")


def make_verdict(item, verdict, steps=(), note=""):
    return {
        "index": item.get("index"),
        "name": item.get("name", ""),
        "type": item.get("type", ""),
        "verdict": verdict,
        "steps": list(steps),
        "note": note,
    }


@dataclass
class TranslateResult:
    """recipe is None when refusal is set. items lists the verdicts of the items walked, up to the refusal."""

    recipe: Optional[dict] = None
    items: list = field(default_factory=list)
    refusal: Optional[dict] = None
    notes: list = field(default_factory=list)
    fixed: list = field(default_factory=list)  # [{ name, reason }]: sizes that some value could not follow
    raised: list = field(default_factory=list)  # [{ name, min, reason }]: sizes whose smallest value was raised
