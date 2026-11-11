"""What a Combine that keeps the shared part of several tools keeps.

Fusion's help says an intersect "keeps overlapping volumes". With several tools that can mean the part and every tool,
or the part and any tool. The two give different shapes, so each export measures which one Fusion made: with the
marker before the Combine, temporary copies of the part and the tools (`TemporaryBRepManager`, never added to the
design) give the volume of each candidate, and with the marker after it the result is matched to one of them.
"""
from ..translator.combine_volume import intersect_model as model  # noqa: F401  (the reader's name for it)
from . import read_geometry as geo


def _brep_tools():
    """`(TemporaryBRepManager, BooleanTypes)` of Fusion; raises outside Fusion."""
    import adsk.fusion
    return adsk.fusion.TemporaryBRepManager.get(), adsk.fusion.BooleanTypes


def _shared(manager, types, target, tools):
    """Volume in mm3 of `target` intersected with each of `tools` in turn. An intersect that reports failure counts as
    empty: Fusion may answer that way when nothing is shared."""
    body = manager.copy(target)
    for tool in tools:
        if not manager.booleanOperation(body, manager.copy(tool), types.IntersectionBooleanType):
            return 0.0
    return geo.volume_mm3(body)


def _union(manager, types, tools):
    """A temporary body that joins `tools`; raises when Fusion reports a failed boolean."""
    body = manager.copy(tools[0])
    for tool in tools[1:]:
        if not manager.booleanOperation(body, manager.copy(tool), types.UnionBooleanType):
            raise ValueError("A temporary boolean failed.")
    return body


def volumes(feature, tool_refs):
    """`{ every, any }` in mm3 for an intersect of several tools, or None when they cannot be measured.

    every: the part intersected with each tool in turn. any: the part intersected with the union of the tools. Each is
    measured on its own, and one that cannot be measured is null. A tool of another component is not measured: its
    body is in other coordinates than the part's."""
    if any(ref.get("foreign") for ref in tool_refs):
        return None

    def measure():
        manager, types = _brep_tools()
        tools = geo.collection_items(feature.toolBodies)
        if len(tools) < 2:
            return None
        target = feature.targetBody
        return {"every": geo.safe(lambda: _shared(manager, types, target, tools), None),
                "any": geo.safe(lambda: _shared(manager, types, target, [_union(manager, types, tools)]), None)}

    return geo.safe(measure, None)
