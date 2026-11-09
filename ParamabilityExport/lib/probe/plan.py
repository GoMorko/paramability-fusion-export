"""What to read from Fusion and which size settings to try. Pure: no Fusion imports.

`scan` finds the sketches whose numbers the probe can follow ("covered" ones): every capture record that names them
is a profile, a hole point set or a revolve axis line that the reader gave tokens for. `request` is what the reader
reads per state, `kept_sizes` the sizes worth probing, `probe_rows` the size settings to try.

Sizes are dicts as in `export_plan.size_offers.probe_sizes`: param (Fusion name), size (recipe name), unit, value,
min, max (manifest numbers).
"""
from ..package.manifest import MAX_NAME_CHARS
from ..package.units import display_from_manifest
from ..params import defaults
from ..params.size_table import DERIVED, FREE
from ..translator.loops import profile_loops
from ..translator.result import Refusal

MAX_PROBE_ROWS = 64
FOLLOWED_KINDS = ("sketchDimension", "constructionPlane")
_SAME = 1e-9
_CURVES = ("line", "arc", "circle", "ellipse")


class Scan:
    """`targets`: the covered records (dicts with `kind` "profile", "hole" or "axis", `item` and what the fit reads).
    `covered`: sketch token to name ("" when the record has none). `uncovered`: tokens of sketches that some record
    uses in a way the probe cannot follow. `named`: the name of every sketch a record names, covered or not, by token
    (a sketch no record gives a name for is missing)."""

    def __init__(self):
        self.targets = []
        self.covered = {}
        self.uncovered = set()
        self.named = {}

    def note_name(self, token, name):
        if token and isinstance(name, str) and name:
            self.named.setdefault(token, name)


def _profile_ok(profile):
    if profile.get("face") or "loops" not in profile or not profile.get("sketch_token"):
        return False
    curves = [c for loop in profile["loops"] for c in (loop.get("curves") or [])]
    if not curves or any(c.get("kind") not in _CURVES or not c.get("entity") for c in curves):
        return False
    return not isinstance(profile_loops(profile), Refusal)


def _stray_tokens(node, out):
    """Sketch tokens that a record carries; any such record other than the ones scanned leaves its sketch uncovered."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "sketch_token" and isinstance(value, str):
                out.uncovered.add(value)
                out.note_name(value, node.get("sketch"))
            else:
                _stray_tokens(value, out)
    elif isinstance(node, list):
        for value in node:
            _stray_tokens(value, out)


def scan(capture):
    """The `Scan` of a capture: its items in the target's component that carry a profile, a hole or a revolve axis."""
    out = Scan()
    for item in capture.get("items") or []:
        data = item.get("data") or {}
        if item.get("suppressed") or item.get("in_target_component") is False or "read_error" in data:
            continue
        kind, index = item.get("type"), item.get("index")
        if kind in ("ExtrudeFeature", "RevolveFeature"):
            _scan_profiles(out, index, data)
            if kind == "RevolveFeature":
                _scan_axis(out, index, data)
        elif kind == "HoleFeature":
            _scan_hole(out, index, data)
        else:
            _stray_tokens(data, out)
    for token in out.uncovered:
        out.covered.pop(token, None)
    out.targets = [t for t in out.targets if t["sketch_token"] in out.covered]
    return out


def _cover(out, token, name):
    out.note_name(token, name)
    out.covered.setdefault(token, name or "")
    if name and not out.covered[token]:
        out.covered[token] = name


def _scan_profiles(out, index, data):
    for number, profile in enumerate(data.get("profiles") or []):
        if not isinstance(profile, dict) or profile.get("foreign") or profile.get("face"):
            continue
        token = profile.get("sketch_token")
        if not _profile_ok(profile):
            if token:
                out.uncovered.add(token)
                out.note_name(token, profile.get("sketch"))
            continue
        _cover(out, token, profile.get("sketch"))
        out.targets.append({"kind": "profile", "item": index, "p": number, "profile": profile,
                            "sketch_token": token, "sketch": profile.get("sketch") or "",
                            "reference": profile.get("reference") or {}})


def _scan_axis(out, index, data):
    axis = data.get("axis")
    if not isinstance(axis, dict) or "entity" not in axis:
        return
    token = axis.get("sketch_token")
    if not token or "point" not in axis or "dir" not in axis:
        if token:
            out.uncovered.add(token)
            out.note_name(token, axis.get("sketch"))
        return
    _cover(out, token, axis.get("sketch"))
    out.targets.append({"kind": "axis", "item": index, "entity": axis["entity"], "sketch_token": token,
                        "sketch": axis.get("sketch") or "", "axis": axis})


