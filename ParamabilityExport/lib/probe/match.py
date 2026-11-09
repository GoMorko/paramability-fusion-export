"""Turn a sketch state read in Fusion into the numbers the translator writes, keyed as in the motion file.

A state profile is matched to the capture profile by the sketch entity tokens of its curves, mapped into the sketch
frame of the capture, and run through the translator's own `profile_loops`, so a value here is the value the
translator writes. A state that cannot be turned into the same outline is a problem with a cause (`motion.SHAPE`,
`TURNS`, `UNREAD`), not a number.
"""
import math

from ..translator.loops import profile_loops
from ..translator.result import Refusal
from .motion import SHAPE, TURNS, UNREAD

POINT_TOLERANCE = 1e-4
TURN_TOLERANCE = 1e-6
ANGLE_TOLERANCE = 1e-6
_SKIP = ("angleDeg",)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _dist(a, b):
    return math.hypot(*(x - y for x, y in zip(a, b)))


def _turned(z, ref):
    """True when the unit normal `z` is not the unit normal `ref`."""
    cross = [z[1] * ref[2] - z[2] * ref[1], z[2] * ref[0] - z[0] * ref[2], z[0] * ref[1] - z[1] * ref[0]]
    return math.sqrt(_dot(cross, cross)) > TURN_TOLERANCE or _dot(z, ref) < 0


def _to_ref(world_vector, ref):
    return [_dot(world_vector, ref["x"]), _dot(world_vector, ref["y"])]


def _point(p, frame, ref):
    world = [frame["origin"][i] + p[0] * frame["x"][i] + p[1] * frame["y"][i] for i in range(3)]
    return _to_ref(_sub(world, ref["origin"]), ref)


def _direction(d, frame, ref):
    world = [d[0] * frame["x"][i] + d[1] * frame["y"][i] for i in range(3)]
    out = _to_ref(world, ref)
    size = math.hypot(*out) or 1.0
    return [out[0] / size, out[1] / size]


_POINT_KEYS = {"line": ("start", "end"), "arc": ("start", "end", "mid", "center"), "circle": ("center",),
               "ellipse": ("center",)}


def _mapped(curve, frame, ref):
    out = dict(curve)
    for key in _POINT_KEYS.get(curve["kind"], ()):
        out[key] = _point(curve[key], frame, ref)
    if curve["kind"] == "ellipse":
        out["major_dir"] = _direction(curve["major_dir"], frame, ref)
    return out


def _gap(curve, other):
    """Sum of the distances between the key points of two curves of one kind."""
    return sum(_dist(curve[k], other[k]) for k in _POINT_KEYS[curve["kind"]])


def _aligned(curve, like):
    """`curve` turned to run the way `like` does (a line or arc swapped end to end, an ellipse axis flipped)."""
    if curve["kind"] in ("line", "arc"):
        swapped = dict(curve, start=curve["end"], end=curve["start"])
        return swapped if _gap(swapped, like) < _gap(curve, like) else curve
    if curve["kind"] == "ellipse" and _dot(curve["major_dir"], like["major_dir"]) < 0:
        return dict(curve, major_dir=[-v for v in curve["major_dir"]])
    return curve


def _signature(loop):
    tokens = [c.get("entity") for c in loop.get("curves") or []]
    return None if not tokens or None in tokens else (bool(loop.get("outer")), tuple(sorted(tokens)))


def _arrange_loop(state_loop, loop, frame, ref):
    """The state loop's curves in the order and direction of the capture loop, mapped to `ref`; and their gap."""
    left = [_mapped(c, frame, ref) for c in state_loop["curves"]]
    out, total = [], 0.0
    for curve in loop["curves"]:
        best = None
        for other in left:
            if other.get("entity") != curve.get("entity") or other["kind"] != curve["kind"]:
                continue
            aligned = _aligned(other, curve)
            gap = _gap(aligned, curve)
            if best is None or gap < best[0]:
                best = (gap, other, aligned)
        if best is None:
            return None
        left.remove(best[1])
        out.append(best[2])
        total += best[0]
    return out, total


