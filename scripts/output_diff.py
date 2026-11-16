"""The difference between two output snapshots (`scripts/output_snapshot.py`), one line per change.

    python3 scripts/output_diff.py before.json after.json [--all]

A line reads `capture | mode | translator | what changed`. Translators are "paramability" and "orca". A changed
recipe is listed by JSON path. A changed formula is worked out for both versions at the current values and with each
size 25% lower and higher, and a line says "same values" when they agree. At most 12 path lines are shown per
capture unless `--all` is given. The exit status is 1 when anything differs, else 0.
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ParamabilityExport"))
sys.path.insert(0, ROOT)

from lib.orca_translate.formulas import orca_value, variable_values  # noqa: E402
from lib.params.expressions.errors import ExpressionError  # noqa: E402
from lib.params.expressions.evaluation import evaluate  # noqa: E402

SIDES = {"p": "paramability", "o": "orca"}
SHOWN = 12
LENGTH = "#length"  # the last part of a path that reports a list length
FACTORS = (0.75, 1.25)
# Keys that are compared as a whole, as lists of entries, in the summary of each translator.
LIST_KEYS = {"p": ("verdicts", "gaps", "fixed", "loose", "cuts", "dropped"), "o": ("verdicts", "left_out", "parameters")}
SCALAR_KEYS = {"p": ("skipped", "refusal"), "o": ("bound",)}


def walk(old, new, path=()):
    """`[(path, old, new)]` for every leaf that differs. A path is a tuple of keys and list positions; a value that is
    missing on one side is `MISSING`. A list that changes length reports `(path + (LENGTH,), a, b)` for the length and
    still compares the positions both lists have."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in sorted(set(old) | set(new)):
            if key not in new:
                out.append((path + (key,), old[key], MISSING))
            elif key not in old:
                out.append((path + (key,), MISSING, new[key]))
            else:
                out += walk(old[key], new[key], path + (key,))
        return out
    if isinstance(old, list) and isinstance(new, list):
        out = [(path + (LENGTH,), len(old), len(new))] if len(old) != len(new) else []
        for i in range(min(len(old), len(new))):
            out += walk(old[i], new[i], path + (i,))
        return out
    return [] if old == new else [(path, old, new)]


class _Missing:
    def __repr__(self):
        return "missing"


MISSING = _Missing()


def format_path(path):
    out = ""
    for part in path:
        out += "[%d]" % part if isinstance(part, int) else ("." if out else "") + str(part)
    return out


def short(value, width=60):
    text = "missing" if value is MISSING else json.dumps(value, sort_keys=True, default=str)
    return text if len(text) <= width else text[:width - 3] + "..."


def is_formula_path(side, path):
    """True when the leaf at `path` is a formula text: an `expr` entry of the recipe of the app, or a variable or an
    `expr` field of a feature of the Orca recipe."""
    if side == "p":
        return len(path) >= 2 and path[-1] == "expr"
    return (len(path) == 2 and path[0] == "variables") or (len(path) == 4 and path[0] == "features" and path[2] == "expr")


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)


def scenarios(env):
    """`[(label, env)]`: the values as they are, then each size 25% lower and then higher."""
    out = [("current values", dict(env))]
    for name in sorted(env):
        for factor in FACTORS:
            out.append(("%s at %d%%" % (name, round(factor * 100)), dict(env, **{name: env[name] * factor})))
    return out


def compare_formulas(old_eval, new_eval, env):
    """`"same values"` when two evaluators agree in every scenario of `env`, else a sentence about the first that
    does not. An evaluator takes a scenario env and returns a number, or raises ExpressionError or KeyError."""
    def work(fn, scenario):
        try:
            return fn(scenario)
        except (ExpressionError, KeyError, ZeroDivisionError, ValueError, OverflowError):
            return "cannot be worked out"
    for label, scenario in scenarios(env):
        a, b = work(old_eval, scenario), work(new_eval, scenario)
        if isinstance(a, str) or isinstance(b, str):
            if a != b:
                return "values differ at %s: %s -> %s" % (label, a if isinstance(a, str) else "%.6g" % a,
                                                           b if isinstance(b, str) else "%.6g" % b)
        elif not close(a, b):
            return "values differ at %s: %.6g -> %.6g" % (label, a, b)
    return "same values"


def app_env(entry):
    """`{size name: value}` of the sizes with a number in an app recipe."""
    sizes = (entry.get("recipe") or {}).get("sizes") or {}
    return {n: s["value"] for n, s in sizes.items() if isinstance(s, dict) and isinstance(s.get("value"), (int, float))}


def orca_inputs(entry):
    """`{variable: number}` of the Orca variables that are plain numbers; the others follow from them."""
    out = {}
    for name, text in (entry.get("variables") or {}).items():
        try:
            out[name] = float(text)
        except (TypeError, ValueError):
            pass
    return out


