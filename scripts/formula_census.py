"""Count how the formulas of exported packages translate. Prints counts only, never a value or a name.

Run from the add-in root: python3 scripts/formula_census.py <folder with .paramability or .zip exports>

For each distinct set of user parameters the script builds the size table the way the manifest list does (every
offered parameter ticked) and counts the formula parameters that become derived sizes or constants and those that
stay numbers, with the reasons masked (names and numbers replaced). It also counts the feature values that read a
size and whether they translate, and the forms the formulas use (operators, functions, unit words, fractions).
"""
import glob
import hashlib
import json
import os
import re
import sys
import zipfile
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ParamabilityExport"))

from lib.params import defaults, size_table  # noqa: E402
from lib.params.expressions.errors import ExpressionError  # noqa: E402
from lib.params.expressions.reading import parse  # noqa: E402
from lib.params.expressions.text import is_plain_number  # noqa: E402

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_QUOTED = re.compile(r"\"[^\"]*\"")


def _mask(reason, names):
    """The reason with every parameter name, quoted text and number replaced."""
    for name in sorted(names, key=len, reverse=True):
        if name:
            reason = reason.replace(name, "<name>")
    reason = _QUOTED.sub("\"<name>\"", reason)
    return _NUMBER.sub("N", reason)


def _walk(node):
    yield node
    for part in node[1:]:
        if isinstance(part, tuple):
            yield from _walk(part)
        elif isinstance(part, list):
            for item in part:
                yield from _walk(item)


def _is_number(node):
    return node[0] == "num" or (node[0] == "neg" and node[1][0] == "num")


def forms(expression):
    """The kinds of form one expression uses, as a set of short words."""
    try:
        tree = parse(expression)
    except ExpressionError:
        return {"unreadable"}
    found = set()
    names = 0
    for node in _walk(tree):
        kind = node[0]
        if kind == "bin":
            found.add({"+": "+ -", "-": "+ -", "*": "*", "/": "/", "%": "%", "^": "^"}[node[1]])
            if node[1] == "/" and _is_number(node[2]):
                right = node[3]
                if _is_number(right) or (right[0] == "unit" and _is_number(right[1])):
                    found.add("fraction of numbers")
        elif kind == "unit":
            found.add("unit word")
            inner = node[1]
            if inner[0] == "bin" and inner[1] == "/" and _is_number(inner[2]) and _is_number(inner[3]):
                found.add("unit after a fraction")
        elif kind == "call":
            found.add("call " + node[1])
        elif kind == "cmp":
            found.add("comparison")
        elif kind == "logic" or kind == "not":
            found.add("logic")
        elif kind == "name":
            names += 1
    if names == 0 and found:
        found.add("names no parameter")
    return found


def _reports(folder):
    paths = sorted(glob.glob(os.path.join(folder, "*.paramability")) + glob.glob(os.path.join(folder, "*.zip")))
    for path in paths:
        try:
            with zipfile.ZipFile(path) as package:
                yield json.loads(package.read("report.json"))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            continue


def _capture_of(report):
    capture = report.get("capture") if isinstance(report, dict) else None
    params = capture.get("parameters") if isinstance(capture, dict) else None
    if not isinstance(params, dict) or not isinstance(params.get("user"), list):
        return None
    return capture


def _digest(user):
    text = json.dumps([[p.get("name"), p.get("expression")] for p in user], sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _table(user, model, design_unit):
    offered = [p["name"] for p in user if defaults.is_offered(p)]
    return size_table.build(user, offered, model, design_unit, max_sizes=max(len(user), 1))


def main(folder):
    seen_sets, seen_model = set(), set()
    exports = 0
    parameters, translated, kept = Counter(), Counter(), Counter()
    reasons, kinds = Counter(), Counter()
    values, value_ok, value_reasons, value_kinds = Counter(), Counter(), Counter(), Counter()
    for report in _reports(folder):
        capture = _capture_of(report)
        if capture is None:
            continue
        exports += 1
        user = [p for p in capture["parameters"]["user"] if isinstance(p, dict) and defaults.is_numeric(p)]
        model = capture["parameters"].get("model") or []
        unit = capture.get("design_units", "mm")
        model_key = hashlib.sha1(json.dumps([[m.get("name"), m.get("expression")] for m in model],
                                            sort_keys=True).encode("utf-8")).hexdigest()
        seen_model.add(model_key)
        key = _digest(user) + unit
        new_set = key not in seen_sets
        seen_sets.add(key)
        try:
            table = _table(user, model, unit)
        except Exception:
            parameters["table failed"] += 1
            continue
        names = [p["name"] for p in user] + [m.get("name", "") for m in model]
        if new_set:
            for p in user:
                if is_plain_number(p.get("expression")):
                    continue
                parameters["formula parameters"] += 1
                entry = table.entry(p["name"])
                for form in forms(p.get("expression", "")):
                    kinds[form] += 1
                if entry is not None and entry.state in (size_table.DERIVED, size_table.CONSTANT) and entry.formula:
                    translated["translated"] += 1
                else:
                    kept["kept as a number"] += 1
                    reasons[_mask((entry.reason if entry else "no entry") or "no reason", names)] += 1
        for item in capture.get("items") or []:
            params = ((item or {}).get("data") or {}).get("params") or {}
            for ref in params.values():
                if not isinstance(ref, dict) or not ref.get("expression"):
                    continue
                tr = table.translate(ref["expression"], expected=ref.get("value"))
                if not tr.reads:
                    continue
                values["values that read a size"] += 1
                for form in forms(ref["expression"]):
                    value_kinds[form] += 1
                if tr.ok:
                    value_ok["translate"] += 1
                else:
                    value_reasons[_mask(tr.reason or "no reason", names)] += 1
    print("exports with a capture:", exports)
    print("distinct user parameter sets:", len(seen_sets), " distinct model parameter sets:", len(seen_model))
    for title, counter in (("user parameters", parameters), ("translated", translated), ("kept as a number", kept)):
        for label, count in sorted(counter.items()):
            print("%s: %s = %d" % (title, label, count))
    for label, count in reasons.most_common():
        print("  reason x%d: %s" % (count, label))
    print("forms of user parameter formulas:")
    for label, count in sorted(kinds.items()):
        print("  %s: %d" % (label, count))
    print("feature values:")
    for counter in (values, value_ok):
        for label, count in sorted(counter.items()):
            print("  %s: %d" % (label, count))
    for label, count in value_reasons.most_common():
        print("  reason x%d: %s" % (count, label))
    print("forms of feature value formulas:")
    for label, count in sorted(value_kinds.items()):
        print("  %s: %d" % (label, count))


if __name__ == "__main__":
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        sys.exit("usage: python3 scripts/formula_census.py <folder with exported packages>")
    main(sys.argv[1])
