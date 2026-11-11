"""Walking the steps of a recipe at every depth. A tool step holds a list of steps of its own."""


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
