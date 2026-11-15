"""Walking the steps of a recipe at every depth. A tool step holds a list of steps of its own."""
from ..capture_model import step_kinds
from .result import Refusal


def all_steps(steps):
    """Every step of `steps`, each one followed by the steps nested in it."""
    found = []
    for step in steps:
        found.append(step)
        found.extend(all_steps(step.get("features") or []))
    return found


def nesting(steps):
    """How many levels of tool steps `steps` hold."""
    return max([1 + nesting(step["features"]) for step in steps if step.get("features")] + [0])


def moved_later(steps, step_id):
    """True when a `move` step comes after the step `step_id` in its list."""
    ids = [step.get("id") for step in steps]
    return step_id in ids and any(step.get("kind") == "move" for step in steps[ids.index(step_id) + 1:])


def outside_tool(steps):
    """The first step of `steps`, at any depth, of a kind the recipe keeps out of a tool body (a coil), else None."""
    return next((step for step in all_steps(steps) if not step_kinds.recipe_kind(step.get("kind")).in_tool), None)


def kind_tool_refusal(kind):
    """The Refusal for a step of `kind` that cannot be part of a tool body: its words and hint fit the kind."""
    found = step_kinds.recipe_kind(kind)
    return Refusal("A %s cannot be part of a tool body that has other steps." % (found.tool_words or kind),
                   cause=found.tool_cause)


def tool_refusal(steps):
    """A Refusal for the first step of `steps` that the recipe keeps out of a tool body, else None."""
    found = outside_tool(steps)
    return None if found is None else kind_tool_refusal(found.get("kind"))
