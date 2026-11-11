"""Which faces and edges a step picks on the body, and which gaps of a walk it may pick them from.

A step that picks geometry a gap would have made cannot be copied either: the copy writes picks as measured points,
which the kernel matches to the closest edge or face, and that geometry is missing from the copy.
"""
# Lists in an item's data that hold bodies, faces made by the step, or faces next to the input: none of them is a pick.
_NOT_PICKS = ("participants", "tools", "sources", "source_bodies", "result_bodies", "bodies", "faces_after",
              "tangent_faces", "made_surfaces", "side_cylinders", "end_points", "elements")


def _is_edge(record):
    return isinstance(record, dict) and bool(record.get("token") or record.get("points"))


def _is_face(record):
    return isinstance(record, dict) and any(record.get(k) for k in ("token", "point", "loops"))


def pick_records(item):
    """`[{ kind, path, record }]`: one entry per edge or face the item picks on the body, in the order of its data.

    These are the picks the copy writes as measured points (`near`), which the kernel matches to the closest edge or
    face: a pick on geometry missing from the copy would land on something else. `kind` is `edge` (an edge record of
    a round or bevel set) or `face` (a shell or offset face, a face input of a round). A face given only by a point on
    it (an emboss face, a face an extrude starts from or reaches to) and a face used as an outline are not picks: the
    copy writes those as measured numbers or shifts, and marks the sizes it cannot follow. `path` is the keys into
    `item["data"]` that lead to `record`, which is the record as the capture holds it."""
    found = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _NOT_PICKS:
                    continue
                if key in ("edges", "faces") and isinstance(value, list):
                    kind, test = ("edge", _is_edge) if key == "edges" else ("face", _is_face)
                    for n, record in enumerate(value):
                        if test(record):
                            found.append({"kind": kind, "path": path + [key, n], "record": record})
                    continue
                walk(value, path + [key])
        elif isinstance(node, list):
            for n, value in enumerate(node):
                walk(value, path + [n])

    data = item.get("data")
    if isinstance(data, dict):
        walk(data, [])
    return found


def picked_gaps(ctx, item):
    """`(gaps, sure)`: the gaps of this walk whose faces `item` picks, or may pick. Empty when the item picks nothing
    or no gap comes before it.

    With the capture's `reach` read, these are the gaps among the steps that made the faces it picks, and `sure` is
    True. A gap the read did not cover (not among the left out steps it was asked about, and not a later picking step
    it tested) may have made any face, so it counts too and `sure` is False. Without the read every gap before the item
    counts."""
    earlier = [gap for gap in ctx.gaps if gap.index is not None and gap.index < item.get("index", 0)]
    if not earlier or not pick_records(item):
        return [], False
    reach = ctx.capture.get("reach")
    read = reach if isinstance(reach, dict) and reach.get("read") is True else {}
    makers, read_for = read.get("makers"), read.get("gaps")
    found = makers.get(str(item.get("index"))) if isinstance(makers, dict) else None
    if not isinstance(found, list) or not isinstance(read_for, list):
        return earlier, False
    unseen = [gap for gap in earlier if gap.index not in read_for and str(gap.index) not in makers]
    return [gap for gap in earlier if gap.index in found or gap in unseen], not unseen
