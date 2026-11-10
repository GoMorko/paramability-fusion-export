"""What a Combine that keeps the shared part of several tools keeps.

Fusion's help says an intersect "keeps overlapping volumes". With several tools that can mean the part and every tool,
or the part and any tool. The two give different shapes, so each export measures which one Fusion made: with the
marker before the Combine, temporary copies of the part and the tools (`TemporaryBRepManager`, never added to the
design) give the volume of each candidate, and with the marker after it the result is matched to one of them.
"""
from . import read_geometry as geo

# Volumes match when they differ by less than this (mm3) or by this share of the larger one.
VOLUME_TOLERANCE_MM3 = 1e-3
VOLUME_RELATIVE = 1e-6


def _brep_tools():
    """`(TemporaryBRepManager, BooleanTypes)` of Fusion; raises outside Fusion."""
    import adsk.fusion
    return adsk.fusion.TemporaryBRepManager.get(), adsk.fusion.BooleanTypes


def _combined(manager, kind, target, tools):
    """A temporary body: `target` combined with each of `tools` in turn by the boolean `kind`; raises when Fusion
    reports a failed boolean."""
    body = manager.copy(target)
    for tool in tools:
        if not manager.booleanOperation(body, manager.copy(tool), kind):
            raise ValueError("A temporary boolean failed.")
    return body


def volumes(feature, tool_refs):
    """`{ every, any }` in mm3 for an intersect of several tools, or None when they cannot be measured.

    every: the part intersected with each tool in turn. any: the part intersected with the union of the tools. A tool
    of another component is not measured: its body is in other coordinates than the part's."""
    if any(ref.get("foreign") for ref in tool_refs):
        return None

    def measure():
        manager, types = _brep_tools()
        tools = geo.collection_items(feature.toolBodies)
        if len(tools) < 2:
            return None
        target = feature.targetBody
        shared = _combined(manager, types.IntersectionBooleanType, target, tools)
        union = _combined(manager, types.UnionBooleanType, tools[0], tools[1:])
        some = _combined(manager, types.IntersectionBooleanType, target, [union])
        found = {"every": geo.volume_mm3(shared), "any": geo.volume_mm3(some)}
        return found if None not in found.values() else None

    return geo.safe(measure, None)


def _same(a, b):
    return abs(a - b) <= max(VOLUME_TOLERANCE_MM3, VOLUME_RELATIVE * max(abs(a), abs(b)))


def model(measured, volume_after):
    """"every", "any" or "unknown": which candidate the part's volume after the Combine matches. When both match
    (the candidates are equal) it is "every"."""
    if not measured or volume_after is None:
        return "unknown"
    if _same(measured["every"], volume_after):
        return "every"
    if _same(measured["any"], volume_after):
        return "any"
    return "unknown"
