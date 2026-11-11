"""The extra look at a part whose first translation left steps out. Pure: no Fusion imports.

A later round, chamfer or shell that picks edges or faces of a left out step would pick something else in the copy.
Fusion is asked which step made the faces each later step picks (`fusion_reader.read_gap_reach`), the answer goes into
the capture as `reach`, and the part is translated again: only a step that picks faces of a left out step is left out
too. Without the answer the translator leaves out every later step that picks geometry.
"""


def left_out_indexes(result):
    """Timeline indexes of the steps a translation left out, in order."""
    found = [item.get("index") for item in result.items if item.get("verdict") == "leftOut"]
    return [i for i in dict.fromkeys(found) if isinstance(i, int) and not isinstance(i, bool)]


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
