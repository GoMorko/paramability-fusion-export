"""Manifest builders and a local check of the package rules. The app stays the authority."""
import math
import re

SCHEMA = "paramability.recipePackage"
VERSION = 1
KINDS = ("valueRows", "recipe", "stepOnly", "parts")
UNITS = ("mm", "deg", "")
MAX_CHECKS = 64
MAX_PARTS = 32
MAX_PART_NAME = 60
MAX_PART_NOTE = 200
MAX_PART_CHECKS = 16
MAX_PARTS_CHECKS = 128
MAX_FIXED = 64
MAX_FIXED_REASON = 200
MAX_NAME_CHARS = 64
MAX_PARAMETERS = 64
MAX_PARAMETER_LABEL = 64
MAX_PARAMETER_COMMENT = 200
MAX_PARAMETER_EXPR = 300
VALUE_LIMIT = 1e6

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


def build_step_only_manifest(name, writer, up_axis="z", notes=None, parameters=None):
    """parameters: the design's user parameter entries; the key is left out when the list is empty."""
    manifest = {
        "schema": SCHEMA,
        "version": VERSION,
        "kind": "stepOnly",
        "name": name,
        "upAxis": up_axis,
        "writer": writer,
        "notes": list(notes or []),
        "part": "part.step",
    }
    _add_parameters(manifest, parameters)
    return manifest


def build_recipe_manifest(name, writer, up_axis="z", notes=None, checks=None, fixed=None, parameters=None,
                          loose=None):
    """A translated part: the STEP files plus recipe.json.

    checks: [{'values': {size name: number}, 'step': 'checks/01.step'}], one size changed per check.
    fixed: [{'name', 'reason'}] for Fusion parameters that stay fixed numbers in the shape. Left out when empty.
    loose: [{'name', 'reason'}] for recipe sizes that stay free but may not follow every step. Left out when empty.
    parameters: the design's user parameter entries. Left out when empty.
    """
    manifest = {
        "schema": SCHEMA,
        "version": VERSION,
        "kind": "recipe",
        "name": name,
        "upAxis": up_axis,
        "writer": writer,
        "notes": list(notes or []),
        "part": "part.step",
        "recipe": "recipe.json",
        "checks": [dict(c) for c in (checks or [])],
    }
    if fixed:
        manifest["fixed"] = [dict(f) for f in fixed]
    if loose:
        manifest["loose"] = [dict(f) for f in loose]
    _add_parameters(manifest, parameters)
    return manifest


def build_parts_manifest(name, writer, parts, up_axis="z", notes=None, fixed=None, parameters=None):
    """Several bodies of one design in one file: shared sizes, one object per part.

    parts: [{'name', 'step', 'recipe', 'note', 'loose', 'checks'}] in order. `step` is a path in the zip. A part
      without `recipe` is a fixed shape (`note` says why). `loose` ([{'name', 'reason'}]) lists the sizes of that
      part's recipe that may not follow every step. `note` and `checks` are left out when empty.
    fixed: [{'name', 'reason'}] for sizes that stay fixed numbers in every part. Left out when empty.
    parameters: the design's user parameter entries, shared by all parts. Left out when empty.
    """
    out_parts = []
    for part in parts:
        entry = {"name": part["name"], "step": part["step"]}
        if part.get("recipe"):
            entry["recipe"] = part["recipe"]
        if part.get("note"):
            entry["note"] = part["note"]
        if part.get("loose"):
            entry["loose"] = [dict(f) for f in part["loose"]]
        if part.get("checks"):
            entry["checks"] = [dict(c) for c in part["checks"]]
        out_parts.append(entry)
    manifest = {
        "schema": SCHEMA,
        "version": VERSION,
        "kind": "parts",
        "name": name,
        "upAxis": up_axis,
        "writer": writer,
        "notes": list(notes or []),
        "parts": out_parts,
    }
    if fixed:
        manifest["fixed"] = [dict(f) for f in fixed]
    _add_parameters(manifest, parameters)
    return manifest


def part_step_path(number):
    return f"parts/{number:02d}/part.step"


def part_recipe_path(number):
    return f"parts/{number:02d}/recipe.json"


def _add_parameters(manifest, parameters):
    if parameters:
        manifest["parameters"] = [dict(p) for p in parameters]


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
        problems.append("kind must be valueRows, recipe, stepOnly or parts.")
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

    if kind in ("stepOnly", "recipe", "parts"):
        _validate_parameters(m.get("parameters"), problems)

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
        if not isinstance(checks, list) or len(checks) > MAX_CHECKS:
            problems.append(f"checks must be a list of at most {MAX_CHECKS}.")
        else:
            for i, c in enumerate(checks, start=1):
                label = f"check {i}"
                vals = c.get("values") if isinstance(c, dict) else None
                if not isinstance(vals, dict) or not vals or not all(
                        _finite(v) and abs(v) <= VALUE_LIMIT for v in vals.values()):
                    problems.append(f"{label}: values must be a non empty map of numbers within 1e6.")
                elif not all(isinstance(k, str) and 1 <= len(k) <= MAX_NAME_CHARS for k in vals):
                    problems.append(f"{label}: size names must be 1 to {MAX_NAME_CHARS} characters.")
                check_path(c.get("step") if isinstance(c, dict) else None, label, step_suffixes)
        _validate_fixed(m.get("fixed"), problems)
        _validate_fixed(m.get("loose"), problems, "loose")
    elif kind == "parts":
        _validate_parts(m, problems, check_path, step_suffixes)
    elif kind == "valueRows":
        _validate_value_rows(m, problems, check_path, step_suffixes)
    return problems


