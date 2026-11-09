"""Find how far each size can move each way in Fusion. Pure: no Fusion imports.

A size check goes to one end of the range (the top, or the bottom when the top is the current value). When Fusion
cannot build the part there, the check is tried again at smaller steps toward the current value (half way, then a
quarter, then an eighth of the way); the first value that builds becomes that end of the range and the new check.
When none builds, the current value becomes that end. The other end is then tried the same way: with a STEP when the
check had to move there, else as a rebuild only. A size that builds at no other value either way stays fixed.

`run(size, values, step, description)` sets `size` to each value in turn (rows of `size_checks.check_at`, with a
STEP when `step`), stops after the first that builds and returns the RowExport results of the rows it ran; it raises
to stop the export.
"""
import math

from ..package.units import display_from_manifest, unit_kind
from ..params.expressions import format_number
from .messages import narrowed_sentence
from .size_checks import check_at

RETRY_FRACTIONS = (0.5, 0.25, 0.125)
_SAME = 1e-9
# Build errors that a smaller value can cure. A refused expression is no range problem.
_RETRY_REASONS = ("new_errors", "recompute_failed", "recompute_raised")


def retryable(result):
    return bool(result.get("error")) and (result.get("detail") or {}).get("reason") in _RETRY_REASONS


def _toward(value, now):
    """`value` cut to a short number, on the side of `now` so that it still builds no worse than the exact one."""
    step = 10.0 ** (math.floor(math.log10(abs(value - now))) - 1)
    scaled = value / step
    cut = math.floor(scaled + 1e-9) if value > now else math.ceil(scaled - 1e-9)
    return round(cut * step, 9)


def retry_values(size, failed):
    """The values to try after `failed`, from the one nearest to it to the one nearest the current value."""
    now = size["value"]
    out = []
    for fraction in RETRY_FRACTIONS:
        value = now + (failed - now) * fraction
        value = float(math.floor(value + 1e-9) if failed > now else math.ceil(value - 1e-9)) \
            if size.get("kind") == "count" else _toward(value, now)
        if abs(value - now) > _SAME and abs(failed - value) > _SAME and value not in out:
            out.append(value)
    return out


def _amount(value, size):
    unit = size["unit"]
    text = format_number(round(display_from_manifest(value, unit), 6))
    return text + " " + unit if unit_kind(unit) in ("length", "angle") else text


class Narrowing:
    """What `narrow_failed` found: the checks and results with the moved ones replaced, `narrowed` (one dict per end
    of a range that was shortened), `tries` ({size: [{'value', 'built'}]} for every value tried after a failure or at
    the other end), `sizes` (the size dicts with the new range ends) and `failed_ends` ({Fusion name: [values]} of
    the sizes that build at no other value, for the reason they stay fixed)."""

    def __init__(self, checks, results, sizes):
        self.checks, self.results, self.sizes = list(checks), list(results), list(sizes)
        self.narrowed, self.tries, self.failed_ends = [], {}, {}

    def ranges(self):
        """{Fusion name: (min, max)} of the shortened sizes, as the checks saw them."""
        return {n["param"]: (n["min"], n["max"]) for n in self.narrowed}

    def moved_ends(self, table):
        """{Fusion name: (min, max)} for `SizeTable.with_narrowed`: only the ends found here move, the other end stays
        as `table` has it, so the translator still reports the limits it sets itself."""
        out = {}
        for n in self.narrowed:
            size = table.sizes.get(table.size_name(n["param"])) or {}
            lo, hi = out.get(n["param"], (size.get("min", n["min"]), size.get("max", n["max"])))
            out[n["param"]] = (n["to"], hi) if n["side"] == "min" else (lo, n["to"])
        return out


def _same(a, b):
    return abs(a - b) <= _SAME


def narrow_failed(checks, results, sizes, run, labels):
    """Try both ends of each checked size. Returns a `Narrowing`.

    sizes: the size dicts the checks came from (`size_offers.sizes_for_checks`, with `kind`, `typed_min` and
    `typed_max`). labels: {size name: text for the person}.
    """
    by_param = {s["param"]: s for s in sizes}
    out = Narrowing(checks, results, sizes)
    for index, check in enumerate(checks):
        size = by_param.get(check["param"])
        if size is None:
            continue
        label = labels.get(size["size"], size["size"])
        moves = _end(out, index, size, check["value"], results[index], run, label, step=True)
        other = size["max"] if check["value"] < size["value"] else size["min"]
        if not _same(other, size["value"]):
            moves = _end(out, index, size, other, None, run, label, step=not moves) or moves
        if not moves:
            ends = [check["value"]] + ([other] if not _same(other, size["value"]) else [])
            out.failed_ends[size["param"]] = ends
            out.narrowed = [n for n in out.narrowed if n["param"] != size["param"]]
    return out


def _end(out, index, size, end, result, run, label, step):
    """Settle one end of a size's range. `result` is the check already run at `end`, or None to try `end` first.
    Returns True when the part builds at `end` or at a value tried toward the current one, which then ends the range
    (and becomes the check with `step`); else the current value ends the range."""
    if result is not None and not result.get("error"):
        return True
    size = next(s for s in out.sizes if s["param"] == size["param"])
    values = [end] if result is None else []
    if result is None or retryable(result):
        values += retry_values(size, end)
    found = run(size, values, step, "%s at %s" % (label, _amount(values[0], size))) if values else []
    tries = out.tries.setdefault(size["size"], [])
    failure = result
    for value, got in zip(values, found):
        tries.append({"value": value, "built": not got.get("error")})
        if got.get("error"):
            failure = failure or got
            continue
        if step:
            out.checks[index], out.results[index] = check_at(size, value, out.sizes), got
        if not _same(value, end):
            _record(out, size, end, value, label, failure or {})
        return True
    _record(out, size, end, size["value"], label, failure or {})
    return False


def _record(out, size, failed, value, label, failure):
    side = "max" if failed > size["value"] else "min"
    lo, hi = (size["min"], value) if side == "max" else (value, size["max"])
    items = (failure.get("detail") or {}).get("items") or ()
    sentence = narrowed_sentence(label, side, _amount(value, size), _amount(failed, size),
                                 typed=bool(size.get("typed_" + side)), item=items[0] if items else "")
    out.narrowed.append({"param": size["param"], "size": size["size"], "side": side, "from": failed, "to": value,
                         "min": lo, "max": hi, "items": list(items), "note": sentence})
    out.sizes = [dict(s, min=lo, max=hi) if s["param"] == size["param"] else s for s in out.sizes]
