"""Capture, translate, then a recipe package or a stepOnly package. Pure: no Fusion imports.

Whatever goes wrong while reading or translating, the person still gets the STEP as a stepOnly package with one
plain note. The caller writes the STEP before it reads the capture.
"""
import inspect
import json

from ..package.manifest import (
    MAX_FIXED, build_recipe_manifest, build_step_only_manifest, check_step_path, validate_manifest)
from ..translator import CaptureError, translate
from ..translator.notes import inside_component_note, recipe_note, reader_failure_note, step_only_note, translate_failure_note
from .messages import fixed_note, recipe_saved_message, sizes_note, unchecked_note  # noqa: F401

MAX_RECIPE_BYTES = 8 * 1024 * 1024
_TOO_LARGE = {"index": None, "name": "", "type": "", "reason": "The recipe is too large to open."}
_NOT_WRITTEN = {"index": None, "name": "", "type": "", "reason": "The steps could not be written."}


def _json_bytes(value, **options):
    return json.dumps(value, ensure_ascii=False, **options).encode("utf-8")


def _report_bytes(report):
    try:
        return _json_bytes(report, indent=2, default=str)
    except (TypeError, ValueError):
        trimmed = {k: v for k, v in report.items() if k != "capture"}
        return _json_bytes(trimmed, indent=2, default=str)


def _recipe_bytes(recipe):
    """UTF-8 bytes of the recipe, or a refusal dict when it cannot be written or is above the reader cap."""
    try:
        data = _json_bytes(recipe, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return None, _NOT_WRITTEN
    if len(data) > MAX_RECIPE_BYTES:
        return None, _TOO_LARGE
    return data, None


def _with_up_axis(capture, up_axis):
    """The recipe turns by the same axis as the STEP's `upAxis`, so the dialog's choice wins over the detected one."""
    if capture.get("up_axis") == up_axis:
        return capture
    return {**capture, "up_axis": up_axis}


def _translate_with_sizes(capture, size_table):
    """Run the translator. The size table (lib/params) goes along when the translator takes `size_table`."""
    if size_table is not None and "size_table" in inspect.signature(translate).parameters:
        return translate(capture, size_table=size_table)
    return translate(capture)


def _free_sizes(recipe):
    """Names of the recipe sizes a form can change (not the formulas)."""
    sizes = (recipe or {}).get("sizes") or {}
    return [name for name, size in sizes.items() if isinstance(size, dict) and "value" in size]


def _merge_fixed(*lists):
    """Entries {'name', 'reason'} in order, the first entry per name wins, at most MAX_FIXED."""
    out, seen = [], set()
    for entries in lists:
        for entry in entries or []:
            name = entry.get("name")
            if name in seen or not name:
                continue
            seen.add(name)
            out.append({"name": name, "reason": entry.get("reason") or "Stays a fixed number."})
    return out[:MAX_FIXED]


def plan_single_export(capture_or_error, step_file, title, writer, up_axis, in_component=False,
                       size_table=None, checks=None, fixed=None, unchecked=None):
    """Return (manifest, files, report) for one body.

    capture_or_error: the reader's capture dict, or the exception the reader raised.
    in_component: the body is not in the root component, so no steps are translated and the part stays a fixed shape.
    size_table: the lib/params SizeTable of this export, or None for a recipe without sizes.
    checks: [{'size', 'value', 'step_file'}] from the size checks, one size changed in each. Only checks of sizes the
      recipe keeps free go into the package.
    fixed: [{'name', 'reason'}] parameters the export itself fixed (measured). The translator adds its own.
    unchecked: names of sizes that got no check, for the report.
    files maps entry paths to a file path or bytes, as write_package expects. Raises ValueError when the manifest
    breaks the package rules.
    """
    capture = capture_or_error if isinstance(capture_or_error, dict) else None
    result = None
    refusal = None
    note = None
    error = None
    if in_component:
        capture = None
        note = inside_component_note()
    elif capture is None:
        error = capture_or_error
        note = reader_failure_note()
    else:
        capture = _with_up_axis(capture, up_axis)
        try:
            result = _translate_with_sizes(capture, size_table)
        except CaptureError as exc:
            error, note = exc, reader_failure_note()
        except Exception as exc:
            error, note = exc, translate_failure_note()

    recipe_data = None
    if result is not None and result.recipe is not None:
        recipe_data, refusal = _recipe_bytes(result.recipe)
    elif result is not None:
        refusal = result.refusal

    free = _free_sizes(result.recipe) if recipe_data is not None else []
    kept = [c for c in (checks or []) if c["size"] in free]
    all_fixed = []
    if recipe_data is not None:
        all_fixed = _merge_fixed(fixed, getattr(size_table, "fixed", None), getattr(result, "fixed", None))

    report = {
        "writer": writer,
        "outcome": "recipe" if recipe_data is not None else "stepOnly",
        "items": list(result.items) if result is not None else [],
        "notes": list(result.notes) if result is not None else [],
    }
    if refusal is not None:
        report["refusal"] = refusal
    if error is not None:
        report["error"] = ("%s: %s" % (type(error).__name__, error))[:500]
    if capture is not None:
        report["capture"] = capture
    if recipe_data is not None:
        report["sizes"] = {"free": free, "fixed": all_fixed, "checks": [
            {"size": c["size"], "value": c["value"]} for c in kept], "unchecked": list(unchecked or [])}

    files = {"part.step": step_file}
    if recipe_data is not None:
        notes = [recipe_note(len(result.recipe["features"]))]
        if free:
            notes.append(sizes_note(len(free)))
        if all_fixed:
            notes.append(fixed_note([f["name"] for f in all_fixed]))
        if unchecked:
            notes.append(unchecked_note(len(unchecked)))
        manifest_checks = []
        for number, check in enumerate(kept, start=1):
            manifest_checks.append({"values": {check["size"]: check["value"]}, "step": check_step_path(number)})
            files[check_step_path(number)] = check["step_file"]
        manifest = build_recipe_manifest(
            title, writer, up_axis=up_axis, notes=notes, checks=manifest_checks, fixed=all_fixed)
        files["recipe.json"] = recipe_data
    else:
        notes = [note or step_only_note(refusal)]
        manifest = build_step_only_manifest(title, writer, up_axis=up_axis, notes=notes)
    files["report.json"] = _report_bytes(report)

    problems = validate_manifest(manifest)
    if problems:
        raise ValueError(" ".join(problems))
    return manifest, files, report
