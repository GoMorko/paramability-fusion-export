"""Capture, translate, then a recipe package or a stepOnly package. Pure: no Fusion imports.

Whatever goes wrong while reading or translating, the person still gets the STEP as a stepOnly package with one
plain note. The caller writes the STEP before it reads the capture.
"""
import json

from ..package.manifest import (
    MAX_FIXED, build_recipe_manifest, build_step_only_manifest, check_step_path, validate_manifest)
from ..translator import CaptureError, translate
from ..translator.notes import (
    recipe_note, reader_failure_note, step_only_note, translate_failure_note, used_several_times_note)
from .messages import dropped_note, fixed_note, sizes_note, unchecked_note

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


def translate_capture(capture, up_axis, size_table=None):
    """The translator's result for a capture turned to the dialog's up axis. Raises what the translator raises."""
    return translate(_with_up_axis(capture, up_axis), size_table=size_table)


def free_sizes(recipe):
    """Names of the recipe sizes a form can change (not the formulas)."""
    sizes = (recipe or {}).get("sizes") or {}
    return [name for name, size in sizes.items() if isinstance(size, dict) and "value" in size]


def _merge_fixed(size_table, *lists):
    """Manifest entries {'name', 'reason'} in order, the first entry per size wins, at most MAX_FIXED.

    Names in the lists are Fusion parameter names (or recipe size names). The entry holds the recipe size name; the
    reason names the Fusion parameter when the two differ.
    """
    out, seen = [], set()
    for entries in lists:
        for entry in entries or []:
            name = entry.get("name")
            if not name:
                continue
            made = size_table.fixed_entry(name, entry.get("reason") or "Stays a fixed number.")
            if made["name"] in seen:
                continue
            seen.add(made["name"])
            out.append(made)
    return out[:MAX_FIXED]


def _dropped(size_table, recipe, fixed):
    """Fusion names the person ticked that the recipe does not hold as sizes: no step uses them, and they are not
    among the fixed ones."""
    sizes = (recipe or {}).get("sizes") or {}
    fixed_names = {f["name"] for f in fixed}
    return [n for n in size_table.ticked
            if size_table.size_name(n) not in sizes and size_table.recipe_name(n) not in fixed_names]


def _uses(capture):
    """How many times Fusion uses the component of the picked body (1 for a root body)."""
    placement = ((capture or {}).get("target") or {}).get("placement")
    uses = placement.get("uses") if isinstance(placement, dict) else 1
    return uses if isinstance(uses, int) and not isinstance(uses, bool) else 1


def plan_single_export(capture_or_error, step_file, title, writer, up_axis,
                       size_table=None, checks=None, fixed=None, unchecked=None, listing=None):
    """Return (manifest, files, report) for one body.

    A body inside a component is translated like a root body: its capture carries the place of the part in the
    assembly, and the recipe is written there. A linked part, a place that cannot be read, or a step across
    components makes the part a fixed shape with its own note.

    capture_or_error: the reader's capture dict, or the exception the reader raised.
    size_table: the SizeTable of this export, or None for a recipe without sizes. A ticked size that no
      copied step uses is named in a note and in `report.json` ("dropped").
    checks: [{'size', 'value', 'step_file'}] from the size checks, one size changed in each. Only checks of sizes the
      recipe keeps free go into the package.
    fixed: [{'name', 'reason'}] parameters the export itself fixed (measured), by Fusion name. The translator adds its
      own. The manifest lists them by recipe size name.
    unchecked: names of sizes that got no check, for the report.
    listing: the design's ParameterListing (params.listing). Its entries go into the manifest `parameters` of every
      package kind, so the Fusion parameters reach Paramability even when the shape stays fixed.
    files maps entry paths to a file path or bytes, as write_package expects. Raises ValueError when the manifest
    breaks the package rules.
    """
    capture = capture_or_error if isinstance(capture_or_error, dict) else None
    result = None
    refusal = None
    note = None
    error = None
    if capture is None:
        error = capture_or_error
        note = reader_failure_note()
    else:
        capture = _with_up_axis(capture, up_axis)
        try:
            result = translate(capture, size_table=size_table)
        except CaptureError as exc:
            error, note = exc, reader_failure_note()
        except Exception as exc:
            error, note = exc, translate_failure_note()

    recipe_data = None
    if result is not None and result.recipe is not None:
        recipe_data, refusal = _recipe_bytes(result.recipe)
    elif result is not None:
        refusal = result.refusal

    free = free_sizes(result.recipe) if recipe_data is not None else []
    kept = [c for c in (checks or []) if c["size"] in free]
    all_fixed, dropped = [], []
    if recipe_data is not None and size_table is not None:
        all_fixed = _merge_fixed(size_table, fixed, size_table.fixed, getattr(result, "fixed", None))
        dropped = _dropped(size_table, result.recipe, all_fixed)

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
    if listing is not None:
        report["parameters"] = listing.report()
    if recipe_data is not None:
        report["sizes"] = {"free": free, "fixed": all_fixed, "checks": [
            {"size": c["size"], "value": c["value"]} for c in kept], "unchecked": list(unchecked or []),
            "dropped": dropped}

    files = {"part.step": step_file}
    listed = listing.entries if listing is not None else None
    if recipe_data is not None:
        first = recipe_note(len(result.recipe["features"]))
        if _uses(capture) > 1:
            first += " " + used_several_times_note(_uses(capture))
        notes = [first]
        if free:
            notes.append(sizes_note(len(free)))
        if all_fixed:
            notes.append(fixed_note([f["name"] for f in all_fixed]))
        if dropped:
            notes.append(dropped_note(dropped))
        if unchecked:
            notes.append(unchecked_note(len(unchecked)))
        manifest_checks = []
        for number, check in enumerate(kept, start=1):
            manifest_checks.append({"values": {check["size"]: check["value"]}, "step": check_step_path(number)})
            files[check_step_path(number)] = check["step_file"]
        manifest = build_recipe_manifest(
            title, writer, up_axis=up_axis, notes=notes, checks=manifest_checks, fixed=all_fixed,
            parameters=listed)
        files["recipe.json"] = recipe_data
    else:
        notes = [note or step_only_note(refusal)]
        manifest = build_step_only_manifest(title, writer, up_axis=up_axis, notes=notes, parameters=listed)
    files["report.json"] = _report_bytes(report)

    problems = validate_manifest(manifest)
    if problems:
        raise ValueError(" ".join(problems))
    return manifest, files, report