def _arrange(state_profile, profile, frame, ref):
    """The state profile as capture style loops in the capture's loop order, and the gap to the capture; or None."""
    state_loops = state_profile.get("loops") or []
    if len(state_loops) != len(profile["loops"]):
        return None
    used, loops, total = set(), [], 0.0
    for loop in profile["loops"]:
        best = None
        for at, other in enumerate(state_loops):
            if at in used or _signature(other) != _signature(loop):
                continue
            arranged = _arrange_loop(other, loop, frame, ref)
            if arranged and (best is None or arranged[1] < best[2]):
                best = (at, arranged[0], arranged[1])
        if best is None:
            return None
        used.add(best[0])
        loops.append({"outer": bool(loop.get("outer")), "curves": best[1]})
        total += best[2]
    return loops, total


def _outline(node):
    """The loop with its numbers taken out: what two loops must share to be the same outline."""
    if isinstance(node, dict):
        return {k: _outline(v) for k, v in node.items() if k not in _SKIP}
    if isinstance(node, list):
        return [_outline(v) for v in node]
    return None if isinstance(node, (int, float)) else node


def _numbers(node, path, out):
    if isinstance(node, dict):
        for key, value in node.items():
            if key not in _SKIP:
                _numbers(value, path + [key], out)
    elif isinstance(node, list):
        for at, value in enumerate(node):
            _numbers(value, path + [str(at)], out)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        out[".".join(path)] = float(node)


def _angles_equal(loop, other):
    return abs(loop.get("angleDeg", 0.0) - other.get("angleDeg", 0.0)) <= ANGLE_TOLERANCE


def _profile_loops(profile, name):
    return profile_loops({"sketch": name, "space": "sketch", "loops": profile["loops"]})


def _values_of(loops, plane, prefix):
    out = {prefix + "/plane": plane}
    for at, loop in enumerate(loops):
        numbers = {}
        _numbers(loop, [], numbers)
        out.update({"%s/l%d/%s" % (prefix, at, k): v for k, v in numbers.items()})
    return out


def _unit(v):
    size = math.hypot(v[0], v[1]) or 1.0
    return [v[0] / size, v[1] / size]


def curve_values(loops, like, prefix):
    """The values of the sketch curves of a profile, keyed `<prefix>/c<loop>.<curve>/<field>` in the capture's loop
    and curve order. A line gives `offset` (its distance from the sketch origin along the left normal of its captured
    direction) and `turn` (degrees it turned from that direction); an arc its `center.0`, `center.1` and `radius`.
    `like` are the capture loops, which fix each line's direction."""
    out = {}
    for k, (loop, ref) in enumerate(zip(loops, like)):
        for j, (curve, base) in enumerate(zip(loop["curves"], ref["curves"])):
            key = "%s/c%d.%d/" % (prefix, k, j)
            if curve["kind"] == "line":
                d0 = _unit(_sub(base["end"], base["start"]))
                d = _unit(_sub(curve["end"], curve["start"]))
                out[key + "offset"] = -d0[1] * curve["start"][0] + d0[0] * curve["start"][1]
                out[key + "turn"] = math.degrees(math.atan2(d0[0] * d[1] - d0[1] * d[0], _dot(d0, d)))
            elif curve["kind"] == "arc":
                out.update({key + "center.0": float(curve["center"][0]), key + "center.1": float(curve["center"][1]),
                            key + "radius": float(curve["radius"])})
    return out


def prefix(target):
    """`<item>/p<profile>` of a profile record."""
    return "%s/p%d" % (target["item"], target["p"])


def _capture_profile_values(target):
    profile = target["profile"]
    frame = profile["frame"]
    loops = _profile_loops(profile, target["sketch"])
    out = _values_of([loops[0]] + list(loops[1]), _dot(frame["origin"], frame["z"]), prefix(target))
    out.update(curve_values(profile["loops"], profile["loops"], prefix(target)))
    return out


