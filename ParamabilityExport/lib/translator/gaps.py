"""Steps the walk leaves out of the copy (gaps), and what it records about each one.

A gap is a step that the copy cannot hold but whose effect stays on the body: the rest of the timeline still reads
right without it. The record names the step, says why it is missing and where it belongs in the recipe, and keeps the
step's Fusion data, so the missing step can be added to the copy later.

The walk records a `Gap` with the ids of the steps it wrote before it. Where the gap belongs is worked out once the
recipe is final (`place_all`), since later steps can move what was written into a tool step.
"""
import copy
import json
import math

from ..package.text import clip
from . import notes as wording
from .words import type_words

MAX_GAPS = 16
MAX_ID = 64
MAX_NAME = 120
MAX_WORDS = 64
MAX_VALUES = 64
MAX_EXPRESSION = 300
MAX_PATH = 200
MAX_DATA_BYTES = 48 * 1024
MAX_SAMPLES = 200
MAX_LOOPS = 8
MAX_MEASURE = 1e6

# Lists in an item's data that hold bodies, faces made by the step, or faces next to the input: none of them is a pick.
_NOT_PICKS = ("participants", "tools", "sources", "source_bodies", "result_bodies", "bodies", "faces_after",
              "tangent_faces", "made_surfaces", "side_cylinders", "end_points", "elements")


def _is_edge(record):
    return isinstance(record, dict) and bool(record.get("token") or record.get("points"))


def _is_face(record):
    return isinstance(record, dict) and any(record.get(k) for k in ("token", "point", "face_point", "loops"))


def pick_records(item):
    """`[{ kind, path, record }]`: one entry per geometry the item picks on the body, in the order of its data.

    `kind` is `edge` (an edge record of a round or bevel set), `face` (a face record: shell and offset faces, the face
    inputs of a round, the faces of an emboss, a face used as an outline) or `point` (any other record that picks a
    face by a point on it, such as a face an extrude starts from or reaches to). `path` is the keys into `item["data"]`
    that lead to `record`, which is the record as the capture holds it."""
    found = []

    def walk(node, path):
        if isinstance(node, dict):
            if node.get("face") is True and path[-2:-1] == ["profiles"]:
                found.append({"kind": "face", "path": path, "record": node})
                return
            if node.get("face_point") is not None:
                found.append({"kind": "point", "path": path, "record": node})
                return
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


class Gap:
    """A step left out of the copy.

    item: the capture item as the walk saw it. reason: why it is missing. depends_on: ids of the earlier gaps whose
    faces it picks or repeats. written_before: ids of the steps of its walk's list written before it. before, after:
    `{ box, volume }` of the walk's body around the step, in the capture's coordinates, or None when not measured.
    """

    def __init__(self, gap_id, item, reason, depends_on, written_before, before=None, after=None):
        self.id = gap_id
        self.item = item
        self.reason = clip(reason, wording.MAX_NOTE) or "This step cannot be copied."
        self.depends_on = list(dict.fromkeys(depends_on))
        self.written_before = list(written_before)
        self.before, self.after = before, after
        self.place = None  # (after, before, list) once placed in the final recipe

    @property
    def index(self):
        return self.item.get("index")

    @property
    def name(self):
        return str(self.item.get("name") or "")[:MAX_NAME] or type_words(self.item.get("type") or "") or "A step"


def gap_id(ctx, item):
    """`gap_<timeline index>`, after the walk's id prefix, as step ids are made."""
    found = "%sgap_%s" % (ctx.id_prefix, item.get("index"))
    return found[-MAX_ID:]


def _root(ctx):
    while ctx.outer is not None:
        ctx = ctx.outer
    return ctx


def _measure(box, volume):
    if not _is_box(box) or not _finite(volume):
        return None
    return {"box": {"min": list(box["min"]), "max": list(box["max"])}, "volume": float(volume)}


