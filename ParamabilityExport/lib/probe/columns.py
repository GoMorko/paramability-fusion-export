"""The parameter columns a written value may follow: each parameter's number at every probe state.

A column is a user parameter (a free size, or a formula over sizes) or a model parameter (a sketch dimension, a
construction plane distance, a feature length) whose Fusion expression translates into the size table's formulas. The
number the formula gives at a state is checked against the number Fusion read at that state, so a column that
disagrees is left out (and listed), never trusted.
"""
from ..params import defaults
from ..params.expressions.errors import ExpressionError
from ..params.expressions.evaluation import evaluate
from ..params.expressions.units import ANGLE, LENGTH, SCALAR, internal_factor
from ..params.size_table import DERIVED, FREE
from .fit import Column

CHECK_TOLERANCE = 1e-6
RANK_DERIVED, RANK_FREE, RANK_DIMENSION, RANK_PLANE, RANK_OTHER = 1, 2, 3, 4, 5
_DIM_NAMES = {LENGTH: "length", ANGLE: "angle", SCALAR: "scalar"}


class ModelColumn(Column):
    """A model parameter column with where it comes from, for ranking by sketch."""

    def __init__(self, name, values, sketch, plane):
        super().__init__(name, RANK_OTHER, values)
        self.sketch = sketch
        self.plane = plane

    def ranked(self, sketch, plane):
        """A copy with the rank it has for a value of `sketch` on the construction plane `plane` (a token)."""
        rank = RANK_OTHER
        if sketch and self.sketch == sketch:
            rank = RANK_DIMENSION
        elif plane and self.plane == plane:
            rank = RANK_PLANE
        out = ModelColumn(self.name, self.values, self.sketch, self.plane)
        out.rank = rank
        return out


def size_env(table, overrides):
    """`(env, derived)`: size values by recipe name (free sizes with `overrides`, then the named derived ones) and the
    value of every derived user parameter by Fusion name (None where its formula fails)."""
    env = {e.size_name: overrides.get(e.name, e.value) for e in table.entries if e.state == FREE}
    derived = {}
    pending = [e for e in table.entries if e.state == DERIVED]
    while pending:
        later = []
        for e in pending:
            try:
                derived[e.name] = evaluate(e.formula, env)
            except ExpressionError:
                later.append(e)
                continue
            if e.size_name:
                env[e.size_name] = derived[e.name]
        if len(later) == len(pending):
            derived.update({e.name: None for e in later})
            break
        pending = later
    return env, derived


def _check(values, reads, name, factor):
    """False when a state's read of the parameter disagrees with the formula; the count of states it was read in."""
    seen = 0
    for value, read in zip(values, reads):
        got = ((read or {}).get("params") or {}).get(name)
        if got is None:
            continue
        seen += 1
        if abs(got * factor - value) > CHECK_TOLERANCE:
            return False, seen
    return True, seen


def user_columns(table, overrides, envs, reads, dropped):
    """Rank 1 and 2 columns. `overrides`: per state the manifest values of the sizes that differ; `envs`: `size_env`
    per state; `reads`: the probe read per state (None when absent). A column that disagrees with Fusion goes into
    `dropped` as `{ name, reason }`."""
    out = []
    for e in table.entries:
        if e.state == FREE:
            out.append(Column(e.name, RANK_FREE, [o.get(e.name, e.value) for o in overrides], e.kind or "length"))
        elif e.state == DERIVED:
            values = [derived.get(e.name) for _, derived in envs]
            if None in values:
                dropped.append({"name": e.name, "reason": "its formula gives no number at some size settings"})
                continue
            dim = defaults.dim_of_unit(table.unit_of(e.name))
            ok, _ = _check(values, reads, e.name, internal_factor(dim) if dim else 1.0)
            if ok:
                out.append(Column(e.name, RANK_DERIVED, values))
            else:
                dropped.append({"name": e.name, "reason": "its formula differs from what Fusion read"})
    return out


def model_columns(table, envs, reads, dropped):
    """Rank 5 columns of the model parameters whose expression follows the sizes; `ranked` sets the rank per value."""
    out = []
    for m in table.model_params.values():
        dim = defaults.dim_of_unit(m.get("unit"))
        if dim not in _DIM_NAMES:
            continue
        tr = table.translate(m["expression"], expected=defaults.size_value(m), dim=_DIM_NAMES[dim], unit=m.get("unit"))
        if not tr.ok or not tr.reads:
            continue
        try:
            values = [evaluate(tr.formula, env) for env, _ in envs]
        except ExpressionError:
            dropped.append({"name": m["name"], "reason": "its formula gives no number at some size settings"})
            continue
        ok, seen = _check(values, reads, m["name"], internal_factor(dim))
        if not ok:
            dropped.append({"name": m["name"], "reason": "its formula differs from what Fusion read"})
        elif seen:
            made = m.get("created_by") or {}
            plane = made.get("token") if made.get("kind") == "constructionPlane" else ""
            sketch = (made.get("sketch") or "") if made.get("kind") == "sketchDimension" else ""
            out.append(ModelColumn(m["name"], values, sketch, plane or ""))
    return out
