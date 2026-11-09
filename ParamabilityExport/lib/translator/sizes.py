"""The recipe `sizes` and the sizes that cannot follow, around the size table.

The size table lists every size the person ticked. The recipe keeps only the sizes that a written formula reads, and
the sizes those formulas read in turn. A size whose value moves a sketch is fixed up front, since sketches are copied as
numbers.
"""
from ..params.expressions import tokenize_formula

# model parameter created_by kind -> what it moves, for the reason text
_STATIC_KINDS = {
    "sketchDimension": "a sketch",
    "constructionPlane": "a construction plane",
    "constructionAxis": "a construction axis",
    "joint": "a joint",
}


def _moves(param):
    """What a model parameter moves (for the reason text), or None. Fusion may name a sketch dimension's creator as
    the sketch itself; its role ("Linear Dimension-2") still tells."""
    kind = (param.get("created_by") or {}).get("kind")
    if kind == "other" and "Dimension" in (param.get("role") or ""):
        kind = "sketchDimension"
    return _STATIC_KINDS.get(kind)


def sketch_fixes(table):
    """{ Fusion name: reason } for each ticked size that a sketch dimension, construction plane or axis, or joint reads.

    Sketch points, placements and construction geometry are written as numbers, so a size that moves them cannot be
    a size. The check at other values (in the add-in and in the app) finds the ones this does not see.
    """
    fixed = {}
    for param in table.model_params.values():
        what = _moves(param)
        if what is None:
            continue
        reads = table.depends(param["name"])
        for name in table.ticked:
            if name in reads and name not in fixed:
                fixed[name] = ("%s stays fixed for now: it changes %s. Sketches that follow sizes come in a later "
                               "version." % (name, what))[:200]
    return fixed


def _identifiers(node, found):
    if isinstance(node, dict):
        expr = node.get("expr")
        if isinstance(expr, str):
            found.update(tok[1] for tok in tokenize_formula(expr) if tok[0] == "id")
        for value in node.values():
            _identifiers(value, found)
    elif isinstance(node, list):
        for value in node:
            _identifiers(value, found)


def used_sizes(features, sizes):
    """The entries of `sizes` (recipe name to size dict) that the written steps read, directly or through formulas."""
    wanted = set()
    _identifiers(features, wanted)
    used = {}
    pending = [name for name in sizes if name in wanted]
    while pending:
        name = pending.pop()
        if name in used:
            continue
        used[name] = sizes[name]
        reads = set()
        _identifiers({"expr": sizes[name].get("expr")}, reads)
        pending.extend(n for n in sizes if n in reads and n not in used)
    return {name: used[name] for name in sizes if name in used}
