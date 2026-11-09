"""Shorten the range of a size that Fusion cannot build at its checked value. Pure: no Fusion imports.

A size check goes to the end of the range. When Fusion cannot build the part there, the check is tried again at
smaller steps toward the current value (half way, then a quarter, then an eighth of the way). The highest value that
builds becomes the new end of the range and the new check; only a size with no building value stays fixed.

`run_try(check, number, total, description)` runs one check row (`size_checks.check_at`) and returns its RowExport
result; it raises to stop the export.
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
    """What `narrow_failed` found: the checks and results with the narrowed ones replaced, `narrowed` (one dict per
    size whose range was shortened), `tries` ({size: [{'value', 'built'}]} for every size tried again) and `sizes`
    (the size dicts with the new range ends)."""

    def __init__(self, checks, results, sizes):
        self.checks, self.results, self.sizes = list(checks), list(results), list(sizes)
        self.narrowed, self.tries = [], {}

    def ranges(self):
        """{Fusion name: (min, max)} of the shortened sizes, for `SizeTable.with_narrowed`."""
        return {n["param"]: (n["min"], n["max"]) for n in self.narrowed}


def narrow_failed(checks, results, sizes, run_try, labels):
    """Try the checks that did not build at smaller steps. Returns a `Narrowing`.

    sizes: the size dicts the checks came from (`size_offers.sizes_for_checks`, with `kind`, `typed_min` and
    `typed_max`). labels: {size name: text for the person}.
    """
    by_param = {s["param"]: s for s in sizes}
    plan = {i: retry_values(by_param[c["param"]], c["value"])
            for i, (c, r) in enumerate(zip(checks, results)) if retryable(r) and c["param"] in by_param}
    out = Narrowing(checks, results, sizes)
    total, number = sum(len(v) for v in plan.values()), 0
    for index, values in plan.items():
        check, failure = checks[index], results[index]
        size = by_param[check["param"]]
        label = labels.get(size["size"], size["size"])
        tried = out.tries.setdefault(size["size"], [])
        for value in values:
            number += 1
            retry = check_at(size, value, sizes)
            result = run_try(retry, number, total, "%s at %s" % (label, _amount(value, size)))
            tried.append({"value": value, "built": not result.get("error")})
            if not result.get("error"):
                out.checks[index], out.results[index] = retry, result
                _record(out, size, check["value"], value, label, failure)
                number += len(values) - len(tried)
                break
    return out


def _record(out, size, failed, value, label, failure):
    side = "max" if failed > size["value"] else "min"
    lo, hi = (size["min"], value) if side == "max" else (value, size["max"])
    items = (failure.get("detail") or {}).get("items") or ()
    sentence = narrowed_sentence(label, side, _amount(value, size), _amount(failed, size),
                                 typed=bool(size.get("typed_" + ("max" if side == "max" else "min"))),
                                 item=items[0] if items else "")
    out.narrowed.append({"param": size["param"], "size": size["size"], "side": side, "from": failed, "to": value,
                         "min": lo, "max": hi, "items": list(items), "note": sentence})
    out.sizes = [dict(s, min=lo, max=hi) if s["param"] == size["param"] else s for s in out.sizes]