def _state(record):
    record = record if isinstance(record, dict) else {}
    return _measure(record.get("box"), record.get("volume_mm3"))


def measures(ctx, item):
    """`(before, after)` of the body this walk builds around `item`, each `{ box, volume }` or None. The exported body
    has the reader's measures on the item; a tool body has what was measured on the tool itself (`tool_walk`)."""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    if _root(ctx).is_target(ctx.target):
        before = _state(item.get("target_before")) or _measure(data.get("target_box_before"), data.get("volume_before"))
        return before, _state(item.get("target_after"))
    return _measure(data.get("target_box_before"), data.get("volume_before")), None


def stop_reason(ctx, reason):
    """The reason that stops the copy instead of a gap at the walk's current place, or None when a gap is kept.

    A gap needs a body to add to, so one before the walk's first step stops it with its own reason. So does a gap in a
    walk of another component's body, whose data is not in the part's coordinates. A part with too many gaps stops
    too."""
    if not ctx.steps or ctx.component is not None:
        return reason
    count, walk = 0, ctx
    while walk is not None:
        count += len(walk.gaps)
        walk = walk.outer
    if count >= MAX_GAPS:
        return wording.too_many_gaps_reason(MAX_GAPS)
    return None


def picked_gaps(ctx, item):
    """`(gaps, sure)`: the gaps of this walk whose faces `item` picks. With the capture's `reach` read, these are the
    gaps among the steps that made the faces it picks (`sure` True). Without it, every gap before the item counts, since
    any of them may have made those faces. Empty when the item picks nothing or no gap comes before it."""
    earlier = [gap for gap in ctx.gaps if gap.index is not None and gap.index < item.get("index", 0)]
    if not earlier or not pick_records(item):
        return [], False
    reach = ctx.capture.get("reach")
    makers = reach.get("makers") if isinstance(reach, dict) and reach.get("read") is True else None
    found = makers.get(str(item.get("index"))) if isinstance(makers, dict) else None
    if not isinstance(found, list):
        return earlier, False
    return [gap for gap in earlier if gap.index in found], True


def _tree(features):
    """Step id to `(list owner id or None, list of steps)` for every step of the recipe."""
    out = {}

    def walk(steps, owner):
        for step in steps:
            out[step.get("id")] = (owner, steps)
            if step.get("features"):
                walk(step["features"], step.get("id"))

    walk(features, None)
    return out


def place_all(gaps, features):
    """Set each gap's place in the final recipe: the last step written before it that is still there, the list that
    holds that step and the step after it. Returns a reason when a gap has no place, else None."""
    tree = _tree(features)
    for gap in gaps:
        after = next((step_id for step_id in reversed(gap.written_before) if step_id in tree), None)
        if after is None:
            return wording.no_gap_place_reason()
        owner, steps = tree[after]
        ids = [step.get("id") for step in steps]
        position = ids.index(after)
        gap.place = (after, ids[position + 1] if position + 1 < len(ids) else None, owner)
    return None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_box(box):
    return isinstance(box, dict) and all(
        isinstance(box.get(k), (list, tuple)) and len(box[k]) == 3 and all(_finite(v) for v in box[k])
        for k in ("min", "max"))


def to_recipe(move):
    """The 12 numbers of a `place.Move`: the 3 by 3 rows, then the offset."""
    return [float(c) for row in move.rows for c in row] + [float(v) for v in move.offset]


def _moved(measure, move):
    """A `{ box, volume }` in recipe coordinates: the box around the moved corners. None when out of bounds."""
    if measure is None:
        return None
    lo, hi = measure["box"]["min"], measure["box"]["max"]
    corners = [[(lo, hi)[(n >> axis) & 1][axis] for axis in range(3)] for n in range(8)]
    moved = [[sum(move.rows[i][k] * p[k] for k in range(3)) + move.offset[i] for i in range(3)] for p in corners]
    box = {"min": [min(p[i] for p in moved) + 0.0 for i in range(3)],
           "max": [max(p[i] for p in moved) + 0.0 for i in range(3)]}
    numbers = box["min"] + box["max"]
    if any(abs(v) > MAX_MEASURE for v in numbers) or not 0 <= measure["volume"] <= MAX_MEASURE ** 2:
        return None
    return {"box": box, "volume": measure["volume"]}