def _validate_checks(checks, label, problems, check_path, step_suffixes, limit):
    """The `checks` list of a recipe or a part: at most `limit` entries of size values and a STEP path each."""
    if not isinstance(checks, list) or len(checks) > limit:
        problems.append(f"{label}: checks must be a list of at most {limit}.")
        return 0
    for i, c in enumerate(checks, start=1):
        name = f"{label} check {i}"
        vals = c.get("values") if isinstance(c, dict) else None
        if not isinstance(vals, dict) or not vals or not all(
                _finite(v) and abs(v) <= VALUE_LIMIT for v in vals.values()):
            problems.append(f"{name}: values must be a non empty map of numbers within 1e6.")
        elif not all(isinstance(k, str) and 1 <= len(k) <= MAX_NAME_CHARS for k in vals):
            problems.append(f"{name}: size names must be 1 to {MAX_NAME_CHARS} characters.")
        check_path(c.get("step") if isinstance(c, dict) else None, name, step_suffixes)
    return len(checks)


def _validate_parts(m, problems, check_path, step_suffixes):
    parts = m.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_PARTS:
        problems.append(f"parts must be a list of 1 to {MAX_PARTS}.")
        return
    _validate_fixed(m.get("fixed"), problems)
    seen, checks = set(), 0
    for i, part in enumerate(parts, start=1):
        label = f"part {i}"
        if not isinstance(part, dict):
            problems.append(f"{label}: must be an object.")
            continue
        name = part.get("name")
        if not isinstance(name, str) or not 1 <= _clean_len(name) <= MAX_PART_NAME:
            problems.append(f"{label}: name must be 1 to {MAX_PART_NAME} characters.")
        elif name.lower() in seen:
            problems.append(f"{label}: name \"{name}\" is used twice.")
        else:
            seen.add(name.lower())
        check_path(part.get("step"), label, step_suffixes)
        if part.get("recipe") is not None:
            check_path(part["recipe"], f"{label} recipe", (".json",))
        note = part.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > MAX_PART_NOTE):
            problems.append(f"{label}: note must be text of at most {MAX_PART_NOTE} characters.")
        _validate_fixed(part.get("loose"), problems, f"{label} loose")
        if part.get("checks") is not None:
            checks += _validate_checks(part["checks"], label, problems, check_path, step_suffixes, MAX_PART_CHECKS)
    if checks > MAX_PARTS_CHECKS:
        problems.append(f"checks must be at most {MAX_PARTS_CHECKS} in all.")


def _validate_fixed(fixed, problems, key="fixed"):
    """The `fixed` or `loose` list: { name, reason } entries."""
    if fixed is None:
        return
    if not isinstance(fixed, list) or len(fixed) > MAX_FIXED:
        problems.append(f"{key} must be a list of at most {MAX_FIXED}.")
        return
    for i, entry in enumerate(fixed, start=1):
        label = f"{key} {i}"
        if not isinstance(entry, dict):
            problems.append(f"{label}: must be an object.")
            continue
        name, reason = entry.get("name"), entry.get("reason")
        if not isinstance(name, str) or not 1 <= len(name) <= MAX_NAME_CHARS:
            problems.append(f"{label}: name must be 1 to {MAX_NAME_CHARS} characters.")
        if not isinstance(reason, str) or not 1 <= len(reason) <= MAX_FIXED_REASON:
            problems.append(f"{label}: reason must be 1 to {MAX_FIXED_REASON} characters.")


def _validate_parameters(params, problems):
    """Check the optional `parameters` list of a stepOnly or recipe manifest (valueRows has its own columns list)."""
    names = set()
    if params is None:
        return
    if not isinstance(params, list) or len(params) > MAX_PARAMETERS:
        problems.append(f"parameters must be a list of at most {MAX_PARAMETERS}.")
        return
    for i, p in enumerate(params, start=1):
        label = f"parameter {i}"
        if not isinstance(p, dict):
            problems.append(f"{label}: must be an object.")
            continue
        pname = p.get("name")
        if not isinstance(pname, str) or not 1 <= len(pname) <= MAX_NAME_CHARS:
            problems.append(f"{label}: name must be 1 to {MAX_NAME_CHARS} characters.")
        elif pname in names:
            problems.append(f"{label}: name \"{pname}\" is used twice.")
        else:
            names.add(pname)
        text = p.get("label")
        if text is not None and (not isinstance(text, str) or len(text) > MAX_PARAMETER_LABEL):
            problems.append(f"{label}: label must be at most {MAX_PARAMETER_LABEL} characters.")
        if p.get("unit", "") not in UNITS:
            problems.append(f"{label}: unit must be mm, deg or empty.")
        if "value" in p and not _finite(p["value"]):
            problems.append(f"{label}: value must be a number.")
        expr = p.get("expr")
        if expr is not None and (not isinstance(expr, str) or not 1 <= len(expr) <= MAX_PARAMETER_EXPR):
            problems.append(f"{label}: expr must be 1 to {MAX_PARAMETER_EXPR} characters.")
        comment = p.get("comment")
        if comment is not None and (not isinstance(comment, str) or len(comment) > MAX_PARAMETER_COMMENT):
            problems.append(f"{label}: comment must be at most {MAX_PARAMETER_COMMENT} characters.")


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
