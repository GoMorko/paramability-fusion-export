"""Capture, translate, then a recipe package or a stepOnly package. Pure: no Fusion imports.

Whatever goes wrong while reading or translating, the person still gets the STEP as a stepOnly package with one
plain note. The caller writes the STEP before it reads the capture.
"""
import inspect
import json

from ..package.manifest import (
    MAX_FIXED, build_recipe_manifest, build_step_only_manifest, check_step_path, validate_manifest)
from ..package.text import clip
from ..probe.plan import sketch_driven
from ..translator import CaptureError, translate
from ..translator.notes import (
    recipe_note, reader_failure_note, step_only_note, translate_failure_note, used_several_times_note)
from .health import measuring_note
from .messages import (
    MAX_NOTE, dropped_note, fixed_note, loose_note, narrowed_notes, sizes_note, unchecked_note)

MAX_RECIPE_BYTES = 8 * 1024 * 1024
MAX_NOTES = 5  # the manifest limit; the last notes (shortened ranges, not used, not checked) give way
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


def _translated(capture, size_table, motion, loose=True, plain=False):
    """`translate`, handing over the sketch motion and the loose and plain modes when the translator takes them."""
    taken = inspect.signature(translate).parameters
    options = {}
    if motion is not None and "motion" in taken:
        options["motion"] = motion
    if size_table is not None and "loose" in taken:
        options["loose"] = loose
    if plain and size_table is not None and "plain" in taken:
        options["plain"] = True
    return translate(capture, size_table=size_table, **options)


def translate_capture(capture, up_axis, size_table=None, motion=None, loose=True, plain=False):
    """The translator's result for a capture turned to the dialog's up axis. Raises what the translator raises.

    `motion` is what the size probe found about sketch values (`probe.motion`), or `probe.motion.OPTIMISTIC` for a
    first look that fixes nothing for sketches. With `loose` a size that some value cannot follow stays free with a
    warning (`TranslateResult.loose`) instead of being fixed. With `plain` no range is raised or shortened either."""
    return _translated(_with_up_axis(capture, up_axis), size_table, motion, loose, plain)


def with_translated_limits(table, result):
    """`table` with the minimums a translation raised and the ranges it shortened (`TranslateResult.raised`,
    `narrowed`), so that the checks are planned inside the ranges the recipe gives its sizes."""
    raised = {r["name"]: r["min"] for r in getattr(result, "raised", None) or []}
    shortened = {r["name"]: (r["min"], r["max"]) for r in getattr(result, "narrowed", None) or []}
    table = table.with_minimums(raised) if raised else table
    return table.with_narrowed(shortened) if shortened else table


def free_sizes(recipe):
    """Names of the recipe sizes a form can change (not the formulas)."""
    sizes = (recipe or {}).get("sizes") or {}
    return [name for name, size in sizes.items() if isinstance(size, dict) and "value" in size]


def _one_period(text):
    """A reason that already ends in a full stop and got a second one ("Fusion says 32..") ends in one."""
    return text[:-1] if text.endswith("..") and not text.endswith("...") else text


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
            made = size_table.fixed_entry(name, _one_period(entry.get("reason") or "Stays a fixed number."))
            if made["name"] in seen or (only is not None and made["name"] not in only):
                continue
            seen.add(made["name"])
            out.append(made)
    return out[:MAX_FIXED]


def _in_range(check, sizes):
    """True when the check's value lies in the range the recipe gives its size."""
    size = sizes.get(check["size"]) or {}
    lo, hi = size.get("min", check["value"]), size.get("max", check["value"])
    return lo - 1e-9 <= check["value"] <= hi + 1e-9


def _dropped(size_table, recipe, fixed):
    """Fusion names the person ticked that the recipe does not hold as sizes: no step uses them, and they are not
    among the fixed ones."""
    sizes = (recipe or {}).get("sizes") or {}
    fixed_names = {f["name"] for f in fixed}
    return [n for n in size_table.ticked
            if size_table.size_name(n) not in sizes and size_table.recipe_name(n) not in fixed_names]


def _not_followed(size_table, dropped):
    """The dropped sizes that change a sketch or a construction plane: they are used, but could not be followed."""
    reaching = set(sketch_driven(size_table))
    return [n for n in dropped if n in reaching]


def _not_followed_note(names):
    text = "Could not follow these through the sketches, so not sizes: %s." % ", ".join(names)
    return clip(text, MAX_NOTE)


def _uses(capture):
    """How many times Fusion uses the component of the picked body (1 for a root body)."""
    placement = ((capture or {}).get("target") or {}).get("placement")
    uses = placement.get("uses") if isinstance(placement, dict) else 1
    return uses if isinstance(uses, int) and not isinstance(uses, bool) else 1


def _step_narrowed(size_table, result, free):
    """Records like the export's own narrowed ones for the ranges the translator shortened, so a step keeps meeting
    the part (`TranslateResult.narrowed`): one per end that moved, the reason on the first."""
    out = []
    for r in getattr(result, "narrowed", None) or []:
        size = size_table.size_name(r["name"]) if size_table is not None else None
        before = size_table.sizes.get(size) if size in free else None
        if not before:
            continue
        note = r["reason"]
        for side in ("min", "max"):
            if abs(r[side] - before[side]) > 1e-9:
                out.append({"param": r["name"], "size": size, "side": side, "from": before[side], "to": r[side],
                            "min": r["min"], "max": r["max"], "items": [], "note": note})
                note = ""
    return out


