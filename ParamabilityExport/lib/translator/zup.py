"""Y up designs to the recipe's Z up frame.

A recipe is always written Z up (the package manifest's `upAxis` applies to the STEP files only). For a Y up
design every position and direction the translator writes turns as (x, y, z) to (x, -z, y), a quarter turn about
the X axis, so later size edits rebuild upright. 2D sketch values and revolve axes live in a sketch plane and stay.
"""
import copy

# Step kind -> paths to positions and directions. "[]" walks a list; a path that is absent in a step is skipped.
PLACEMENT = ("origin", "normal", "xDir")
FIELDS = {
    "extrude": [("sketch", "on", f) for f in PLACEMENT] + [("within", "on", f) for f in PLACEMENT]
    + [("extent", "upTo", "near", "[]")],
    "revolve": [("sketch", "on", f) for f in PLACEMENT] + [("within", "on", f) for f in PLACEMENT],
    "hole": [("origin",), ("direction",)],
    "round": [("edges", "near", "[]"), ("edges", "parallelTo")],
    "bevel": [("edges", "near", "[]"), ("edges", "parallelTo"), ("sizeOn",)],
    "shell": [("openFaces", "near", "[]")],
    "pattern": [("linear", "dir"), ("linear2", "dir"), ("polar", "axisPoint"), ("polar", "axis")],
    "mirror": [("plane", "origin"), ("plane", "normal")],
}

# Step kinds with positions or directions that the translator never writes. The schema walk in the tests
# fails when a kind appears in neither table, so a new schema field cannot slip by.
NOT_WRITTEN = ("loft", "sweep", "thread", "coil", "skin", "draft", "bevelGear")


def turn_point(p):
    """(x, y, z) to (x, -z, y)."""
    return [p[0], 0.0 - p[2], p[1]]


def turn_back_point(p):
    """The inverse of turn_point: (x, y, z) to (x, z, -y)."""
    return [p[0], p[2], 0.0 - p[1]]


def _is_triple(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


def _apply(node, path, fn):
    if not path:
        return
    key, rest = path[0], path[1:]
    if key == "[]":
        if isinstance(node, list):
            for entry in node:
                _apply(entry, rest, fn)
        return
    if not isinstance(node, dict) or key not in node:
        return
    if not rest:
        if _is_triple(node[key]):
            node[key] = fn(node[key])
        elif isinstance(node[key], list):
            node[key] = [fn(p) if _is_triple(p) else p for p in node[key]]
        return
    _apply(node[key], rest, fn)


def _turn(recipe, fn):
    out = copy.deepcopy(recipe)
    for step in out.get("features", []):
        for path in FIELDS.get(step.get("kind"), ()):
            if path[-1] == "[]":
                _apply(step, path[:-1], fn)
            else:
                _apply(step, path, fn)
    return out


def turn_z_up(recipe):
    """Return a copy of the recipe with every position and direction turned from Y up to Z up."""
    return _turn(recipe, turn_point)


def turn_back(recipe):
    """The inverse of turn_z_up. Used by tests to check the round trip."""
    return _turn(recipe, turn_back_point)