def orca_evaluator(variables, expression):
    """A function of the plain variables' values that works out `expression` over `variables` as Orca does."""
    def evaluate_it(inputs):
        names = dict(variables)
        names.update({n: repr(v) for n, v in inputs.items() if n in variables})
        return orca_value(expression, variable_values(names))
    return evaluate_it


def formula_line(side, path, old, new, old_entry, new_entry):
    """The text for a changed formula at `path`."""
    if side == "p":
        env = dict(app_env(old_entry))
        env.update(app_env(new_entry))
        verdict = compare_formulas(lambda e: evaluate(old, e), lambda e: evaluate(new, e), env)
    else:
        env = orca_inputs(new_entry) or orca_inputs(old_entry)
        read = path[1] if path[0] == "variables" else None
        old_vars, new_vars = old_entry.get("variables") or {}, new_entry.get("variables") or {}
        if read is not None:
            verdict = compare_formulas(orca_evaluator(old_vars, read), orca_evaluator(new_vars, read), env)
        else:
            verdict = compare_formulas(orca_evaluator(old_vars, old), orca_evaluator(new_vars, new), env)
    return "%s: formula %s -> %s (%s)" % (format_path(path), short(old, 40), short(new, 40), verdict)


def entry_changes(side, old, new, show_all=False):
    """The lines about one translator's entry of one capture and mode."""
    if old is None or new is None:
        return ["output %s" % ("appeared" if old is None else "disappeared")]
    if "error" in old or "error" in new:
        if old.get("error") == new.get("error"):
            return []
        return ["error changed: %s -> %s" % (old.get("error", "none"), new.get("error", "none"))]
    lines = []
    for key in LIST_KEYS[side]:
        lines += list_lines(key, old.get(key) or [], new.get(key) or [])
    for key in SCALAR_KEYS[side]:
        if old.get(key) != new.get(key):
            lines.append("%s: %s -> %s" % (key, short(old.get(key)), short(new.get(key))))
    for key in sorted(set(old.get("texts") or {}) | set(new.get("texts") or {})):
        if (old.get("texts") or {}).get(key) != (new.get("texts") or {}).get(key):
            lines.append("user-facing text changed: %s" % key)
    roots = ("recipe",) if side == "p" else ("features", "variables")
    found = []
    for root in roots:
        found += walk(old.get(root), new.get(root), (root,))
    for path, a, b in found if show_all else found[:SHOWN]:
        if is_formula_path(side, path) and a is not MISSING and b is not MISSING:
            lines.append(formula_line(side, path, a, b, old, new))
        elif path[-1] == LENGTH:
            lines.append("%s: length %s -> %s" % (format_path(path[:-1]), a, b))
        else:
            lines.append("%s: %s -> %s" % (format_path(path), short(a), short(b)))
    if len(found) > SHOWN and not show_all:
        lines.append("... and %d more changes in the recipe" % (len(found) - SHOWN))
    if not found and old.get("recipe_sha") != new.get("recipe_sha"):
        lines.append("recipe bytes changed outside the fields listed in the snapshot")
    return lines


def list_lines(key, old, new):
    """One line for a list that changed: what left and what came."""
    if old == new:
        return []
    gone = [e for e in old if e not in new]
    came = [e for e in new if e not in old]
    parts = []
    if gone:
        parts.append("removed %s" % short(gone[:4], 120) + (" and %d more" % (len(gone) - 4) if len(gone) > 4 else ""))
    if came:
        parts.append("added %s" % short(came[:4], 120) + (" and %d more" % (len(came) - 4) if len(came) > 4 else ""))
    return ["%s: %s" % (key, ", ".join(parts) or "order changed")]


def diff(before, after, show_all=False):
    """`[(capture, mode, translator, text)]` for two snapshots."""
    out = []
    for capture in sorted(set(before) | set(after)):
        if capture not in after or capture not in before:
            out.append((capture, "-", "-", "capture %s" % ("appeared" if capture not in before else "disappeared")))
            continue
        old_modes, new_modes = before[capture], after[capture]
        for mode in sorted(set(old_modes) | set(new_modes)):
            if mode not in old_modes or mode not in new_modes:
                out.append((capture, mode, "-", "mode %s" % ("appeared" if mode not in old_modes else "disappeared")))
                continue
            for side in sorted(set(old_modes[mode]) | set(new_modes[mode])):
                old, new = old_modes[mode].get(side), new_modes[mode].get(side)
                if old is None and new is None:
                    continue
                for text in entry_changes(side, old, new, show_all):
                    out.append((capture, mode, SIDES[side], text))
    return out


def main(argv):
    show_all = "--all" in argv
    names = [a for a in argv if a != "--all"]
    if len(names) != 2:
        sys.exit(__doc__)
    snaps = []
    for name in names:
        with open(name, encoding="utf-8") as f:
            snaps.append(json.load(f))
    lines = diff(snaps[0], snaps[1], show_all)
    for line in lines:
        print(" | ".join(line))
    changed = {(c, m, t) for c, m, t, _ in lines}
    print("%d lines, %d outputs changed" % (len(lines), len(changed)))
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