def _scan_hole(out, index, data):
    token = data.get("sketch_token")
    positions, points = data.get("positions"), data.get("point_tokens")
    if not token:
        return
    if not positions or not isinstance(points, list) or len(points) != len(positions) or not all(points):
        out.uncovered.add(token)
        out.note_name(token, data.get("sketch"))
        return
    _cover(out, token, data.get("sketch"))
    out.targets.append({"kind": "hole", "item": index, "sketch_token": token, "sketch": data.get("sketch") or "",
                        "positions": positions, "point_tokens": points})


# ---- what to read per state ----------------------------------------------------------------------------------

def _numeric_model(table):
    return [m for m in table.model_params.values() if defaults.dim_of_unit(m.get("unit")) is not None]


def request(capture, table, covered=None):
    """What the reader reads at each state, or None when no sketch is covered.

    `covered` limits the sketches to these tokens (the ones whose first read matched the capture).
    `{ "sketches": [token], "points": [token], "lines": [token], "params": [Fusion name], "target": True }`
    """
    found = scan(capture)
    tokens = [t for t in found.covered if covered is None or t in covered]
    if not tokens:
        return None
    points, lines = [], []
    for target in found.targets:
        if target["sketch_token"] not in tokens:
            continue
        if target["kind"] == "hole":
            points.extend(target["point_tokens"])
        elif target["kind"] == "axis":
            lines.append(target["entity"])
    names = [e.name for e in table.entries if e.state in (FREE, DERIVED)]
    names += [m["name"] for m in _numeric_model(table)]
    return {"sketches": tokens, "points": list(dict.fromkeys(points)), "lines": list(dict.fromkeys(lines)),
            "params": list(dict.fromkeys(names)), "target": True}


# ---- which sizes to probe ------------------------------------------------------------------------------------

def sketch_driven(table):
    """Fusion names of the ticked sizes that reach a model parameter made by a sketch dimension or a construction
    plane (of the body's scope), in table order."""
    reached = set()
    for m in table.model_params.values():
        if (m.get("created_by") or {}).get("kind") in FOLLOWED_KINDS:
            reached |= table.depends(m["name"])
    return [name for name in table.ticked if name in reached]


def kept_sizes(table, free_sizes):
    """Fusion names of the sizes to probe: the free sizes of the first translation (recipe names in `free_sizes`),
    plus every ticked size that reaches a sketch dimension or a construction plane. In table order."""
    free = set(free_sizes)
    driven = set(sketch_driven(table))
    return [n for n in table.ticked if table.size_name(n) in free or n in driven]


# ---- probe rows ----------------------------------------------------------------------------------------------

def state_values(sizes, overrides=None):
    """Manifest value of every size (Fusion name) with `overrides` applied: the `values` of a probe state."""
    values = {s["param"]: s["value"] for s in sizes}
    values.update(overrides or {})
    return values


def _row(sizes, name, overrides, key=None):
    manifest = state_values(sizes, overrides)
    current = {s["param"]: s["value"] for s in sizes}
    return {
        "name": name[:MAX_NAME_CHARS],
        "key": "probe: " + (key or name),
        "values": {s["param"]: display_from_manifest(manifest[s["param"]], s["unit"]) for s in sizes},
        "step": False,
        "state": manifest,
        "varied": sorted(p for p in overrides if abs(manifest[p] - current[p]) > _SAME),
    }


def _others(size):
    """The ends of the size's range that differ from its current value."""
    return [end for end in (size["min"], size["max"]) if abs(end - size["value"]) > _SAME]


def probe_rows(sizes, moved, limit=MAX_PROBE_ROWS):
    """The states to try, as `(rows, untried)`.

    sizes: the kept sizes, with the range ends to try. moved: the params that move covered sketch values. A moved
    size gets a row at each range end that differs from its current value; with two or more moved sizes, one row
    puts all kept sizes at their minimum and one at their maximum. A row has no STEP (`"step": False`); `state` holds
    the manifest values, `varied` the params that differ. `untried` lists the moved params left without rows by the
    row limit.
    """
    rows, untried = [], []
    moved_sizes = [s for s in sizes if s["param"] in moved]
    for size in moved_sizes:
        wanted = _others(size)
        if len(rows) + len(wanted) > limit:
            untried.append(size["param"])
            continue
        for end in wanted:
            label = "min" if end == size["min"] else "max"
            rows.append(_row(sizes, "%s (%s)" % (size["size"][:MAX_NAME_CHARS - 6], label), {size["param"]: end},
                             "%s (%s)" % (size["param"], label)))
    if len(moved_sizes) >= 2 and len(rows) + 2 <= limit:
        for label, key in (("all min", "min"), ("all max", "max")):
            rows.append(_row(sizes, label, {s["param"]: s[key] for s in sizes}))
    return rows, untried
