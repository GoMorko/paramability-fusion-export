"""Manifest builders and a local check of the package rules. The app stays the authority."""
import math
import re

SCHEMA = "paramability.recipePackage"
VERSION = 1
KINDS = ("valueRows", "recipe", "stepOnly")
UNITS = ("mm", "deg", "")

_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def build_value_rows_manifest(name, writer, parameters, rows, default_index=None, choice_name=None,
                              up_axis="z", notes=None):
    """rows: list of {'name', 'values'}. Step paths are assigned as rows/01.step and up."""
    out_rows = []
    for i, row in enumerate(rows, start=1):
        entry = {"name": row["name"], "values": dict(row["values"]), "step": row_step_path(i)}
        if default_index is not None and default_index == i - 1:
            entry["default"] = True
        out_rows.append(entry)
    manifest = {
        "schema": SCHEMA,
        "version": VERSION,
        "kind": "valueRows",
        "name": name,
        "upAxis": up_axis,
        "writer": writer,
        "notes": list(notes or []),
        "parameters": [dict(p) for p in parameters],
        "rows": out_rows,
    }
    if choice_name:
        manifest["choiceName"] = choice_name
    return manifest


def build_step_only_manifest(name, writer, up_axis="z", notes=None):
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "kind": "stepOnly",
        "name": name,
        "upAxis": up_axis,
        "writer": writer,
        "notes": list(notes or []),
        "part": "part.step",
    }


def row_step_path(number):
    return f"rows/{number:02d}.step"


def _clean_len(text):
    return len(_CONTROL.sub("", text).strip())


def _path_problem(path, label, suffixes):
    if not isinstance(path, str) or not path:
        return f"{label}: the path is missing."
    if len(path) > 128:
        return f"{label}: the path is longer than 128 characters."
    parts = path.split("/")
    for part in parts:
        if part in ("", "..", ".") or not _SEGMENT.match(part):
            return f"{label}: \"{path}\" is not a safe relative path."
    if not path.lower().endswith(suffixes):
        return f"{label}: \"{path}\" must end in {' or '.join(suffixes)}."
    return None


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_manifest(m):
    """Return a list of plain sentences, empty when the manifest follows the rules."""
    problems = []
    if not isinstance(m, dict):
        return ["The manifest is not an object."]
    if m.get("schema") != SCHEMA:
        problems.append(f"schema must be \"{SCHEMA}\".")
    if m.get("version") != VERSION:
        problems.append(f"version must be {VERSION}.")
    kind = m.get("kind")
    if kind not in KINDS:
        problems.append("kind must be valueRows, recipe or stepOnly.")
    name = m.get("name")
    if not isinstance(name, str) or not 1 <= _clean_len(name) <= 120:
        problems.append("name must be 1 to 120 characters.")
    if m.get("upAxis", "z") not in ("z", "y"):
        problems.append("upAxis must be z or y.")
    writer = m.get("writer")
    if writer is not None and (not isinstance(writer, str) or len(writer) > 200):
        problems.append("writer must be text of at most 200 characters.")
    notes = m.get("notes")
    if notes is not None:
        if not isinstance(notes, list) or len(notes) > 5:
            problems.append("notes must be a list of at most 5 sentences.")
        elif any(not isinstance(n, str) or len(n) > 200 for n in notes):
            problems.append("each note must be text of at most 200 characters.")

    paths = []

    def check_path(path, label, suffixes):
        problem = _path_problem(path, label, suffixes)
        if problem:
            problems.append(problem)
        elif path in paths:
            problems.append(f"{label}: \"{path}\" is used twice.")
        else:
            paths.append(path)

    step_suffixes = (".step", ".stp")
    if kind == "stepOnly":
        check_path(m.get("part"), "part", step_suffixes)
    elif kind == "recipe":
        check_path(m.get("part"), "part", step_suffixes)
        check_path(m.get("recipe"), "recipe", (".json",))
        checks = m.get("checks", [])
        if not isinstance(checks, list) or len(checks) > 16:
            problems.append("checks must be a list of at most 16.")
        else:
            for i, c in enumerate(checks, start=1):
                label = f"check {i}"
                vals = c.get("values") if isinstance(c, dict) else None
                if not isinstance(vals, dict) or not vals or not all(_finite(v) for v in vals.values()):
                    problems.append(f"{label}: values must be a non empty map of numbers.")
                check_path(c.get("step") if isinstance(c, dict) else None, label, step_suffixes)
    elif kind == "valueRows":
        _validate_value_rows(m, problems, check_path, step_suffixes)
    return problems


def _validate_value_rows(m, problems, check_path, step_suffixes):
    choice = m.get("choiceName")
    if choice is not None and (not isinstance(choice, str) or not 1 <= _clean_len(choice) <= 60):
        problems.append("choiceName must be 1 to 60 characters.")
    params = m.get("parameters", [])
    names = set()
    if not isinstance(params, list) or len(params) > 32:
        problems.append("parameters must be a list of at most 32.")
        params = []
    for i, p in enumerate(params, start=1):
        label = f"parameter {i}"
        if not isinstance(p, dict):
            problems.append(f"{label}: must be an object.")
            continue
        pname = p.get("name")
        if not isinstance(pname, str) or not 1 <= len(pname) <= 64:
            problems.append(f"{label}: name must be 1 to 64 characters.")
        elif pname in names:
            problems.append(f"{label}: name \"{pname}\" is used twice.")
        else:
            names.add(pname)
        label_text = p.get("label")
        if label_text is not None and (not isinstance(label_text, str) or len(label_text) > 120):
            problems.append(f"{label}: label must be at most 120 characters.")
        if p.get("unit") not in UNITS:
            problems.append(f"{label}: unit must be mm, deg or empty.")
    rows = m.get("rows")
    if not isinstance(rows, list) or not 2 <= len(rows) <= 32:
        problems.append("rows must be a list of 2 to 32 sizes.")
        return
    seen = set()
    defaults = 0
    for i, row in enumerate(rows, start=1):
        label = f"row {i}"
        if not isinstance(row, dict):
            problems.append(f"{label}: must be an object.")
            continue
        rname = row.get("name")
        if not isinstance(rname, str) or not 1 <= len(rname) <= 60:
            problems.append(f"{label}: name must be 1 to 60 characters.")
        elif rname.lower() in seen:
            problems.append(f"{label}: name \"{rname}\" is used twice.")
        else:
            seen.add(rname.lower())
        values = row.get("values", {})
        if not isinstance(values, dict):
            problems.append(f"{label}: values must be an object.")
        else:
            for key, v in values.items():
                if key not in names:
                    problems.append(f"{label}: \"{key}\" is not a listed parameter.")
                elif not _finite(v) or abs(v) > 1e6:
                    problems.append(f"{label}: \"{key}\" must be a number within 1e6.")
        if row.get("default") is True:
            defaults += 1
        check_path(row.get("step"), label, step_suffixes)
    if defaults > 1:
        problems.append("Only one row can be the default.")
