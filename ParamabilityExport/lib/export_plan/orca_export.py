"""The OrcaSlicer output of one body: the Design tab recipe, the plate mesh and the report, as a `.3mf`. Pure: no
Fusion imports.

The plate shows the body's mesh where the Design tab builds the recipe (`orca_translate.place`). When steps are
left out and the copy is placed by its own box, the mesh (the real Fusion body) keeps the same turn and the same
move across the bed, and is lowered or raised alone so that it rests on the bed too. When the steps cannot be read
or translated, the file still holds the mesh, with an empty recipe, and the report says why.

The report is written inside the `.3mf` and beside it (`<name>.report.json`), since Orca leaves the entry out when
the project is saved again from Orca.
"""
import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from ..geometry import mesh as meshes
from ..orca_recipe.recipe import Recipe, serialize
from ..orca_recipe.threemf import MeshObject, write_3mf
from ..orca_translate import translate as orca_translate
from ..orca_translate.place import BED_CENTRE, Placement, apply, moved_box
from ..timing.export_timing import attach as attach_timing, stamp as timing_stamp

ORCA = "orca"
PARAMABILITY = "paramability"
REPORT_ENTRY = "Metadata/paramability_report.json"
# How far (mm) the plate mesh may lie from the box of the part before the report says so.
MESH_TOLERANCE = 0.5
NOT_READ_NOTE = "The steps of the part could not be read, so the file holds only its shape."
NOT_TRANSLATED_NOTE = "The steps of the part could not be copied, so the file holds only its shape."
REPORT_SUFFIX = ".report.json"
OWN_BOX_NOTE = ("Steps are left out, so the Orca copy is not the same size as the Fusion part (up to %.1f mm). "
                "The copy is placed on the bed by its own shape, and the Fusion shape on the plate rests on the bed "
                "too.")


@dataclass
class OrcaPackage:
    """What `plan_orca_export` made: the recipe bytes, the plate meshes, the report and the translation (None when
    there is none)."""

    recipe_bytes: bytes
    objects: list
    report: dict
    result: Optional[Any] = None
    notes: list = field(default_factory=list)

    def report_bytes(self):
        try:
            return json.dumps(self.report, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        except (TypeError, ValueError):
            trimmed = {k: v for k, v in self.report.items() if k != "capture"}
            return json.dumps(trimmed, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def translate_for_orca(capture, up_axis, size_table=None, bed=BED_CENTRE):
    """The Orca translation of a capture turned to the dialog's up axis. Raises what the translator raises."""
    if capture.get("up_axis") != up_axis:
        capture = {**capture, "up_axis": up_axis}
    return orca_translate(capture, size_table, bed)


def _mesh_check(vertices, place, capture, lift=0.0):
    """`{mesh, part, off}` boxes on the plate and how far apart they are, or None when the capture has no box. The
    part's box is raised by `lift` as the mesh was."""
    box = ((capture or {}).get("target") or {}).get("box")
    if not box or not vertices:
        return None
    seen = meshes.bounds(vertices)
    part = moved_box(place.to_orca, box)
    part = {k: [part[k][0], part[k][1], part[k][2] + lift] for k in ("min", "max")}
    off = max(abs(seen[k][i] - part[k][i]) for k in ("min", "max") for i in range(3))
    return {"mesh": seen, "part": part, "off": round(off, 4)}


def _placement(result, place, capture, lift):
    """The `placement` block of the report: which box placed the copy, and how far the mesh was raised to rest on
    the bed. `note` is the sentence for the result window, or None."""
    own = getattr(result, "copy_box", None)
    block = {"by": "copy" if own is not None else "part", "mesh_lift": round(lift, 4)}
    box = ((capture or {}).get("target") or {}).get("box")
    if own is None:
        return block, None
    block["copy_box"] = moved_box(place.to_orca, own)
    if not box:
        return block, None
    off = max(abs(own[k][i] - box[k][i]) for k in ("min", "max") for i in range(3))
    block["off"] = round(off, 4)
    return block, OWN_BOX_NOTE % off


def plan_orca_export(capture_or_error, mesh, title, writer, up_axis, size_table=None, listing=None, health=None,
                     marker=None, translated=None, timing=None, bed=BED_CENTRE):
    """The `OrcaPackage` of one body.

    capture_or_error: the reader's capture dict, or the exception it raised. mesh: `(vertices, triangles)` of the body
    in root coordinates, mm. translated: the Orca translation already made for these inputs (`translate_for_orca`),
    or None to translate here. The rest as in `recipe_export.plan_single_export`.
    """
    started = timing_stamp(timing)
    capture = capture_or_error if isinstance(capture_or_error, dict) else None
    result, error, note = translated, None, None
    if capture is None:
        error, note = capture_or_error, NOT_READ_NOTE
    elif result is None:
        try:
            result = translate_for_orca(capture, up_axis, size_table, bed)
        except Exception as exc:
            error, note = exc, NOT_TRANSLATED_NOTE
    vertices, triangles = mesh
    if result is not None:
        place = result.place
        recipe = result.recipe
    else:
        envelope = {"up_axis": up_axis, "target": {}}
        root_box = meshes.bounds(vertices)
        place = Placement(envelope, bed, box=root_box)
        recipe = Recipe()
        recipe.modeling_origin = place.bed
    placed = [apply(place.root_to_orca, v) for v in vertices]
    lift = 0.0
    if getattr(result, "copy_box", None) is not None and placed:
        # The copy sits on the bed by its own box; the real Fusion body rests on the bed by its own lowest point.
        lift = -min(v[2] for v in placed)
        placed = [(v[0], v[1], v[2] + lift) for v in placed]
    objects = [MeshObject(title or "Part", placed, triangles)]

    notes = [note] if note else list(result.notes)
    report = {"writer": writer, "output": ORCA, "outcome": "orcaRecipe" if result is not None else "meshOnly",
              "title": title, "notes": notes}
    if result is not None:
        report["items"] = list(result.items)
        report["orca"] = result.summary()
        report["placement"], placed_note = _placement(result, place, capture, lift)
        if placed_note:
            notes.append(placed_note)
    if error is not None:
        report["error"] = ("%s: %s" % (type(error).__name__, error))[:500]
    check = _mesh_check(placed, place, capture, lift) if result is not None else None
    if check is not None:
        report["mesh_check"] = check
        if check["off"] > MESH_TOLERANCE:
            notes.append("The shape on the plate and the box of the part differ by %.1f mm." % check["off"])
    if marker is not None:
        report["marker"] = dict(marker)
    if capture is not None:
        report["capture"] = capture
    if health is not None:
        report["health"] = health
    if listing is not None:
        report["parameters"] = listing.report()
    attach_timing(report, timing, started)
    return OrcaPackage(serialize(recipe), objects, report, result, notes)


def report_path(path):
    """Where the report beside a `.3mf` goes: the same name with `.report.json` in place of `.3mf`."""
    stem, ext = os.path.splitext(path)
    return (stem if ext.lower() == ".3mf" else path) + REPORT_SUFFIX


def write_orca_package(path, package):
    """Write the `.3mf` of an `OrcaPackage` (the person keeps their own printer presets) with the report inside, and
    the same report beside it."""
    report = package.report_bytes()
    write_3mf(path, package.recipe_bytes, package.objects, extra={REPORT_ENTRY: report})
    with open(report_path(path), "wb") as f:
        f.write(report)
