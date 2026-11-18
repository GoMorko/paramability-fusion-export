"""The extra look at a part whose first translation left steps out. Pure: no Fusion imports.

A later round, chamfer or shell that picks edges or faces of a left out step would pick something else in the copy.
Fusion is asked which step made the faces each later step picks (`fusion_reader.read_gap_reach`), the answer goes into
the capture as `reach`, and the part is translated again: only a step that picks faces of a left out step is left out
too. Without the answer the translator leaves out every later step that picks geometry.

The read also runs when the first translation stopped only because the part holds more gaps than it may
(`TranslateResult.over_gap_cap`): the later picking steps that the read clears may bring it under the cap. The cap
applies to the translation that uses the answer.

The read is asked about the steps left out for their own reason, also inside tool bodies, and about the steps written
only in part (a round with one set of edges left out). A step left out only because it may pick faces of another gap
is not one of them: the read tests it as a picking step instead.
"""
from ..results.verdicts import LEFT_OUT


def _own_gaps(verdicts):
    for verdict in verdicts:
        # A step written in part has its gap too (`gap`, cause `own`).
        if (verdict.get("verdict") == LEFT_OUT or verdict.get("gap")) and verdict.get("cause") != "picks":
            yield verdict.get("index")
        yield from _own_gaps(verdict.get("tool_steps") or [])


def left_out_indexes(result):
    """Timeline indexes of the steps a translation left out for their own reason, at any depth, in order."""
    return sorted({i for i in _own_gaps(result.items) if isinstance(i, int) and not isinstance(i, bool)})


def needs_reach(result):
    """True when a translation left steps out, or stopped because the part holds more gaps than it may: later picking
    steps count as gaps until the reach is read, so the read may bring the part under the cap."""
    return result is not None and bool(result.gaps or result.over_gap_cap)


def _usable(reach):
    return isinstance(reach, dict) and isinstance(reach.get("read"), bool)


def with_reach(read, capture, result, log):
    """`capture` with the `reach` of the steps `result` left out, or `capture` itself when `result` needs none
    (`needs_reach`) or left none out.

    `read(capture, indexes)` asks Fusion. A failed read gives `{ read: false, error }`, which the translator takes
    on the safe side. Only a timeline marker that could not be put back is raised, and it stops the export."""
    indexes = left_out_indexes(result) if needs_reach(result) else []
    if not indexes:
        return capture
    reach = read(capture, indexes)
    if not _usable(reach):
        log("reach read gave no answer")
        reach = {"read": False, "error": "The reach was not read."}
    elif reach["read"] is False:
        log("reach read failed: %s" % reach.get("error"))
    return {**capture, "reach": reach}
