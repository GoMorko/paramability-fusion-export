"""Capture, translate, then a recipe package or a stepOnly package. Pure: no Fusion imports.

Whatever goes wrong while reading or translating, the person still gets the STEP as a stepOnly package with one
plain note. The caller writes the STEP before it reads the capture.
"""
import json

from ..package.manifest import MAX_FIXED, build_recipe_manifest, build_step_only_manifest, validate_manifest
from ..package.text import clip
from ..translator import CaptureError, translate
from ..translator.notes import (
    recipe_note, reader_failure_note, step_only_note, translate_failure_note, used_several_times_note)
from .health import measuring_note
from .messages import MAX_NOTE, dropped_note, fixed_note, loose_note, sizes_note, unchanged_note

MAX_RECIPE_BYTES = 8 * 1024 * 1024
MAX_NOTES = 5  # the manifest limit; the last notes (not followed, not used) give way
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


def translate_capture(capture, up_axis, size_table=None, motion=None):
    """The translator's result for a capture turned to the dialog's up axis. Raises what the translator raises.

    `motion` is what the size probe found about sketch values (`sketch_values.motion`), or `sketch_values.motion.OPTIMISTIC` for a
    first look that fixes nothing for sketches. A size that some value cannot follow stays free with a warning
    (`TranslateResult.loose`); the ranges are the table's."""
    return translate(_with_up_axis(capture, up_axis), size_table=size_table, motion=motion)


def free_sizes(recipe):
    """Names of the recipe sizes a form can change (not the formulas)."""
    sizes = (recipe or {}).get("sizes") or {}
    return [name for name, size in sizes.items() if isinstance(size, dict) and "value" in size]


def _merge_fixed(size_table, *lists, skip=(), only=None):
    """Manifest entries {'name', 'reason'} in order, the first entry per size wins, at most MAX_FIXED.

    Names in the lists are Fusion parameter names (or recipe size names). The entry holds the recipe size name; the
    reason names the Fusion parameter when the two differ. Recipe names in `skip` are left out, and so is every name
    outside `only` when it is given.
    """
    out, seen = [], set(skip)
    for entries in lists:
        for entry in entries or []:
            name = entry.get("name")
            if not name:
                continue
            made = size_table.fixed_entry(name, entry.get("reason") or "Stays a fixed number.")
            if made["name"] in seen or (only is not None and made["name"] not in only):
                continue
            seen.add(made["name"])
            out.append(made)
    return out[:MAX_FIXED]


def _not_followed_note(names):
    text = "Could not follow these, so not sizes: %s." % ", ".join(names)
    return clip(text, MAX_NOTE)


def link_outcomes(size_table, sizes):
    """What happened to each geometry link of the export (`size_table.links`): the link with `outcome` ("size",
    "loose", "fixed", "dropped" or "not ticked") and the reason when there is one. `sizes` is the report's `sizes`
    record, or None when no recipe was written."""
    sizes = sizes or {}
    free = set(sizes.get("free") or [])
    loose = {e["name"]: e["reason"] for e in sizes.get("loose") or []}
    fixed = {e["name"]: e["reason"] for e in sizes.get("fixed") or []}
    dropped = {e["name"]: e["reason"] for e in sizes.get("dropped") or []}
    out = []
    for link in size_table.links:
        name = link["param"]
        recipe = size_table.recipe_name(name)
        if recipe in fixed:
            found = {"outcome": "fixed", "reason": fixed[recipe]}
        elif recipe in loose:
            found = {"outcome": "loose", "reason": loose[recipe]}
        elif recipe in free:
            found = {"outcome": "size"}
        elif name in dropped:
            found = {"outcome": "dropped", "reason": dropped[name]}
        else:
            found = {"outcome": "not ticked" if name not in size_table.ticked else "dropped"}
        out.append({**link, **found})
    return out


def _uses(capture):
    """How many times Fusion uses the component of the picked body (1 for a root body)."""
    placement = ((capture or {}).get("target") or {}).get("placement")
    uses = placement.get("uses") if isinstance(placement, dict) else 1
    return uses if isinstance(uses, int) and not isinstance(uses, bool) else 1


