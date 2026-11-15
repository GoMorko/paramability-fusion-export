"""Capture, translate, then a recipe package or a stepOnly package. Pure: no Fusion imports.

Whatever goes wrong while reading or translating, the person still gets the STEP as a stepOnly package with one
plain note. The caller writes the STEP before it reads the capture.
"""
import json
from dataclasses import dataclass
from typing import Any, Optional

from ..capture_model.gap_hints import hint as gap_hint
from ..package.gaps_file import gaps_file_bytes
from ..package.manifest import (
    GAPS_ENTRY, MAX_FIXED, MAX_PART_NOTE, build_parts_manifest, build_recipe_manifest, build_step_only_manifest,
    part_gaps_path, part_recipe_path, part_step_path, validate_manifest)
from ..package.text import clip
from ..params.size_table import CONSTANT, DERIVED
from ..translator import CaptureError, translate
from ..timing.export_timing import attach as attach_timing, stamp as timing_stamp
from ..translator.notes import (
    also_failing_note, cut_reason, left_out_note, recipe_note, reader_failure_note, step_only_note,
    translate_failure_note, used_several_times_note)
from .health import measuring_note
from .messages import (
    MAX_NOTE, ORIGINAL_KEPT_NOTE, ORIGINAL_KEPT_PARTS_NOTE, cut_note, dropped_note, fixed_note, left_out_parts_note, loose_note,
    part_left_out_note, sizes_note, unchanged_note)
from .part_names import tagged

MAX_RECIPE_BYTES = 8 * 1024 * 1024
MAX_NOTES = 5  # the manifest limit; `_most_useful` picks which notes stay
_TOO_LARGE = {"index": None, "name": "", "type": "", "reason": "The recipe is too large to open."}
_NOT_WRITTEN = {"index": None, "name": "", "type": "", "reason": "The steps could not be written."}
_GAPS_NOT_WRITTEN = {"index": None, "name": "", "type": "",
                     "reason": "The list of steps left out could not be written."}


def _json_bytes(value, **options):
    return json.dumps(value, ensure_ascii=False, **options).encode("utf-8")


