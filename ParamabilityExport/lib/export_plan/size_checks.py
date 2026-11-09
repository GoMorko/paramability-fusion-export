"""Plan the size checks of a recipe export and read what they showed. Pure: no Fusion imports.

A check is one STEP file of the part with exactly one size changed. Paramability builds the recipe at that value
and compares it with the STEP, so a size that disagrees with Fusion is found and fixed there.

A size is a dict: param (Fusion name), size (name in the recipe), unit (Fusion unit), value, min, max (manifest
numbers: mm, deg or plain), favorite (bool).
"""
from ..package.manifest import MAX_CHECKS, MAX_FIXED_REASON, MAX_NAME_CHARS
from ..package.text import clip
from ..package.units import display_from_manifest
from ..fusion_reader.sketches import moved_sketches
from ..translator.notes import fixed_reason, loose_reason

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
        checks.append(check_at(size, value, sizes))
    return checks, unchecked


def check_at(size, value, sizes):
    """One check of `size` at `value`: every other size stays at its current value. The row also holds the manifest
    value it sets (`state`, `varied`), as the probe's rows do."""
    values = {s["param"]: display_from_manifest(s["value"], s["unit"]) for s in sizes}
    values[size["param"]] = display_from_manifest(value, size["unit"])
    return {
        "param": size["param"], "size": size["size"], "value": value,
        "row": {"name": size["size"][:MAX_NAME_CHARS], "values": values, "key": row_key(size["param"], value),
                "state": {size["param"]: value}, "varied": [size["param"]]},
    }


def row_key(param, value):
    """The key of a row that sets one size: unique per size and value, unlike the row name, which is cut."""
    return "%s=%r" % (param, float(value))


def into_range(checks, recipe_sizes):
    """[(check, value)] for the checks whose value lies outside the range the recipe gives their size (a minimum the
    translator raised, a range it shortened): the value is the end of that range on the same side, or None when that
    end is the current value. `recipe_sizes` is the recipe's `sizes` (recipe name to size dict)."""
    out = []
    for check in checks:
        size = recipe_sizes.get(check["size"]) or {}
        if "min" not in size or size["min"] - _SAME <= check["value"] <= size["max"] + _SAME:
            continue
        end = size["max"] if check["value"] > size["max"] else size["min"]
        out.append((check, None if abs(end - size["value"]) <= _SAME else end))
    return out


def fixed_entry(name, reason):
    """`name` is the Fusion parameter name; the package entry is made from it later, with the recipe size name."""
    return {"name": name, "reason": clip(reason, MAX_FIXED_REASON)}


def size_entry(param, size, label, why, loose=False):
    """The entry of a size that cannot follow: fixed, or kept free with a warning when `loose`."""
    reason = loose_reason(label, why) if loose else fixed_reason(label, why)
    return {**fixed_entry(param, reason), "param": param, "size": size}


def moved_why(sketch_names, scope=""):
    """`scope` is the component name put before each sketch name, for a body inside a component ("Tray / Sketch1")."""
    names = ["%s / %s" % (scope, n) if scope else n for n in sketch_names]
    shown = ", ".join(names[:2]) + (" and more" if len(names) > 2 else "")
    return "it changes %s, and a sketch like this cannot follow sizes yet" % shown


def build_failure_reason(label, value, items=()):
    """`value` is the number Fusion could not build, or a list of them (one per end of the range); `items` are the
    timeline items that went into error, the first one is named."""
    values = value if isinstance(value, (list, tuple)) else [value]
    why = f": {items[0]} fails" if items else ""
    shown = " or ".join("%g" % v for v in values)
    closer = ", or any value closer to the current one" if len(values) > 1 else ""
    return f"{label} stays fixed: Fusion cannot build the part when it is {shown}{closer}{why}."


def build_failures(checks, results, tries=None):
    """[{'size', 'value', 'error', 'detail'}] for the checks Fusion could not build, for `report.json`. `tries` is
    {size: [{'value', 'built'}]}: the smaller steps tried after the failure (`size_narrowing.narrow_failed`)."""
    out = []
    for c, r in zip(checks, results):
        if r.get("error"):
            out.append({"size": c["size"], "value": c["value"], "error": r["error"], "detail": r.get("detail") or {}})
            if (tries or {}).get(c["size"]):
                out[-1]["tries"] = tries[c["size"]]
    return out


def frame_numbers(frame):
    """A placement frame {origin, x, y, z} as the flat list stored under PLACEMENT_KEY in a snapshot."""
    return [float(v) for key in ("origin", "x", "y", "z") for v in frame[key]]


def place_why(part):
    return f"it moves {part} in the assembly, and parts that move with sizes come in a later version"


def place_moved(before, after):
    """The part's place changed between two snapshots. A place that was not read in one of them is no move."""
    old, new = before.get(PLACEMENT_KEY), after.get(PLACEMENT_KEY)
    if old is None or new is None:
        return False
    return len(old) != len(new) or any(abs(a - b) > PLACE_TOLERANCE for a, b in zip(old, new))


def _sketches_only(snapshot):
    return {k: v for k, v in snapshot.items() if k != PLACEMENT_KEY}


def read_checks(checks, results, baseline_sketches, sketch_by_check, labels, part_name="the part", scope="",
                loose=False, failed_ends=None):
    """Sort the checks by what they showed.

    results: RowExport results in check order; an entry with 'error' is a row Fusion could not build.
    sketch_by_check: {row key: sketch numbers read at that check} from the same run. A snapshot may also hold the
    part's place under PLACEMENT_KEY (`frame_numbers`); a size that moves it cannot follow, since the recipe is written
    at the place of the export. So can a size that changes a sketch the probe does not follow.
    labels: {size name: text for the person}.
    part_name: the part as the person knows it (the component), for the reason of a move.
    scope: the component name shown before a sketch name in a reason; empty for a body of the root.
    loose: a size that cannot follow keeps its check and stays free with a warning, instead of being fixed.
    failed_ends: {Fusion name: [values]} the ends Fusion could not build, for the reason of a check that failed.
    Returns (kept, fixed, loose): kept lists the checks with a STEP file, in order, each with 'step_file'; fixed and
    loose list {'name' (Fusion name), 'reason', 'param', 'size'}. A check that did not build is always fixed.
    """
    kept, fixed, doubtful = [], [], []
    for check, result in zip(checks, results):
        label = labels.get(check["size"], check["size"])
        if result.get("error"):
            items = (result.get("detail") or {}).get("items") or ()
            value = (failed_ends or {}).get(check["param"]) or check["value"]
            fixed.append({**fixed_entry(check["param"], build_failure_reason(label, value, items)),
                          "param": check["param"], "size": check["size"]})
            continue
        row = check["row"]
        snapshot = sketch_by_check.get(row.get("key", row["name"]), {})
        why = None
        if place_moved(baseline_sketches, snapshot):
            why = place_why(part_name)
        else:
            moved = moved_sketches(_sketches_only(baseline_sketches), _sketches_only(snapshot))
            if moved:
                why = moved_why(moved, scope)
        if why is not None:
            (doubtful if loose else fixed).append(size_entry(check["param"], check["size"], label, why, loose))
            if not loose:
                continue
        kept.append({**check, "step_file": result["step_file"]})
    return kept, fixed, doubtful