def plan_single_export(capture_or_error, step_file, title, writer, up_axis,
                       size_table=None, checks=None, fixed=None, unchecked=None, listing=None, motion=None,
                       probe=None, build_failures=None, narrowed=None, marker=None, loose=None, loose_sizes=True,
                       translated=None, plain=False, health=None):
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
    loose: [{'name', 'reason'}] sizes the export keeps free although it could not follow them fully (measured), by
      Fusion name. The translator adds its own. The manifest lists those the recipe keeps free, by recipe size name.
    loose_sizes: False makes the translator fix every size that some value cannot follow (the dialog's "Keep doubtful
      sizes fixed"). The report records it as `keep_doubtful`.
    health: how the design came out of the export (`export_plan.health.make_health`), for `report.json` and one note
      when the sketch measurements cannot be trusted.
    translated: the translator's result for these same inputs (`translate_capture`), when the caller has it already.
    unchecked: names of sizes that got no check, for the report.
    listing: the design's ParameterListing (params.listing). Its entries go into the manifest `parameters` of every
      package kind, so the Fusion parameters reach Paramability even when the shape stays fixed.
    motion: what the size probe found for sketch values (`probe.motion.Motion`), or None for a translation that
      fixes every size behind a sketch.
    probe: the size probe's own record for `report.json` (request, states read, motion, restore gap), or None.
    build_failures: the size checks Fusion could not build, with why (`size_checks.build_failures`), for `report.json`.
    narrowed: [{'size', 'side', 'from', 'to', 'note', ...}] sizes whose range the export shortened because Fusion
      could not build the part at the end (`size_narrowing.Narrowing.narrowed`). The table already holds the new range.
      Those the recipe keeps free get a note and a record in `report.json`.
    marker: { position, count } of the timeline marker the export worked at (`export_plan.marker.read_marker`), for
      `report.json`. Steps after the position are left out of the part.
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
            result = translated or _translated(capture, size_table, motion, loose_sizes, plain)
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
    recipe_sizes = (result.recipe.get("sizes") or {}) if recipe_data is not None else {}
    kept = [c for c in (checks or []) if c["size"] in free]
    # A check below a minimum the translator raised, or past a range it shortened, cannot be used.
    outside = [c["size"] for c in kept if not _in_range(c, recipe_sizes)]
    kept = [c for c in kept if c["size"] not in outside]
    unchecked = list(unchecked or []) + [n for n in outside if n not in (unchecked or [])]
    all_fixed, all_loose, dropped, not_followed = [], [], [], []
    if recipe_data is not None and size_table is not None:
        all_fixed = _merge_fixed(size_table, fixed, size_table.fixed, getattr(result, "fixed", None))
        all_loose = _merge_fixed(size_table, loose, getattr(result, "loose", None),
                                 skip={f["name"] for f in all_fixed}, only=set(free))
        dropped = _dropped(size_table, result.recipe, all_fixed)
        # With a motion the sketches were measured, so a dropped size there simply moves nothing a step copies.
        not_followed = _not_followed(size_table, dropped) if motion is None else []

    kept_narrowed = [n for n in narrowed or [] if n["size"] in free] + _step_narrowed(size_table, result, free)
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
    if size_table is not None:
        report["check_sizes"] = not plain
        report["keep_doubtful"] = not loose_sizes
    if capture is not None:
        report["capture"] = capture
    if probe is not None:
        report["probe"] = probe
    if health is not None:
        report["health"] = health
    if listing is not None:
        report["parameters"] = listing.report()
    if recipe_data is not None:
        report["sizes"] = {"free": free, "fixed": all_fixed, "loose": all_loose, "checks": [
            {"size": c["size"], "value": c["value"]} for c in kept], "unchecked": list(unchecked or []),
            "dropped": dropped, "not_followed": not_followed, "build_failures": list(build_failures or [])}
        raised = [{"name": size_table.size_name(r["name"]), "min": r["min"], "reason": r["reason"]}
                  for r in getattr(result, "raised", None) or []
                  if size_table is not None and size_table.size_name(r["name"]) in free]
        if raised:
            report["sizes"]["raised"] = raised
        if kept_narrowed:
            report["sizes"]["narrowed"] = kept_narrowed

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
        notes.extend(narrowed_notes([n["note"] for n in kept_narrowed if n["note"]]))
        unused = [n for n in dropped if n not in not_followed]
        if not_followed:
            notes.append(_not_followed_note(not_followed))
        if unused:
            notes.append(dropped_note(unused))
        if unchecked and not plain:
            notes.append(unchecked_note(len(unchecked)))
        del notes[MAX_NOTES:]
        manifest_checks = []
        for number, check in enumerate(kept, start=1):
            manifest_checks.append({"values": {check["size"]: check["value"]}, "step": check_step_path(number)})
            files[check_step_path(number)] = check["step_file"]
        manifest = build_recipe_manifest(
            title, writer, up_axis=up_axis, notes=notes, checks=manifest_checks, fixed=all_fixed,
            parameters=listed, loose=all_loose)
        files["recipe.json"] = recipe_data
    else:
        notes = [note or step_only_note(refusal)]
        manifest = build_step_only_manifest(title, writer, up_axis=up_axis, notes=notes, parameters=listed)
    files["report.json"] = _report_bytes(report)

    problems = validate_manifest(manifest)
    if problems:
        raise ValueError(" ".join(problems))
    return manifest, files, report
