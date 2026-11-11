"""The extra look at a part whose first translation left steps out. Pure: no Fusion imports.

A later round, chamfer or shell that picks edges or faces of a left out step would pick something else in the copy.
Fusion is asked which step made the faces each later step picks (`fusion_reader.read_gap_reach`), the answer goes into
the capture as `reach`, and the part is translated again: only a step that picks faces of a left out step is left out
too. Without the answer the translator leaves out every later step that picks geometry.

The read is asked about the steps left out for their own reason, also inside tool bodies. A step left out only because
it may pick faces of another gap is not one of them: the read tests it as a picking step instead.
"""


def _own_gaps(verdicts):
    for verdict in verdicts:
        if verdict.get("verdict") == "leftOut" and verdict.get("cause") != "picks":
            yield verdict.get("index")
        yield from _own_gaps(verdict.get("tool_steps") or [])


def left_out_indexes(result):
    """Timeline indexes of the steps a translation left out for their own reason, at any depth, in order."""
    return sorted({i for i in _own_gaps(result.items) if isinstance(i, int) and not isinstance(i, bool)})


def _usable(reach):
    return isinstance(reach, dict) and isinstance(reach.get("read"), bool)


def with_reach(read, capture, result, log):
    """`capture` with the `reach` of the steps `result` left out, or `capture` itself when `result` left none out.

    `read(capture, indexes)` asks Fusion. A failed read gives `{ read: false, error }`, which the translator takes
    on the safe side. Only a timeline marker that could not be put back is raised, and it stops the export."""
    indexes = left_out_indexes(result) if result is not None and result.recipe is not None else []
    if not indexes:
        return capture
    reach = read(capture, indexes)
    if not _usable(reach):
        log("reach read gave no answer")
        reach = {"read": False, "error": "The reach was not read."}
    return {**capture, "reach": reach}
