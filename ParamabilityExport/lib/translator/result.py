"""Result types shared by the driver and the feature handlers."""
from dataclasses import dataclass, field
from typing import Optional


class Refusal:
    """Returned by a handler instead of a `StepResult` when its item cannot be copied. `reason` is one plain
    sentence."""

    def __init__(self, reason):
        self.reason = reason
        self.doubts = []

    def __repr__(self):
        return "Refusal(%r)" % (self.reason,)


class Doubt:
    """A value that cannot follow some sizes, so it is written as its number.

    names: the Fusion names of the sizes. why: the end of the reason (a `notes.Past` when it holds past some values).
    step: the timeline index of the item being copied, or None for a check on the whole recipe. fixed: the value would
    make the recipe unusable while the sizes stay free, so they become fixed numbers; otherwise they stay free with a
    warning (loose).
    """

    def __init__(self, names, why, step=None, fixed=False):
        self.names = tuple(names)
        self.why = why
        self.step = step
        self.fixed = fixed

    def __repr__(self):
        return "Doubt(%r, %r)" % (self.names, str(self.why))


class Entry:
    """One recipe step a handler writes, with what the walk keeps about it once the step has its id.

    placers: placer makers (`placer_makers.py`): each makes the placers that let later picks on the faces this step
      makes follow sizes (`make(ctx, step_id, step)`).
    picks: for a round or bevel step, { near, reads, written }: its edges as measured points, the sizes its pick
      follows and the written points (None when the pick names a step). Patterns and mirrors copy these points.
    repeatable: False when Fusion recomputes the step's length per copy (it reaches to a face or through the part),
      so patterns and mirrors refuse it as a source.
    label: the step's label when it is not the name of its item (a tool step is named after its tool).
    """

    def __init__(self, step, placers=(), picks=None, repeatable=True, label=None):
        self.step = step
        self.placers = list(placers)
        self.picks = picks
        self.repeatable = repeatable
        self.label = label


class StepResult:
    """What a handler hands back for its item: the recipe steps it writes (`entries`, in order).

    An empty result means the item makes no step on purpose. The walk fills `doubts` (`Doubt` records: the sizes a
    value of these steps cannot follow) and `notes` (plain sentences for the item's verdict) with what the handler
    recorded on the context. `items` are capture items of other bodies whose steps these steps carry (the tool body of
    a Combine); they count as copied once these steps are written. `asked` is the set of `(item index, params path)`
    the handlers dealt with (`values.quantity`, `values.pin`, `values.handled`); the audit compares it with each
    item's `data.params`. `tool_steps` are the verdicts of the items inside the tool steps written here.
    """

    def __init__(self, entries=()):
        self.entries = list(entries)
        self.doubts = []
        self.notes = []
        self.items = []
        self.asked = set()
        self.tool_steps = []

    @classmethod
    def of(cls, steps):
        """A result of plain steps: no placers, no picks, every step repeatable."""
        return cls(Entry(step) for step in steps)

    @property
    def steps(self):
        return [entry.step for entry in self.entries]

    def add(self, step, placers=(), picks=None, repeatable=True, label=None):
        """Write `step`; returns it."""
        self.entries.append(Entry(step, placers, picks, repeatable, label))
        return step

    def extend(self, entries):
        self.entries.extend(entries)
        return self

    def join(self, other):
        """Take on the doubts and items of `other`, the result of another body whose steps these steps carry."""
        self.doubts.extend(other.doubts)
        self.items.extend(other.items)
        self.asked |= other.asked


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
    loose: list = field(default_factory=list)  # [{ name, reason }]: sizes kept free although some value cannot follow
    # [{ name, reason, used }]: ticked parameters that are not sizes of the recipe, with the plain reason. `used` is
    # True when a copied step reads the parameter and the copy cannot follow it, False when nothing copied depends on it.
    dropped: list = field(default_factory=list)
