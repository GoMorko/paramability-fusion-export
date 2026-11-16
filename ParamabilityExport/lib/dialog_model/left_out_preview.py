"""The steps of a picked body that the copy will leave out, as the export dialog shows them before the export runs.
Pure: no Fusion imports.

The list comes from one translation of the capture the dialog already read, with no size tries and no face read. It
holds the steps the translation leaves out for their own reason (a step type the copy has no handler for, a step that
reaches into another component, a refusal of a handler). For the recipe, a step that is a gap only because it picks
faces of one of those waits for the face read of the export, so it is not listed; the preview says more may show
instead (`find`). The Orca translation decides every step it leaves out by itself, so its list is whole (`find_orca`).
Each line reads like the one in the result window after the export (`export_plan.messages.left_out_line`).
"""
from ..results.verdicts import LEFT_OUT
from ..export_plan.messages import left_out_line
from ..package.text import clip

MAX_LISTED = 3
MAX_SHORT_REASON = 110
MORE_MAY_SHOW = "More may show after the export."


class Found:
    """What the translation of one body leaves out: `steps` are `{index, name, reason, hint}` in timeline order (hint
    is "" when the cause has none), `waits_for_faces` is True when a step is left out only because it may pick faces
    of another left out step, which the export decides."""

    def __init__(self, steps=(), waits_for_faces=False):
        self.steps = list(steps)
        self.waits_for_faces = waits_for_faces


def _step(index, record):
    """The step of a left out record (`results.left_out.left_out`)."""
    return {"index": index, "name": record.get("name") or "A step",
            "reason": " ".join(str(record.get("reason") or "").split()), "hint": record.get("hint") or ""}


def _collect(verdicts, records, own, waiting):
    """Fill `own` (`{index: step}`) and `waiting` (a one item list) from the verdicts, tool steps at any depth.
    `records` are the gap records the recipe keeps, by gap id."""
    for verdict in verdicts:
        record = records.get(verdict.get("gap")) if verdict.get("verdict") == LEFT_OUT else None
        if record is not None and verdict.get("cause") == "own":
            own.setdefault(verdict.get("index"), _step(verdict.get("index"), record))
        elif record is not None and verdict.get("cause") == "picks":
            waiting[0] = True
        _collect(verdict.get("tool_steps") or [], records, own, waiting)


def find(result):
    """The `Found` of a translation result whose copy goes on (`result.recipe` is set)."""
    records = {gap.get("id"): gap for gap in result.gaps or []}
    own, waiting = {}, [False]
    _collect(result.items or [], records, own, waiting)
    steps = [own[index] for index in sorted(own, key=lambda i: i if isinstance(i, int) else -1)]
    return Found(steps, waiting[0])


def find_orca(result):
    """The `Found` of an Orca translation result: the steps it left out, in timeline order."""
    steps = [_step(record.get("index"), record) for record in result.left_out]
    steps.sort(key=lambda step: step["index"] if isinstance(step["index"], int) else -1)
    return Found(steps)


def step_text(step, whole=False):
    """The line of one step. The reason is cut for the dialog's box unless `whole` (the tooltip)."""
    reason = step["reason"] if whole else clip(step["reason"], MAX_SHORT_REASON)
    return left_out_line(step["name"], reason, step["hint"])


def lines(found, heading, closing=True):
    """The heading, a line per step (at most MAX_LISTED), how many more, and (with `closing`) that the export may find
    more. Empty when nothing is left out."""
    if not found.steps:
        return []
    out = [heading] + [step_text(step) for step in found.steps[:MAX_LISTED]]
    more = len(found.steps) - MAX_LISTED
    if more > 0:
        out.append("and %d more." % more)
    if closing and found.waits_for_faces:
        out.append(MORE_MAY_SHOW)
    return out
