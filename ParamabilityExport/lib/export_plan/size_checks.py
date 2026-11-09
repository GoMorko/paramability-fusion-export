"""Plan the size checks of a recipe export and read what they showed. Pure: no Fusion imports.

A check is one STEP file of the part with exactly one size changed. Paramability builds the recipe at that value
and compares it with the STEP, so a size that disagrees with Fusion is found and fixed there.

A size is a dict: param (Fusion name), size (name in the recipe), unit (Fusion unit), value, min, max (manifest
numbers: mm, deg or plain), favorite (bool).
"""
from ..package.manifest import MAX_CHECKS, MAX_NAME_CHARS
from ..package.units import display_from_manifest
from ..fusion_reader.sketches import moved_sketches

_SAME = 1e-9

# Key of the part's place in a sketch snapshot. It is not a string, so no sketch name can take it.
PLACEMENT_KEY = ("placement",)
# 1e-4 mm: the recompute noise Fusion leaves on an unchanged place (the numbers are mm and unit axes).
PLACE_TOLERANCE = 1e-4


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


def moved_reason(label, sketch_names, scope=""):
    """`scope` is the component name put before each sketch name, for a body inside a component ("Tray / Sketch1")."""
    names = ["%s / %s" % (scope, n) if scope else n for n in sketch_names]
    shown = ", ".join(names[:2]) + (" and more" if len(names) > 2 else "")
    return f"{label} stays fixed for now: it changes {shown}. A sketch like this cannot follow sizes yet."


def build_failure_reason(label, value, items=()):
    """`items` are the timeline items that went into error; the first one is named."""
    why = f": {items[0]} fails" if items else ""
    return f"{label} stays fixed: Fusion cannot build the part when it is {value:g}{why}."


def build_failures(checks, results):
    """[{'size', 'value', 'error', 'detail'}] for the checks Fusion could not build, for `report.json`."""
    return [{"size": c["size"], "value": c["value"], "error": r["error"], "detail": r.get("detail") or {}}
            for c, r in zip(checks, results) if r.get("error")]


def frame_numbers(frame):
    """A placement frame {origin, x, y, z} as the flat list stored under PLACEMENT_KEY in a snapshot."""
    return [float(v) for key in ("origin", "x", "y", "z") for v in frame[key]]


def place_reason(label, part):
    return (f"{label} stays fixed: it moves {part} in the assembly. "
            "Parts that move with sizes come in a later version.")


def place_moved(before, after):
    """The part's place changed between two snapshots. A place that was not read in one of them is no move."""
    old, new = before.get(PLACEMENT_KEY), after.get(PLACEMENT_KEY)
    if old is None or new is None:
        return False
    return len(old) != len(new) or any(abs(a - b) > PLACE_TOLERANCE for a, b in zip(old, new))


def _sketches_only(snapshot):
    return {k: v for k, v in snapshot.items() if k != PLACEMENT_KEY}


def read_checks(checks, results, baseline_sketches, sketch_by_check, labels, part_name="the part", scope=""):
    """Sort the checks by what they showed.

    results: RowExport results in check order; an entry with 'error' is a row Fusion could not build.
    sketch_by_check: {row name: sketch numbers read at that check} from the same run. A snapshot may also hold the
    part's place under PLACEMENT_KEY (`frame_numbers`); a size that moves it is fixed, since the recipe is written at
    the place of the export.
    labels: {size name: text for the person}.
    part_name: the part as the person knows it (the component), for the reason of a move.
    scope: the component name shown before a sketch name in a reason; empty for a body of the root.
    Returns (kept, fixed): kept lists the checks with a STEP file, in order, each with 'step_file'; fixed lists
    {'name' (Fusion name), 'reason', 'param', 'size'} for sizes that must stay fixed numbers.
    """
    kept, fixed = [], []
    for check, result in zip(checks, results):
        label = labels.get(check["size"], check["size"])
        if result.get("error"):
            items = (result.get("detail") or {}).get("items") or ()
            fixed.append({**fixed_entry(check["param"], build_failure_reason(label, check["value"], items)),
                          "param": check["param"], "size": check["size"]})
            continue
        snapshot = sketch_by_check.get(check["row"]["name"], {})
        if place_moved(baseline_sketches, snapshot):
            fixed.append({**fixed_entry(check["param"], place_reason(label, part_name)),
                          "param": check["param"], "size": check["size"]})
            continue
        moved = moved_sketches(_sketches_only(baseline_sketches), _sketches_only(snapshot))
        if moved:
            fixed.append({**fixed_entry(check["param"], moved_reason(label, moved, scope)),
                          "param": check["param"], "size": check["size"]})
            continue
        kept.append({**check, "step_file": result["step_file"]})
    return kept, fixed
