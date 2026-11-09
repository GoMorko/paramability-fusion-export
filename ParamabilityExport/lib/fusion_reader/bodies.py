"""Which bodies the export offers. No adsk import; works on the objects it is given."""


def is_pickable_body(entity):
    """True for any solid body: in the root, a component or an occurrence (a picked one is an occurrence proxy)."""
    try:
        return bool(getattr(entity, "isSolid", False))
    except Exception:
        return False

