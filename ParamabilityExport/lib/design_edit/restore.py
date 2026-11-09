"""Put user parameters back to their saved expressions."""
from ..params.expressions import is_plain_number


def restore_order(saved):
    """Names with plain number expressions first, then formulas, each group in saved order.

    Plain numbers go first so formulas that read them are set against restored inputs.
    """
    plain = [n for n, e in saved.items() if is_plain_number(e)]
    formulas = [n for n in saved if n not in plain]
    return plain + formulas


def restore_parameters(store, saved):
    """Set back every parameter whose expression changed, then recompute. Never raises.

    store needs current_expressions(), set_expression(name, text) and recompute().
    A parameter that refuses is retried once after the others. Returns the names that could not be restored.
    """
    try:
        current = store.current_expressions()
    except Exception:
        current = {}
    pending = [n for n in restore_order(saved) if current.get(n) != saved[n]]
    touched = bool(pending)
    for _ in range(2):
        failed = []
        for name in pending:
            try:
                store.set_expression(name, saved[name])
            except Exception:
                failed.append(name)
        pending = failed
        if not pending:
            break
    if touched:
        try:
            store.recompute()
        except Exception:
            pass
    return pending
