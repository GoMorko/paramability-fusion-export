"""Where a gap belongs in the final recipe.

A gap keeps the ids of the steps written before it. Later steps can move what was written into a tool step, so the
place is worked out once the recipe is final.
"""
from . import notes as wording


def _tree(features):
    """Step id to `(list owner id or None, list of steps)` for every step of the recipe."""
    out = {}

    def walk(steps, owner):
        for step in steps:
            out[step.get("id")] = (owner, steps)
            if step.get("features"):
                walk(step["features"], step.get("id"))

    walk(features, None)
    return out


def place_all(gaps, features):
    """Set each gap's place in the final recipe: the last step written before it that is still there, the list that
    holds that step and the step after it. Returns a reason when a gap has no place, else None."""
    tree = _tree(features)
    for gap in gaps:
        after = next((step_id for step_id in reversed(gap.written_before) if step_id in tree), None)
        if after is None:
            return wording.no_gap_place_reason()
        owner, steps = tree[after]
        ids = [step.get("id") for step in steps]
        position = ids.index(after)
        gap.place = (after, ids[position + 1] if position + 1 < len(ids) else None, owner)
    return None