def _report_bytes(report):
    """`report.json` without indentation: it is read by tools, not by eye, and the compact form is written by the
    fast JSON encoder and takes about a third of the room of an indented one on a large probe."""
    try:
        return _json_bytes(report, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        trimmed = {k: v for k, v in report.items() if k != "capture"}
        return _json_bytes(trimmed, separators=(",", ":"), default=str)


def _recipe_bytes(recipe):
    """UTF-8 bytes of the recipe, or a refusal dict when it cannot be written or is above the reader cap."""
    try:
        data = _json_bytes(recipe, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return None, _NOT_WRITTEN
    if len(data) > MAX_RECIPE_BYTES:
        return None, _TOO_LARGE
    return data, None


def _recipe_and_gaps(result):
    """`(recipe bytes, gaps bytes, refusal)` of a translation that has a recipe. A recipe that leaves steps out needs
    its gaps file: when that cannot be written the part is not a recipe at all."""
    data, refusal = _recipe_bytes(result.recipe)
    if data is None or not result.gaps:
        return data, None, refusal
    gaps = gaps_file_bytes(result.gaps, result.to_recipe)
    if gaps is None:
        return None, None, _GAPS_NOT_WRITTEN
    return data, gaps, None


def _most_useful(ranked):
    """The notes of `[(rank, note)]` (in the order they are shown) that fit in MAX_NOTES: the lowest ranks stay, in
    their order, and empty notes are dropped. The count of steps, the steps left out and the loose and fixed sizes
    rank first, so that the notes about sizes that are not followed or not used give way first."""
    present = [(rank, n, note) for n, (rank, note) in enumerate(ranked) if note]
    kept = sorted(sorted(present)[:MAX_NOTES], key=lambda entry: entry[1])
    return [note for _, _, note in kept]


def _with_up_axis(capture, up_axis):
    """The recipe turns by the same axis as the STEP's `upAxis`, so the dialog's choice wins over the detected one."""
    if capture.get("up_axis") == up_axis:
        return capture
    return {**capture, "up_axis": up_axis}


def translate_capture(capture, up_axis, size_table=None, motion=None, timer=None):
    """The translator's result for a capture turned to the dialog's up axis. Raises what the translator raises.

    `motion` is what the size probe found about sketch values (`sketch_values.motion`), or `sketch_values.motion.OPTIMISTIC` for a
    first look that fixes nothing for sketches. A size that some value cannot follow stays free with a warning
    (`TranslateResult.loose`); the ranges are the table's. `timer` gets the time of the walk after a stop
    (`translator.translate`)."""
    return translate(_with_up_axis(capture, up_axis), size_table=size_table, motion=motion, timer=timer)


def refusal_hint(result):
    """What to change in Fusion so the step that stops the copy (`result.refusal`) copies, or "" when the cause has no
    hint."""
    return gap_hint(result.refusal_cause) or ""


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


def _cut_entries(size_table, cuts, free, shared=()):
    """`[{ name, reason, words, why, min, max, shared }]` of the translators' range cuts (`TranslateResult.cuts`) for the sizes in
    `free`, one per size by recipe name. A size in `shared` is in several parts, and every one of them has the range."""
    out, seen = [], set()
    for cut in cuts:
        recipe = size_table.recipe_name(cut["name"])
        if recipe not in free or recipe in seen:
            continue
        seen.add(recipe)
        common = recipe in shared
        reason = cut_reason(cut["name"], cut["words"], cut["why"], True) if common else cut["reason"]
        out.append({**size_table.fixed_entry(cut["name"], reason), "words": cut["words"], "why": cut["why"],
                    "min": cut["min"], "max": cut["max"], "shared": common})
    return out[:MAX_FIXED]


def _cut_listed(cuts):
    """The manifest `cuts` entries: the app shows each cut size with its reason as a quiet note, apart from `loose`."""
    return [{"name": cut["name"], "reason": cut["reason"]} for cut in cuts]


def _not_followed_note(names):
    text = "Could not follow these, so not sizes: %s." % ", ".join(names)
    return clip(text, MAX_NOTE)


def link_outcomes(size_table, sizes):
    """What happened to each geometry link of the export (`size_table.links`): the link with `outcome` ("size",
    "loose", "fixed", "dropped", "formula" for a parameter worked out by a formula, which cannot be ticked, or
    "not ticked") and the reason when there is one. `sizes` is the report's `sizes`
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
        elif _is_formula(size_table, name):
            found = {"outcome": "formula", "reason": _formula_reason(size_table, name)}
        else:
            found = {"outcome": "not ticked" if name not in size_table.ticked else "dropped"}
        out.append({**link, **found})
    return out


def _is_formula(size_table, name):
    entry = size_table.entry(name)
    return entry is not None and (entry.state == DERIVED or (entry.state == CONSTANT and bool(entry.formula)))


def _formula_reason(size_table, name):
    """Why a parameter worked out by a formula has no tick: it follows the parameters it reads."""
    reads = list(size_table.entry(name).reads)
    if not reads:
        return "%s is a formula of parameters that are not sizes, so it keeps its value." % name
    return clip("%s is a formula: it follows %s." % (name, ", ".join(reads)), MAX_PART_NOTE)


def _uses(capture):
    """How many times Fusion uses the component of the picked body (1 for a root body)."""
    placement = ((capture or {}).get("target") or {}).get("placement")
    uses = placement.get("uses") if isinstance(placement, dict) else 1
    return uses if isinstance(uses, int) and not isinstance(uses, bool) else 1


def plan_single_export(capture_or_error, step_file, title, writer, up_axis,
                       size_table=None, listing=None, motion=None, probe=None, marker=None, loose=None,
                       translated=None, health=None, also=None, derived=None, timing=None):
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
    derived: the `derived` block (`probe.derived.shadow`) for `report.json`: what reading the sketch graphs gives, kept
      beside the measured result and used for nothing else.
    timing: the export's `timing.export_timing.ExportTiming`, for the `timing` block of `report.json`. Its time since
      this call began counts as the package phase.
    files maps entry paths to a file path or bytes, as write_package expects. The manifest `checks` list is empty.
    Raises ValueError when the manifest breaks the package rules.
    """
    started = timing_stamp(timing)
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

    recipe_data = gaps_data = None
    if result is not None and result.recipe is not None:
        recipe_data, gaps_data, refusal = _recipe_and_gaps(result)
    elif result is not None:
        refusal = result.refusal

    free = free_sizes(result.recipe) if recipe_data is not None else []
    all_fixed, all_loose, all_cut, dropped = [], [], [], []
    if recipe_data is not None and size_table is not None:
        all_fixed = _merge_fixed(size_table, size_table.fixed, result.fixed)
        all_loose = _merge_fixed(size_table, loose, result.loose,
                                 skip={f["name"] for f in all_fixed}, only=set(free))
        all_cut = _cut_entries(size_table, result.cuts, set(free))
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
    if result is not None and result.after_stop is not None:
        report["after_stop"] = result.after_stop
    if error is not None:
        report["error"] = ("%s: %s" % (type(error).__name__, error))[:500]
    if marker is not None:
        report["marker"] = dict(marker)
    if capture is not None:
        report["capture"] = capture
    if probe is not None:
        report["probe"] = probe
    if derived is not None:
        report["derived"] = derived
    if health is not None:
        report["health"] = health
    if listing is not None:
        report["parameters"] = listing.report()
    if recipe_data is not None:
        report["sizes"] = {"free": free, "fixed": all_fixed, "loose": all_loose, "dropped": dropped}
        if all_cut:
            report["sizes"]["cut"] = all_cut
    if gaps_data is not None:
        report["gaps"] = list(result.gaps)
        if capture.get("reach") is not None:
            report["reach"] = capture["reach"]
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
        gapped = gaps_data is not None
        not_followed = [d["name"] for d in dropped if d["used"]]
        unused = [d["name"] for d in dropped if not d["used"] and not d.get("tried")]
        unchanged = [d["name"] for d in dropped if not d["used"] and d.get("tried")]
        notes = _most_useful([
            (0, first),
            (1, left_out_note([gap["name"] for gap in result.gaps]) if gapped else ""),
            (4, ORIGINAL_KEPT_NOTE if gapped else ""),
            (3, measuring_note(health)),
            (5, sizes_note(len(free)) if free else ""),
            (2, loose_note([f["name"] for f in all_loose]) if all_loose else ""),
            (2, cut_note([f["name"] for f in all_cut]) if all_cut else ""),
            (2, fixed_note([f["name"] for f in all_fixed]) if all_fixed else ""),
            (6, _not_followed_note(not_followed) if not_followed else ""),
            (7, unchanged_note(unchanged) if unchanged else ""),
            (8, dropped_note(unused) if unused else ""),
        ])
        manifest = build_recipe_manifest(
            title, writer, up_axis=up_axis, notes=notes, fixed=all_fixed, parameters=listed,
            loose=all_loose, cuts=_cut_listed(all_cut), gaps=GAPS_ENTRY if gaps_data is not None else None)
        files["recipe.json"] = recipe_data
        if gaps_data is not None:
            files[GAPS_ENTRY] = gaps_data
    else:
        also = also_failing_note(result.after_stop) if result is not None and note is None else ""
        notes = [note or step_only_note(refusal)] + ([also] if also else [])
        manifest = build_step_only_manifest(title, writer, up_axis=up_axis, notes=notes, parameters=listed)
    attach_timing(report, timing, started)
    files["report.json"] = _report_bytes(report)

    problems = validate_manifest(manifest)
    if problems:
        raise ValueError(" ".join(problems))
    return manifest, files, report


@dataclass
class PartInput:
    """One picked body of a several-body export, as `plan_parts_export` takes it.

    name: the part's name in the file. step_file: the STEP file on disk. capture: the reader's capture dict, or the
    exception it raised. translated: the translator's result for the same inputs (None translates here). motion: what
    the size probe found for this part's sketches. probe: that probe's record for `report.json`. derived: the part's
    `derived` block for `report.json`.
    """

    name: str
    step_file: str
    capture: Any
    translated: Optional[Any] = None
    motion: Optional[Any] = None
    probe: Optional[dict] = None
    derived: Optional[dict] = None


class _Part:
    """What one part of `plan_parts_export` came to: its recipe bytes, or the reason it is a fixed shape."""

    def __init__(self, given, up_axis, size_table):
        self.given = given
        self.result = self.refusal = self.note = self.error = self.recipe_data = self.gaps_data = None
        self.capture = given.capture if isinstance(given.capture, dict) else None
        if self.capture is None:
            self.error, self.note = given.capture, reader_failure_note()
        else:
            self.capture = _with_up_axis(self.capture, up_axis)
            try:
                self.result = given.translated or translate(self.capture, size_table=size_table, motion=given.motion)
            except CaptureError as exc:
                self.error, self.note = exc, reader_failure_note()
            except Exception as exc:
                self.error, self.note = exc, translate_failure_note()
        if self.result is not None and self.result.recipe is not None:
            self.recipe_data, self.gaps_data, self.refusal = _recipe_and_gaps(self.result)
        elif self.result is not None:
            self.refusal = self.result.refusal
        self.free = free_sizes(self.result.recipe) if self.recipe_data is not None else []

    @property
    def is_recipe(self):
        return self.recipe_data is not None

    @property
    def gaps(self):
        """The gap records of this part's recipe, or [] when it leaves nothing out."""
        return list(self.result.gaps) if self.gaps_data is not None else []

    def fixed_note(self):
        return self.note or step_only_note(self.refusal)


def _shared_dropped(size_table, parts, fixed_names, free):
    """The dropped entries of all parts, one per size: a size some part writes as a size, or that is fixed, is not
    dropped. A size no part uses is listed once, and `used` is True when any part reads it."""
    out = {}
    for part in parts:
        for d in part.result.dropped:
            if size_table.recipe_name(d["name"]) in fixed_names or size_table.recipe_name(d["name"]) in free:
                continue
            found = out.setdefault(d["name"], dict(d))
            if d["used"] and not found["used"]:
                out[d["name"]] = dict(d)
    return list(out.values())


def _tagged_loose(recipes):
    """The translators' loose sizes of all parts: one entry per size and reason, led by the parts that gave it. The
    size table is shared, so a doubt about a size usually comes from every part."""
    found = {}
    for part in recipes:
        for entry in part.result.loose:
            found.setdefault((entry["name"], entry["reason"]), []).append(part.given.name)
    return [{"name": name, "reason": tagged(names, reason)} for (name, reason), names in found.items()]


def _parts_notes(parts, free, loose, fixed, health, cut=()):
    """The package notes of a several-body export, at most `MAX_NOTES` (`_most_useful`)."""
    recipes = sum(1 for p in parts if p.is_recipe)
    first = "%d %s, %d %s." % (len(parts), "part" if len(parts) == 1 else "parts", len(free),
                               "size" if len(free) == 1 else "sizes")
    left_out = [(p.given.name, len(p.gaps)) for p in parts if p.gaps]
    shapes = [p.given.name for p in parts if not p.is_recipe] if recipes < len(parts) else []
    return _most_useful([
        (0, first),
        (1, left_out_parts_note(left_out) if left_out else ""),
        (5, ORIGINAL_KEPT_PARTS_NOTE if left_out else ""),
        (4, clip("Added as fixed shapes: %s." % ", ".join(shapes), MAX_NOTE) if shapes else ""),
        (3, measuring_note(health)),
        (2, loose_note([f["name"] for f in loose]) if loose else ""),
        (2, cut_note([f["name"] for f in cut]) if cut else ""),
        (2, fixed_note([f["name"] for f in fixed]) if fixed else ""),
    ])


def _part_record(part, loose, cut=()):
    """The part's entry in `report.json`."""
    result = part.result
    record = {
        "name": part.given.name,
        "outcome": "recipe" if part.is_recipe else "stepOnly",
        "items": list(result.items) if result is not None else [],
        "notes": list(result.notes) if result is not None else [],
    }
    if part.refusal is not None:
        record["refusal"] = part.refusal
    if result is not None and result.after_stop is not None:
        record["after_stop"] = result.after_stop
    if part.error is not None:
        record["error"] = ("%s: %s" % (type(part.error).__name__, part.error))[:500]
    if part.capture is not None:
        record["capture"] = part.capture
    if part.given.probe is not None:
        record["probe"] = part.given.probe
    if part.given.derived is not None:
        record["derived"] = part.given.derived
    if part.is_recipe:
        record["sizes"] = {"free": part.free, "loose": [e["name"] for e in loose]}
        if cut:
            record["sizes"]["cut"] = [e["name"] for e in cut]
    if part.gaps:
        record["gaps"] = part.gaps
        if part.capture.get("reach") is not None:
            record["reach"] = part.capture["reach"]
    return record


def plan_parts_export(inputs, title, writer, up_axis, size_table=None, listing=None, marker=None, loose=None,
                      health=None, also=None, timing=None):
    """Return (manifest, files, report) for several bodies of one design in one file (package kind `parts`).

    inputs: a `PartInput` per picked body, in order. Each part is translated like `plan_single_export` does; one that
    cannot be copied (or whose steps could not be read) is a fixed shape in the file with its own note, and the
    others keep their recipes. All parts were translated with the same `size_table`, so a size is one size for every
    part that reads it.
    A size that is fixed in one part is fixed in all (the caller translates with it fixed; `size_table.fixed` and
    each result's `fixed` are joined here). A size that is loose in one part (a translator doubt, or `loose` from the
    size probe) is listed as loose for every part whose recipe holds it; each reason starts with the part it was found
    in. A size whose range was cut (`TranslateResult.cuts`) is cut alike in every part that reads it, and its reason
    says so; the manifest lists it as loose with that reason. A ticked size that no part writes as a size is listed
    once in `report.json` under "dropped".
    loose, health, listing, marker, also, timing: as in `plan_single_export`.
    files holds `parts/NN/part.step`, `parts/NN/recipe.json` and one `report.json` with a record per part.
    Raises ValueError when the manifest breaks the package rules.
    """
    started = timing_stamp(timing)
    parts = [_Part(given, up_axis, size_table) for given in inputs]
    recipes = [p for p in parts if p.is_recipe]
    free = list(dict.fromkeys(name for p in recipes for name in p.free))
    all_fixed, all_loose, all_cut, dropped = [], [], [], []
    if recipes and size_table is not None:
        all_fixed = _merge_fixed(size_table, size_table.fixed, *[p.result.fixed for p in recipes])
        fixed_names = {f["name"] for f in all_fixed}
        found = list(loose or []) + _tagged_loose(recipes)
        all_loose = _merge_fixed(size_table, found, skip=fixed_names, only=set(free))
        dropped = _shared_dropped(size_table, recipes, fixed_names, set(free))
        users = [name for part in recipes for name in part.free]
        all_cut = _cut_entries(size_table, [c for part in recipes for c in part.result.cuts], set(free),
                               shared={name for name in free if users.count(name) > 1})
    sizes = {"free": free, "fixed": all_fixed, "loose": all_loose, "dropped": dropped}
    if all_cut:
        sizes["cut"] = all_cut
    report = {"writer": writer, "outcome": "parts", "parts": []}
    if marker is not None:
        report["marker"] = dict(marker)
    if health is not None:
        report["health"] = health
    if listing is not None:
        report["parameters"] = listing.report()
    if recipes:
        report["sizes"] = sizes
        if size_table is not None and size_table.links:
            report["links"] = link_outcomes(size_table, sizes)
    if also:
        report["also_changes"] = list(also)

    files, entries = {}, []
    for number, part in enumerate(parts, start=1):
        mine = [e for e in all_loose if e["name"] in part.free]
        cut = [e for e in all_cut if e["name"] in part.free]
        report["parts"].append(_part_record(part, mine, cut))
        entry = {"name": part.given.name, "step": part_step_path(number)}
        files[entry["step"]] = part.given.step_file
        if part.is_recipe:
            entry["recipe"] = part_recipe_path(number)
            files[entry["recipe"]] = part.recipe_data
            entry["loose"] = mine
            entry["cuts"] = _cut_listed(cut)
            sentences = []
            if part.gaps:
                entry["gaps"] = part_gaps_path(number)
                files[entry["gaps"]] = part.gaps_data
                sentences += [part_left_out_note(len(part.gaps)), ORIGINAL_KEPT_NOTE]
            if _uses(part.capture) > 1:
                sentences.append(used_several_times_note(_uses(part.capture)))
            if sentences:
                entry["note"] = clip(" ".join(sentences), MAX_PART_NOTE)
        else:
            entry["note"] = clip(part.fixed_note(), MAX_PART_NOTE)
        entries.append(entry)
    manifest = build_parts_manifest(
        title, writer, entries, up_axis=up_axis, notes=_parts_notes(parts, free, all_loose, all_fixed, health, all_cut),
        fixed=all_fixed, parameters=listing.entries if listing is not None else None)
    attach_timing(report, timing, started, parts=True)
    files["report.json"] = _parts_report_bytes(report)

    problems = validate_manifest(manifest)
    if problems:
        raise ValueError(" ".join(problems))
    return manifest, files, report


def _parts_report_bytes(report):
    """`report.json` of a several-body export; the captures are left out when the report cannot be written with them."""
    try:
        return _json_bytes(report, indent=2, default=str)
    except (TypeError, ValueError):
        trimmed = dict(report, parts=[{k: v for k, v in part.items() if k != "capture"} for part in report["parts"]])
        return _json_bytes(trimmed, indent=2, default=str)
