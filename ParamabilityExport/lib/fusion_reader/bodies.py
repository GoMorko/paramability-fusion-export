"""Which bodies the export offers. No adsk import; works on the objects it is given."""


def is_pickable_body(entity):
    """True for any solid body: in the root, a component or an occurrence (a picked one is an occurrence proxy)."""
    try:
        return bool(getattr(entity, "isSolid", False))
    except Exception:
        return False


def is_root_body(body, root):
    """True for a body that belongs to the root component itself, not to a child component or occurrence."""
    try:
        if getattr(body, "assemblyContext", None) is not None:
            return False
        return body.parentComponent.entityToken == root.entityToken
    except Exception:
        return False
