"""What to read from Fusion and which size settings to try. Pure: no Fusion imports.

`scan` finds the sketches whose numbers the probe can follow ("covered" ones): every capture record that names them
is a profile, a hole point set or a revolve axis line that the reader gave tokens for. Which records a step type
carries comes from the step kind table (`translator/step_kinds.py`, `sketches`). `refs` finds the measured
references of other components (a plane, axis, direction or point a step uses) that the probe reads again at every
state. `request` is what the reader reads per state, `kept_sizes` the sizes worth probing, `probe_rows` the size
settings to try.

Sizes are dicts as in `export_plan.size_offers.probe_sizes`: param (Fusion name), size (recipe name), unit, value,
min, max (manifest numbers).
"""
from ..package.manifest import MAX_NAME_CHARS
from ..package.units import display_from_manifest
from ..params import defaults, geometry_links
from ..params.size_table import DERIVED, FREE
from ..translator.loops import profile_loops
from ..translator.result import Refusal
from ..translator.sizes import probed_sizes
from ..translator.step_kinds import AXIS, HOLE_POINTS, PROFILES, step_type

MAX_PROBE_ROWS = 64
# Ticked sizes that nothing ties to a sketch, tried after all the others while rows are left.
MAX_EXTRA_SIZES = 8
# Unticked parameters that act on another component, tried once each to find links the reader cannot see.
MAX_DISCOVERY = 12
# A row that does not build is tried again nearer to the value now: this share of the way to the range end, in turn.
# Each try is one more Fusion recompute; a nearer value that builds is enough for the fit, which then holds between
# the values measured.
NEARER_STEPS = (0.5, 0.25, 0.1)
# Rows the export adds for those tries in all, inside `MAX_PROBE_ROWS`: discovery rows get what is left.
MAX_NEARER_ROWS = 24
_SAME = 1e-9
_CURVES = ("line", "arc", "circle", "ellipse")


class Scan:
    """`targets`: the covered records (dicts with `kind` "profile", "hole" or "axis", `item` and what the fit reads).
    `covered`: sketch token to name ("" when the record has none). `uncovered`: tokens of sketches that some record
    uses in a way the probe cannot follow. `named`: the name of every sketch a record names, covered or not, by token
    (a sketch no record gives a name for is missing). `native`: tokens of the covered sketches of tool bodies from other
    components: they are read in their own component's frame, not brought into the part's (`request`)."""

    def __init__(self):
        self.targets = []
        self.native = set()
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
    """The `Scan` of a capture: its items in the target's component, and the steps of tool bodies from other
    components (`helper_of`), that carry a profile, a hole or a revolve axis."""
    out = Scan()
    for item in capture.get("items") or []:
        data = item.get("data") or {}
        if (item.get("suppressed") or (item.get("in_target_component") is False and not item.get("helper_of"))
                or "read_error" in data):
            continue
        spec = step_type(item.get("type"))
        records = spec.sketches if spec is not None else ()
        before = len(out.targets)
        for record in records:
            _SCANNERS[record](out, item.get("index"), data)
        if not records:
            _stray_tokens(data, out)
        if item.get("helper_of"):
            out.native.update(t["sketch_token"] for t in out.targets[before:])
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


_SCANNERS = {PROFILES: _scan_profiles, AXIS: _scan_axis, HOLE_POINTS: _scan_hole}


# ---- measured references ---------------------------------------------------------------------------------------

SHAPE_PLANE, SHAPE_AXIS, SHAPE_DIRECTION, SHAPE_POINT = "plane", "axis", "direction", "point"
NO_TOKEN = "it has no token to find it again"
NO_PLACE = "its place could not be brought into the part's coordinates"
_POINT_TYPES = ("SketchPoint", "BRepVertex")


