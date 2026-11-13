"""Put user parameters back to their saved expressions."""
from ..params.expressions import is_plain_number
from .apply import set_all


def restore_order(saved):
    """Names with plain number expressions first, then formulas, each group in saved order.

    Plain numbers go first so formulas that read them are set against restored inputs.
    """
    plain = [n for n, e in saved.items() if is_plain_number(e)]
    formulas = [n for n in saved if n not in plain]
    return plain + formulas


def restore_parameters(store, saved):
    """Set back every parameter whose expression changed, with one rebuild. Never raises.

    store needs current_expressions(), set_expression(name, text) and recompute(); set_expressions is used when it
    has one (`apply.set_all`): all of them go back in one change and Fusion rebuilds once, with no full recompute.
    The expressions are then read back, as text, and those that did not take go back one at a time as below.
    Else they are set one at a time and the design is recomputed; a parameter that refuses is then retried once after
    the others. Returns the names that could not be restored.
    """
    pending = _differing(store, saved, restore_order(saved))
    batched = bool(pending) and set_all(store, {n: saved[n] for n in pending})
    if batched:
        pending = _differing(store, saved, pending)
        if not pending:
            return []
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
    if batched:
        pending = list(dict.fromkeys(pending + _differing(store, saved, saved)))
    return pending


def _differing(store, saved, names):
    """The names in `names` whose expression now is not their saved text (all of them when it cannot be read)."""
    try:
        current = store.current_expressions()
    except Exception:
        current = {}
    return [n for n in names if current.get(n) != saved[n]]
