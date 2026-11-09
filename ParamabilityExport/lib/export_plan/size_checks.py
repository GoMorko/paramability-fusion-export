"""Plan the size checks of a recipe export and read what they showed. Pure: no Fusion imports.

A check is one STEP file of the part with exactly one size changed. Paramability builds the recipe at that value
and compares it with the STEP, so a size that disagrees with Fusion is found and fixed there.

A size is a dict: param (Fusion name), size (name in the recipe), unit (Fusion unit), value, min, max (manifest
numbers: mm, deg or plain), favorite (bool).
"""
from ..package.manifest import MAX_NAME_CHARS
from ..package.units import display_from_manifest
from ..fusion_reader.sketches import moved_sketches

MAX_CHECKS = 16
_SAME = 1e-9


def check_value(size):
    """The value one check uses: the top of the range, or the bottom when the top is the current value. None when
    the range holds no other value."""
    top, bottom, now = size["max"], size["min"], size["value"]
    if abs(top - now) > _SAME:
        return top
    if abs(bottom - now) > _SAME:
        return bottom
    return None


def plan_checks(sizes, limit=MAX_CHECKS):
    """Return (checks, unchecked).

    checks: [{'param', 'size', 'value', 'row'}] in check order, favourites first, at most `limit`.
    row: {'name', 'values'} for RowExport. It lists every size at its current value except the checked one, so a
    check never starts from the state the one before it left.
    unchecked: the sizes that get no check, because of the limit or because their range holds one value only.
    """
    ordered = sorted(sizes, key=lambda s: 0 if s.get("favorite") else 1)
    checks = []
    unchecked = []
    for size in ordered:
        value = check_value(size)
        if value is None or len(checks) >= limit:
            unchecked.append(size)
            continue
        values = {s["param"]: display_from_manifest(s["value"], s["unit"]) for s in sizes}
        values[size["param"]] = display_from_manifest(value, size["unit"])
        checks.append({
            "param": size["param"], "size": size["size"], "value": value,
            "row": {"name": size["size"][:MAX_NAME_CHARS], "values": values},
        })
    return checks, unchecked


def fixed_entry(name, reason):
    """`name` is the Fusion parameter name; the package entry is made from it later, with the recipe size name."""
    return {"name": name, "reason": " ".join(reason.split())[:200]}


def moved_reason(label, sketch_names):
    shown = ", ".join(sketch_names[:2]) + (" and more" if len(sketch_names) > 2 else "")
    return f"{label} stays fixed for now: it changes {shown}. Sketches that follow sizes come in a later version."


def build_failure_reason(label, value):
    return f"{label} stays fixed: Fusion cannot build the part when it is {value:g}."


def read_checks(checks, results, baseline_sketches, sketch_by_check, labels):
    """Sort the checks by what they showed.

    results: RowExport results in check order; an entry with 'error' is a row Fusion could not build.
    sketch_by_check: {row name: sketch numbers read at that check} from the same run.
    labels: {size name: text for the person}.
    Returns (kept, fixed): kept lists the checks with a STEP file, in order, each with 'step_file'; fixed lists
    {'name' (Fusion name), 'reason', 'param', 'size'} for sizes that must stay fixed numbers.
    """
    kept, fixed = [], []
    for check, result in zip(checks, results):
        label = labels.get(check["size"], check["size"])
        if result.get("error"):
            fixed.append({**fixed_entry(check["param"], build_failure_reason(label, check["value"])),
                          "param": check["param"], "size": check["size"]})
            continue
        moved = moved_sketches(baseline_sketches, sketch_by_check.get(check["row"]["name"], {}))
        if moved:
            fixed.append({**fixed_entry(check["param"], moved_reason(label, moved)),
                          "param": check["param"], "size": check["size"]})
            continue
        kept.append({**check, "step_file": result["step_file"]})
    return kept, fixed