def is_vector(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


def _shape(ref):
    """What of a reference is followed: a plane (point and normal), an axis (point and direction), a direction alone,
    or a point (a sketch point or vertex); None when its record has no usable geometry."""
    point, normal, direction = (is_vector(ref.get(k)) for k in ("point", "normal", "dir"))
    if point and normal:
        return SHAPE_PLANE
    if point and direction:
        return SHAPE_AXIS
    if direction:
        return SHAPE_DIRECTION
    return SHAPE_POINT if point and ref.get("type") in _POINT_TYPES else None


def refs(capture, items=None):
    """The measured references of the capture's steps (`params.geometry_links.item_refs`), each with its `shape` and,
    when the probe cannot follow it, a `reason` (else empty)."""
    out = []
    for entry in geometry_links.capture_refs(capture, items):
        ref = entry["ref"]
        shape = _shape(ref)
        reason = "" if shape else NO_PLACE
        if shape and not ref.get("token"):
            shape, reason = None, NO_TOKEN
        out.append(dict(entry, shape=shape, reason=reason))
    return out


# ---- what to read per state ----------------------------------------------------------------------------------

def _numeric_model(table):
    return [m for m in table.model_params.values() if defaults.dim_of_unit(m.get("unit")) is not None]


def request(capture, table, covered=None, wanted=None):
    """What the reader reads at each state, or None when no sketch is covered and no reference can be followed.

    `covered` limits the sketches to these tokens (the ones whose first read matched the capture). `wanted` limits the
    references to these keys.
    `{ "sketches": [token], "points": [token], "lines": [token], "params": [Fusion name], "target": True,
       "refs": { key: { "token", "type", "path", "shape" } } }`; `refs` is left out when empty. `native` lists the sketches of
    tool bodies from other components, and is left out when there are none.
    """
    found = scan(capture)
    tokens = [t for t in found.covered if covered is None or t in covered]
    followed = {r["key"]: {"token": r["ref"]["token"], "type": r["ref"].get("type") or "",
                           "path": r["ref"].get("path") or "", "shape": r["shape"]}
                for r in refs(capture) if r["shape"] and (wanted is None or r["key"] in wanted)}
    if not tokens and not followed:
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
    out = {"sketches": tokens, "points": list(dict.fromkeys(points)), "lines": list(dict.fromkeys(lines)),
           "params": list(dict.fromkeys(names)), "target": True}
    native = [t for t in tokens if t in found.native]
    if native:
        out["native"] = native
    if followed:
        out["refs"] = followed
    return out


# ---- which sizes to probe ------------------------------------------------------------------------------------

def sketch_driven(table):
    """Fusion names of the ticked sizes that reach a model parameter made by a sketch dimension or a construction
    plane (of the body's scope), or a sketch or a measured reference through the geometry of another component
    (`table.links`), in table order (`translator.sizes.probed_sizes`)."""
    return probed_sizes(table)


def extra_sizes(table, kept, limit=MAX_EXTRA_SIZES):
    """Fusion names of the ticked sizes the probe also tries although nothing ties them to a sketch: the person ticked
    them, so they may move a sketch in a way the capture cannot show. At most `limit`, in table order; `kept` are the
    sizes probed anyway."""
    kept = set(kept)
    return [name for name in table.ticked if name not in kept][:limit]


def kept_sizes(table, free_sizes):
    """Fusion names of the sizes to probe: the free sizes of the first translation (recipe names in `free_sizes`),
    plus every ticked size that reaches a sketch dimension, a construction plane or a sketch through another component
    (`sketch_driven`). In table order."""
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


def probe_rows(sizes, moved, limit=MAX_PROBE_ROWS, extra=()):
    """The states to try, as `(rows, untried)`.

    sizes: the kept sizes, with the range ends to try. moved: the params that move covered sketch values. A moved
    size gets a row at each range end that differs from its current value; with two or more moved sizes, one row
    puts all kept sizes at their minimum and one at their maximum. A row has no STEP (`"step": False`); `state` holds
    the manifest values, `varied` the params that differ. `untried` lists the moved params left without rows by the
    row limit. `extra` are params tried on a guess (`extra_sizes`): their rows come after the moved ones, and one
    left without rows is not listed in `untried`.
    """
    rows, untried = [], []
    moved_sizes = [s for s in sizes if s["param"] in moved]
    guessed = [s for s in sizes if s["param"] in extra and s["param"] not in moved]
    for size in moved_sizes + guessed:
        wanted = _others(size)
        if len(rows) + len(wanted) > limit:
            if size["param"] in moved:
                untried.append(size["param"])
            continue
        for end in wanted:
            label = "min" if end == size["min"] else "max"
            rows.append(_row(sizes, "%s (%s)" % (size["size"][:MAX_NAME_CHARS - 6], label), {size["param"]: end},
                             "%s (%s)" % (size["param"], label)))
    if len(moved_sizes) + len(guessed) >= 2 and len(rows) + 2 <= limit:
        for label, key in (("all min", "min"), ("all max", "max")):
            rows.append(_row(sizes, label, {s["param"]: s[key] for s in sizes}))
    return rows, untried


def _tried_alone(states, name, value):
    """`(value, built)` of every state that set only `name` to another value than `value`."""
    out = []
    for state in states:
        values = state.get("values") or {}
        if list(values) == [name] and abs(values[name] - value) > _SAME:
            out.append((values[name], state.get("built") is not False))
    return out


def _toward(size, end, share):
    """The value `share` of the way from the size's value to `end`; a count is rounded to a whole number."""
    value = size["value"] + share * (end - size["value"])
    return float(round(value)) if size.get("kind") == "count" else value


def _next_nearer(size, end, tried):
    """The next value toward `end` to try after rows on that side that did not build, or None when the steps are used
    up. `tried` are the values tried alone on that side."""
    span = end - size["value"]
    nearest = min(abs((v - size["value"]) / span) for v in tried)
    for share in NEARER_STEPS:
        if share >= nearest - _SAME:
            continue
        value = _toward(size, end, share)
        if abs(value - size["value"]) > _SAME and all(abs(value - v) > _SAME for v in tried):
            return value
    return None


def _nearer_for(size, states, moved):
    """`[(label, value)]`: the rows that try `size` nearer to its value after rows that did not build."""
    tried = _tried_alone(states, size["param"], size["value"])
    out = []
    for label, end in (("min", size["min"]), ("max", size["max"])):
        side = [(v, ok) for v, ok in tried if (v - size["value"]) * (end - size["value"]) > 0]
        if side and not any(ok for _, ok in side):
            value = _next_nearer(size, end, [v for v, _ in side])
            if value is not None:
                out.append((label, value))
    built = [v for v, ok in tried if ok]
    if not out and size["param"] in moved and len(built) == 1:
        value = _toward(size, built[0], 0.5)
        if abs(value - size["value"]) > _SAME and all(abs(value - v) > _SAME for v, _ in tried):
            out.append(("check", value))
    return out


def nearer_rows(sizes, states, moved=(), limit=MAX_NEARER_ROWS):
    """The next rows that try sizes nearer to their value now, after rows that did not build.

    `states` are the probe states so far (`values` and `built`). For each size and each side of its value whose rows
    all failed to build: one row `NEARER_STEPS` of the way toward that range end, the first step nearer than the
    nearest value tried there. A size in `moved` (it moved a sketch or a measured place) with only one row that built
    and nothing left to try gets one more row half way to that value, so the fit has two readings to tell a straight
    line from a curve. Sizes that no row built come first. At most `limit` rows; the export calls this again after
    each batch, so each call gives one step per side."""
    plans = [(size, _nearer_for(size, states, set(moved))) for size in sizes]
    unbuilt = {size["param"] for size in sizes
               if not any(ok for _, ok in _tried_alone(states, size["param"], size["value"]))}
    plans.sort(key=lambda entry: entry[0]["param"] not in unbuilt)
    rows = []
    for size, wanted in plans:
        for label, value in wanted:
            if len(rows) >= limit:
                return rows
            name = "%s (%s, nearer)" % (size["size"][:MAX_NAME_CHARS - 16], label)
            rows.append(_row(sizes, name, {size["param"]: value}, "%s (%s %r)" % (size["param"], label, value)))
    return rows


def check_rows(sizes, curved, spans, room):
    """Two rows that check the other sizes together once some sizes move a value along a curve on their own
    (`curved`): every other size at the lowest, then at the highest value it was measured at (`spans`, as
    `Motion.spans`), the curved ones at their value now. The fit of such a value over the other sizes (`Stuck.rest`)
    is then checked by a state that changes several of them at once. Empty when fewer than two other sizes would
    change, or `room` is under two rows."""
    if room < 2:
        return []
    rows = []
    for label, end in (("all low but curved", "low"), ("all high but curved", "high")):
        overrides = {s["param"]: spans[s["param"]][end] for s in sizes
                     if s["param"] not in curved and s["param"] in spans
                     and abs(spans[s["param"]][end] - s["value"]) > _SAME}
        if len(overrides) >= 2:
            rows.append(_row(sizes, label, overrides))
    return rows


def discovery_rows(candidates, room, limit=MAX_DISCOVERY):
    """One row per candidate, in order, at most `limit` and `room`: the parameter alone set to its `end`.

    A candidate is a size dict as in `probe_rows` plus `end` (a manifest number). These rows only tell whether a
    sketch moves with the parameter; they are not states of the motion fit."""
    rows = []
    for candidate in candidates[:max(0, min(limit, room))]:
        row = _row([candidate], "%s (try)" % candidate["size"][:MAX_NAME_CHARS - 6],
                   {candidate["param"]: candidate["end"]}, "try %s" % candidate["param"])
        rows.append(row)
    return rows


def discovery_left(candidates, room, limit=MAX_DISCOVERY):
    """The candidates `discovery_rows` leaves without a row, in order."""
    return list(candidates[max(0, min(limit, room)):])
