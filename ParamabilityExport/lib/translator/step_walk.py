"""Walking the steps of a recipe at every depth. A tool step holds a list of steps of its own."""


def all_steps(steps):
    """Every step of `steps`, each one followed by the steps nested in it."""
    found = []
    for step in steps:
        found.append(step)
        found.extend(all_steps(step.get("features") or []))
    return found
