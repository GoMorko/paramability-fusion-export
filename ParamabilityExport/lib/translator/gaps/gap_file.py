"""A gap as written for the package: the record in the gaps file, with the data of the step kept within its caps.

The app refuses a whole gaps file that breaks one of the caps (`RECIPE_GAPS_CAPS` in the app's recipe package).
"""
import json
import math

from ...capture_model.gap_hints import hint as gap_hint
from .finishing import is_finishing
from .gap_measures import moved_measure
from ..words import type_words

MAX_WORDS = 64
MAX_SIZES = 64
MAX_VALUES = 64
MAX_EXPRESSION = 300
MAX_PATH = 200
MAX_DATA_BYTES = 48 * 1024
MAX_DATA_DEPTH = 32  # the data object itself is level 1
MAX_SAMPLES = 200
MAX_LOOPS = 8


def _values(item, table):
    """`{ path, fusion, expr? }` per model parameter value of the item: the Fusion expression, and the recipe formula
    when the size table can write it."""
    params = (item.get("data") or {}).get("params")
    out = []
    for path, ref in (params.items() if isinstance(params, dict) else ()):
        expression = ref.get("expression") if isinstance(ref, dict) else None
        if (not isinstance(expression, str) or not expression or len(expression) > MAX_EXPRESSION
                or not str(path).strip()):
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


def _plain_json(node, depth):
    """`(node, cut)`: `node` as JSON the app reads. A number that is not finite becomes null, and an object or list
    that would hold values past MAX_DATA_DEPTH levels becomes null; `cut` says one was changed."""
    if node is None or isinstance(node, (bool, str)):
        return node, False
    if isinstance(node, (int, float)):
        return (node, False) if math.isfinite(node) else (None, True)
    if isinstance(node, (dict, list, tuple)):
        if depth >= MAX_DATA_DEPTH and node:
            return None, True
        pairs = node.items() if isinstance(node, dict) else enumerate(node)
        found, cut = {}, False
        for key, value in pairs:
            found[key], changed = _plain_json(value, depth + 1)
            cut = cut or changed
        return (found if isinstance(node, dict) else list(found.values())), cut
    return None, True


def trimmed_data(data):
    """`(data, trimmed)`: the item's data as plain JSON (`_plain_json`), cut until it fits MAX_DATA_BYTES as UTF-8
    JSON. First free curve samples are thinned, then outlines lose their loops past the first few, then the outlines
    go; data that still does not fit is left out whole."""
    out, trimmed = _plain_json(data, 1) if isinstance(data, dict) else ({}, False)
    if _size_of(out) <= MAX_DATA_BYTES:
        return out, trimmed
    for cut in (_thin_samples, _drop_loops, lambda node: node.pop("profiles", None) is not None):
        cut(out)
        if _size_of(out) <= MAX_DATA_BYTES:
            return out, True
    return {}, True


def record(gap, table, move):
    """The gap as written for the package. `sizes` and `looseSizes` start empty; the driver fills them once it knows
    the sizes of the recipe. `hint`, what to change in Fusion so the step copies, is there only when its cause has
    one (`gap_hints`). `finishing` says the step only finishes surfaces (`finishing.is_finishing`)."""
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
    found = gap_hint(gap.cause)
    if found:
        out["hint"] = found
    for key, measure in (("bodyBefore", gap.before), ("bodyAfter", gap.after)):
        moved = moved_measure(measure, move)
        if moved is not None:
            out[key] = moved
    out["data"] = data
    out["trimmed"] = trimmed
    out["finishing"] = is_finishing(gap.item.get("type"), gap.item.get("data"))
    return out
