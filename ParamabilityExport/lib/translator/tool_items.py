"""Which timeline items build a tool body that lives in another component. Pure: capture dicts only.

A Combine in the exported body's component can take a tool body made in another component. The reader records such a
tool with its component (`foreign`, `component`) and reads the items that made it a second time, in the tool's own
frame (`helper_of`). The same rules pick those items for the reader and for the Combine handler.
"""
from . import step_kinds
from .capture import same_body

MAX_TOOLS = 8
MAX_ITEMS = 40
TOO_MANY = "the export reads at most %d steps of tool bodies from other components" % MAX_ITEMS


def component_token(tool):
    return ((tool or {}).get("component") or {}).get("token") or ""


def component_name(tool):
    return ((tool or {}).get("component") or {}).get("name") or "another component"


def is_foreign_tool(tool):
    """A tool body of another component that names its component, so the steps that made it can be found."""
    return isinstance(tool, dict) and tool.get("foreign") is True and bool(component_token(tool))


def foreign_tools(items):
    """`(combine item, tool record)` for each tool body of another component that a Combine of the exported body's
    component lists, in timeline order."""
    out = []
    for item in items:
        data = item.get("data")
        if item.get("suppressed") or item.get("in_target_component") is False or not isinstance(data, dict):
            continue
        out.extend((item, tool) for tool in data.get("tools") or [] if is_foreign_tool(tool))
    return out


def chain(items, tool, before):
    """The items before timeline index `before` that made or changed the foreign tool body `tool`: not suppressed,
    modeling steps of the tool's component whose bodies include the tool. Sketches and construction geometry are
    left out."""
    owner = component_token(tool)
    found = []
    for item in items:
        if item["index"] >= before or item.get("suppressed") or step_kinds.skipped(item.get("type")):
            continue
        if owner and item.get("component") and item["component"] != owner:
            continue
        if any(same_body(b, tool) for b in item.get("bodies_after") or []):
            found.append(item)
    return found


def plan(items, cap=MAX_ITEMS):
    """`(wanted, left)`: the items to read for the foreign tools of `items`, each with the tool it serves, in timeline
    order and without repeats, and the items past the cap of `cap` steps."""
    wanted, left, seen = [], [], set()
    for combine, tool in foreign_tools(items):
        for item in chain(items, tool, combine["index"]):
            if item["index"] in seen:
                continue
            seen.add(item["index"])
            (wanted if len(wanted) < cap else left).append((item, tool))
    wanted.sort(key=lambda pair: pair[0]["index"])
    return wanted, left