def plan_single_export(capture_or_error, step_file, title, writer, up_axis,
                       size_table=None, listing=None, motion=None, probe=None, marker=None, loose=None,
                       translated=None, health=None, also=None):
    """Return (manifest, files, report) for one body.

    A body inside a component is translated like a root body: its capture carries the place of the part in the
    assembly, and the recipe is written there. A linked part, a place that cannot be read, or a step across
    components makes the part a fixed shape with its own note.

    capture_or_error: the reader's capture dict, or the exception the reader raised.
    size_table: the SizeTable of this export, or None for a recipe without sizes. A ticked size that no
      copied step uses is named in a note and in `report.json` ("dropped", with the reason).
    loose: [{'name', 'reason'}] sizes the export keeps free although it could not follow them fully (measured), by
      Fusion name. The translator adds its own. The manifest lists those the recipe keeps free, by recipe size name.
    health: how the design came out of the export (`export_plan.health.make_health`), for `report.json` and one note
      when the sketch measurements cannot be trusted.
    translated: the translator's result for these same inputs (`translate_capture`), when the caller has it already.
      A result without a recipe (a refusal) is used as it is: nothing is translated a second time. Only None
      translates here.
    listing: the design's ParameterListing (params.listing). Its entries go into the manifest `parameters` of every
      package kind, so the Fusion parameters reach Paramability even when the shape stays fixed.
    motion: what the size probe found for sketch values (`sketch_values.motion.Motion`), or None for a translation that
      fixes every size behind a sketch.
    probe: the size probe's own record for `report.json` (request, states read, motion, restore gap), or None.
    marker: { position, count } of the timeline marker the export worked at (`design_edit.marker.read_marker`), for
      `report.json`. Steps after the position are left out of the part.
    also: Fusion names of unticked parameters the size probe saw changing the part (`report.json` "also_changes").
    files maps entry paths to a file path or bytes, as write_package expects. The manifest `checks` list is empty.
    Raises ValueError when the manifest breaks the package rules.
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
            result = translated or translate(capture, size_table=size_table, motion=motion)
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
    all_fixed, all_loose, dropped = [], [], []
    if recipe_data is not None and size_table is not None:
        all_fixed = _merge_fixed(size_table, size_table.fixed, result.fixed)
        all_loose = _merge_fixed(size_table, loose, result.loose,
                                 skip={f["name"] for f in all_fixed}, only=set(free))
        fixed_names = {f["name"] for f in all_fixed}
        dropped = [d for d in result.dropped if size_table.recipe_name(d["name"]) not in fixed_names]

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
    if marker is not None:
        report["marker"] = dict(marker)
    if capture is not None:
        report["capture"] = capture
    if probe is not None:
        report["probe"] = probe
    if health is not None:
        report["health"] = health
    if listing is not None:
        report["parameters"] = listing.report()
    if recipe_data is not None:
        report["sizes"] = {"free": free, "fixed": all_fixed, "loose": all_loose, "dropped": dropped}
    if size_table is not None and size_table.links:
        report["links"] = link_outcomes(size_table, report.get("sizes"))
    if also:
        report["also_changes"] = list(also)

    files = {"part.step": step_file}
    listed = listing.entries if listing is not None else None
    if recipe_data is not None:
        first = recipe_note(len(result.recipe["features"]))
        if _uses(capture) > 1:
            first += " " + used_several_times_note(_uses(capture))
        notes = [first]
        doubt = measuring_note(health)
        if doubt:
            notes.append(doubt)
        if free:
            notes.append(sizes_note(len(free)))
        if all_loose:
            notes.append(loose_note([f["name"] for f in all_loose]))
        if all_fixed:
            notes.append(fixed_note([f["name"] for f in all_fixed]))
        not_followed = [d["name"] for d in dropped if d["used"]]
        unused = [d["name"] for d in dropped if not d["used"] and not d.get("tried")]
        unchanged = [d["name"] for d in dropped if not d["used"] and d.get("tried")]
        if not_followed:
            notes.append(_not_followed_note(not_followed))
        if unchanged:
            notes.append(unchanged_note(unchanged))
        if unused:
            notes.append(dropped_note(unused))
        del notes[MAX_NOTES:]
        manifest = build_recipe_manifest(
            title, writer, up_axis=up_axis, notes=notes, fixed=all_fixed, parameters=listed, loose=all_loose)
        files["recipe.json"] = recipe_data
    else:
        notes = [note or step_only_note(refusal)]
        manifest = build_step_only_manifest(title, writer, up_axis=up_axis, notes=notes, parameters=listed)
    files["report.json"] = _report_bytes(report)

    problems = validate_manifest(manifest)
    if problems:
        raise ValueError(" ".join(problems))
    return manifest, files, report
