"""Write one body of the root component as a STEP file."""
import adsk.core

ROUTE_TEMP_COMPONENT = "temp_component"
ROUTE_ASK_DESIGNER = "ask_designer"

# What to do when the root holds more than the picked body. Switch after hand test 3 (docs/hand-tests.md).
MULTI_BODY_ROUTE = ROUTE_TEMP_COMPONENT


class StepExportError(Exception):
    """The STEP file could not be written. The message is a plain sentence."""


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
    """Find the body again by its token (references can go stale after a recompute); else use the fallback."""
    try:
        found = design.findEntityByToken(token)
        if found:
            return found[0]
    except Exception:
        pass
    return fallback


def _export_component(design, component, path):
    manager = design.exportManager
    options = manager.createSTEPExportOptions(path, component)
    if not manager.execute(options):
        raise StepExportError("Fusion could not write the STEP file.")


def _remove_temporary(design, occurrence, timeline_before):
    """Delete the temporary occurrence and any timeline items the copy added. Failures are ignored."""
    try:
        occurrence.deleteMe()
    except Exception:
        pass
    try:
        timeline = design.timeline
        for i in reversed(range(timeline_before, timeline.count)):
            try:
                timeline.item(i).entity.deleteMe()
            except Exception:
                pass
    except Exception:
        pass


def export_body_step(design, body, path, route=None):
    """Export body to path. The root export is used when the body is the only solid body in the design."""
    route = route or MULTI_BODY_ROUTE
    root = design.rootComponent
    if count_solid_bodies(root) == 1:
        _export_component(design, root, path)
        return
    if route == ROUTE_ASK_DESIGNER:
        raise StepExportError(
            "The design holds more than one solid body. Hide or move the other bodies, then try again.")
    try:
        timeline_before = design.timeline.count
    except Exception:
        timeline_before = 0
    occurrence = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    try:
        body.copyToComponent(occurrence)
        _export_component(design, occurrence.component, path)
    finally:
        _remove_temporary(design, occurrence, timeline_before)