def _state_profile_values(target, read):
    profile = target["profile"]
    ref = profile["frame"]
    record = (read.get("sketches") or {}).get(target["sketch_token"])
    if not isinstance(record, dict) or not isinstance(record.get("frame"), dict):
        return None, UNREAD
    frame = record["frame"]
    if _turned(frame["z"], ref["z"]):
        return None, TURNS
    best = None
    for candidate in record.get("profiles") or []:
        arranged = _arrange(candidate, profile, frame, ref)
        if arranged and (best is None or arranged[1] < best[1]):
            best = arranged
    if best is None:
        return None, SHAPE
    mapped = _profile_loops({"loops": best[0]}, target["sketch"])
    base = _profile_loops(profile, target["sketch"])
    if isinstance(mapped, Refusal) or isinstance(base, Refusal):
        return None, SHAPE
    got, want = [mapped[0]] + list(mapped[1]), [base[0]] + list(base[1])
    if _outline(got) != _outline(want) or not all(_angles_equal(a, b) for a, b in zip(got, want)):
        return None, SHAPE
    out = _values_of(got, _dot(frame["origin"], ref["z"]), prefix(target))
    out.update(curve_values(best[0], profile["loops"], prefix(target)))
    return out, None


def _hole_values(target, read, e0):
    prefix = "%s/positions" % target["item"]
    if read is None:
        return {"%s/%d/%d" % (prefix, n, c): float(p[c]) for n, p in enumerate(target["positions"])
                for c in range(3)}, None
    here = (read.get("sketches") or {}).get(target["sketch_token"]) or {}
    there = ((e0 or {}).get("sketches") or {}).get(target["sketch_token"]) or {}
    if not here.get("frame") or not there.get("frame"):
        return None, UNREAD
    if _turned(here["frame"]["z"], there["frame"]["z"]):
        return None, TURNS
    out = {}
    for n, token in enumerate(target["point_tokens"]):
        p = (read.get("points") or {}).get(token)
        if not p:
            return None, UNREAD
        out.update({"%s/%d/%d" % (prefix, n, c): float(p[c]) for c in range(3)})
    return out, None


def _axis_values(target, read):
    prefix = "%s/axis/point" % target["item"]
    if read is None:
        return {"%s/%d" % (prefix, c): float(target["axis"]["point"][c]) for c in range(3)}, None
    line = (read.get("lines") or {}).get(target["entity"])
    if not line:
        return None, UNREAD
    if _turned(line["dir"], target["axis"]["dir"]):
        return None, TURNS
    return {"%s/%d" % (prefix, c): float(line["point"][c]) for c in range(3)}, None


def captured_values(target):
    """The values of one covered record as the capture has them: a dict by key."""
    if target["kind"] == "profile":
        return _capture_profile_values(target)
    if target["kind"] == "hole":
        return _hole_values(target, None, None)[0]
    return _axis_values(target, None)[0]


def state_values(target, read, e0=None):
    """`(values, cause)` of one covered record in a state read: the numbers by key, or None and the cause."""
    if target["kind"] == "profile":
        return _state_profile_values(target, read)
    if target["kind"] == "hole":
        return _hole_values(target, read, e0)
    return _axis_values(target, read)


def readable(found, e0):
    """Tokens of the covered sketches whose every record the first read gives back as the capture has it
    (within 1e-4 mm). A sketch that fails stays with the measured check of the export."""
    bad = set()
    for target in found.targets:
        values, _ = state_values(target, e0 or {}, e0)
        want = captured_values(target)
        if values is None or values.keys() != want.keys() or any(
                abs(values[k] - v) > POINT_TOLERANCE for k, v in want.items()):
            bad.add(target["sketch_token"])
    return {t for t in found.covered if t not in bad}
