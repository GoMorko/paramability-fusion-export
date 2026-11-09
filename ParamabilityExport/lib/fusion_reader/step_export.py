"""Write one body of the design as a STEP file."""
import adsk.core

from ..export_plan.errors import StepExportError
from ..export_plan.marker import put_back, read_marker
from ..export_plan.temp_copy import remove_temporary_copy, timeline_state
from ..package.units import cm_to_mm

COPY_TOLERANCE_MM = 1e-3

ROUTE_TEMP_COMPONENT = "temp_component"
ROUTE_ASK_DESIGNER = "ask_designer"

# What to do when the root holds more than the picked body. Section 3 of docs/hand-tests.md says when to switch.
MULTI_BODY_ROUTE = ROUTE_TEMP_COMPONENT


def _count(collection, only_solid=True):
    n = 0
    for i in range(collection.count):
        if not only_solid or collection.item(i).isSolid:
            n += 1
    return n


def count_solid_bodies(root):
    """Solid bodies a root export would write: the root's own and those in every occurrence."""
    total = _count(root.bRepBodies)
    for i in range(root.allOccurrences.count):
        total += _count(root.allOccurrences.item(i).bRepBodies)
    return total


def resolve_body(design, token, fallback):
    """Find the body again by its token (references can go stale after a recompute); else use the fallback.

    A picked body inside a component is an occurrence proxy that carries the placement. When the lookup gives the
    native body instead, it is put back into the picked occurrence, since a native body would export at the
    component's own origin.
    """
    try:
        found = design.findEntityByToken(token)
        if found:
            body = found[0]
            context = getattr(fallback, "assemblyContext", None)
            if context is None or getattr(body, "assemblyContext", None) is not None:
                return body
            return body.createForAssemblyContext(context)
    except Exception:
        pass
    return fallback


def _require_copy_in_place(copy, original):
    """The copy in the temporary component must sit where the picked body sits (boxes equal within 1e-3 mm)."""
    if copy is None:
        return
    try:
        a, b = copy.boundingBox, original.boundingBox
        corners = ((a.minPoint, b.minPoint), (a.maxPoint, b.maxPoint))
        off = max(abs(getattr(p, axis) - getattr(q, axis)) for p, q in corners for axis in "xyz")
    except Exception:
        raise StepExportError("The copy of the part could not be checked against its place in the assembly.")
    if cm_to_mm(off) > COPY_TOLERANCE_MM:
        raise StepExportError("The copy of the part did not land in its place in the assembly.")


def _export_component(design, component, path):
    manager = design.exportManager
    options = manager.createSTEPExportOptions(path, component)
    if not manager.execute(options):
        raise StepExportError("Fusion could not write the STEP file.")


def _require_copy_made(component):
    """The temporary component must hold the copied body before it is written."""
    try:
        made = component.bRepBodies.count > 0
    except Exception:
        made = False
    if not made:
        raise StepExportError("The copy of the part could not be made.")


def export_body_step(design, body, path, route=None):
    """Export body to path, as the design is at the timeline marker.

    The root export is used when the body is the only solid body in the design. Otherwise the body is copied into a
    temporary component, written, and the copy is deleted. Fusion places the copy's timeline items at the marker;
    afterwards the marker goes back to where it was."""
    route = route or MULTI_BODY_ROUTE
    root = design.rootComponent
    if count_solid_bodies(root) == 1:
        _export_component(design, root, path)
        return
    if route == ROUTE_ASK_DESIGNER:
        raise StepExportError(
            "The design holds more than one solid body. Hide or move the other bodies, then try again.")
    timeline = design.timeline
    start = read_marker(timeline)
    before = timeline_state(timeline)
    occurrence = None
    try:
        occurrence = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        # For a body inside a component, body is the occurrence proxy, so the copy keeps its place in the assembly.
        _require_copy_in_place(body.copyToComponent(occurrence), body)
        _require_copy_made(occurrence.component)
        _export_component(design, occurrence.component, path)
    finally:
        remove_temporary_copy(timeline, occurrence, before)
        back = start is None or put_back(timeline, start["position"])
    if not back:
        raise StepExportError("The timeline marker could not be moved back after the copy of the part.")