def _values(item, table):
    """`{ path, fusion, expr? }` per model parameter value of the item: the Fusion expression, and the recipe formula
    when the size table can write it."""
    params = (item.get("data") or {}).get("params")
    out = []
    for path, ref in (params.items() if isinstance(params, dict) else ()):
        expression = ref.get("expression") if isinstance(ref, dict) else None
        if not isinstance(expression, str) or not expression or len(expression) > MAX_EXPRESSION:
            continue
        entry = {"path": str(path)[:MAX_PATH], "fusion": expression}
        if table is not None:
            found = table.translate(expression)
            if found.ok and len(str(found.formula)) <= MAX_EXPRESSION:
                entry["expr"] = str(found.formula)
        out.append(entry)
        if len(out) == MAX_VALUES:
            break
    return out


def _size_of(data):
    return len(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _thin_samples(node):
    """Free curve samples cut to MAX_SAMPLES points each, keeping both ends. True when one was cut."""
    cut = False
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "samples" and isinstance(value, list) and len(value) > MAX_SAMPLES:
                step = (len(value) - 1) / (MAX_SAMPLES - 1)
                node[key] = [value[round(n * step)] for n in range(MAX_SAMPLES)]
                cut = True
            else:
                cut = _thin_samples(value) or cut
    elif isinstance(node, list):
        for value in node:
            cut = _thin_samples(value) or cut
    return cut


def _drop_loops(node):
    """Loops past the first MAX_LOOPS of every outline dropped. True when one was dropped."""
    cut = False
    if isinstance(node, dict):
        loops = node.get("loops")
        if isinstance(loops, list) and len(loops) > MAX_LOOPS:
            node["loops"] = loops[:MAX_LOOPS]
            cut = True
        for value in node.values():
            cut = _drop_loops(value) or cut
    elif isinstance(node, list):
        for value in node:
            cut = _drop_loops(value) or cut
    return cut


def trimmed_data(data):
    """`(data, trimmed)`: the item's data cut until it fits MAX_DATA_BYTES as UTF-8 JSON. First free curve samples are
    thinned, then outlines lose their loops past the first few, then the outlines go; data that still does not fit is
    left out whole."""
    out = copy.deepcopy(data) if isinstance(data, dict) else {}
    if _size_of(out) <= MAX_DATA_BYTES:
        return out, False
    for cut in (_thin_samples, _drop_loops, lambda node: node.pop("profiles", None) is not None):
        cut(out)
        if _size_of(out) <= MAX_DATA_BYTES:
            return out, True
    return {}, True


def record(gap, table, move):
    """The gap as written for the package. `sizes` and `looseSizes` start empty; the driver fills them once it knows
    the sizes of the recipe."""
    after, before, owner = gap.place
    data, trimmed = trimmed_data(gap.item.get("data"))
    out = {
        "id": gap.id,
        "name": gap.name,
        "type": str(gap.item.get("type") or "")[:MAX_WORDS],
        "words": type_words(gap.item.get("type") or "")[:MAX_WORDS],
        "reason": gap.reason,
        "after": after,
        "before": before,
        "list": owner,
        "dependsOn": list(gap.depends_on),
        "sizes": [],
        "looseSizes": [],
        "values": _values(gap.item, table),
    }
    for key, measure in (("bodyBefore", gap.before), ("bodyAfter", gap.after)):
        moved = _moved(measure, move)
        if moved is not None:
            out[key] = moved
    out["data"] = data
    out["trimmed"] = trimmed
    return out
