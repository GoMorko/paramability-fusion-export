"""Turn a sketch state read in Fusion into the numbers the translator writes, keyed as in the motion file.

A state profile is matched to the capture profile by the sketch entity tokens of its curves, mapped into the sketch
frame of the capture, and run through the translator's own `profile_loops`, so a value here is the value the
translator writes. Pieces of one sketch curve are paired by their place along the loop, so a loop that moved further
than its pieces are apart still pairs each piece with its own. A state that cannot be turned into the same outline is
a problem with a cause (`motion.SHAPE`, `TURNS`, `UNREAD`), not a number.
"""
import math

from ..translator.loops import profile_loops
from ..translator.result import Refusal
from ..sketch_values import keys
from ..sketch_values.motion import SHAPE, TURNS, UNREAD

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


def _gap(curve, other, shift=(0.0, 0.0)):
    """Sum of the distances between the key points of two curves of one kind, `curve` moved back by `shift`."""
    return sum(_dist(_sub(curve[k], shift), other[k]) for k in _POINT_KEYS[curve["kind"]])


def _aligned(curve, like, shift=(0.0, 0.0)):
    """`curve` turned to run the way `like` does (a line or arc swapped end to end, an ellipse axis flipped), compared
    once moved back by `shift`."""
    if curve["kind"] in ("line", "arc"):
        swapped = dict(curve, start=curve["end"], end=curve["start"])
        return swapped if _gap(swapped, like, shift) < _gap(curve, like, shift) else curve
    if curve["kind"] == "ellipse" and _dot(curve["major_dir"], like["major_dir"]) < 0:
        return dict(curve, major_dir=[-v for v in curve["major_dir"]])
    return curve


def _signature(loop):
    tokens = [c.get("entity") for c in loop.get("curves") or []]
    return None if not tokens or None in tokens else (bool(loop.get("outer")), tuple(sorted(tokens)))


def _same_curve(a, b):
    return a.get("entity") == b.get("entity") and a["kind"] == b["kind"]


def _centre(curve):
    points = [curve[k] for k in _POINT_KEYS[curve["kind"]]]
    return [sum(p[i] for p in points) / len(points) for i in range(2)]


def _shift(pairs):
    """The mean move from each capture curve to its state curve: how far the loop slid as a whole."""
    if not pairs:
        return (0.0, 0.0)
    moves = [_sub(_centre(state), _centre(curve)) for state, curve in pairs]
    return tuple(sum(m[i] for m in moves) / len(moves) for i in range(2))


def _lined_up(order, curves):
    """(state curves turned like the capture's, their gap, the gap left once the loop's slide is taken out)."""
    shift = _shift(list(zip(order, curves)))
    aligned = [_aligned(o, c, shift) for o, c in zip(order, curves)]
    return (aligned, sum(_gap(a, c) for a, c in zip(aligned, curves)),
            sum(_gap(a, c, shift) for a, c in zip(aligned, curves)))


def _walks(mapped, curves):
    """Orders of `mapped` along the loop (each start, both ways) whose entities and kinds match `curves` one by one."""
    n = len(curves)
    if n != len(mapped):
        return
    for step in (1, -1):
        for start in range(n):
            order = [mapped[(start + step * i) % n] for i in range(n)]
            if all(_same_curve(o, c) for o, c in zip(order, curves)):
                yield order


def _nearest(mapped, curves):
    """Each capture curve paired with a state curve of its entity and kind, the nearest once the slide shown by the
    curves that appear once is taken out; or None."""
    def count(curve, among):
        return sum(1 for other in among if _same_curve(other, curve))

    once = [(m, c) for c in curves if count(c, curves) == 1 and count(c, mapped) == 1
            for m in mapped if _same_curve(m, c)]
    shift = _shift(once)
    left, order = list(mapped), []
    for curve in curves:
        found = [o for o in left if _same_curve(o, curve)]
        if not found:
            return None
        best = min(found, key=lambda o: _gap(_aligned(o, curve, shift), curve, shift))
        left.remove(best)
        order.append(best)
    return order


def _arrange_loop(state_loop, loop, frame, ref):
    """The state loop's curves in the order and direction of the capture loop, mapped to `ref`; and their gap.

    Pieces of one sketch curve are told apart by their place along the loop when the loop reads in order, else by
    nearness once the loop's slide is taken out, so a loop that moved far still pairs each piece with its own."""
    mapped = [_mapped(c, frame, ref) for c in state_loop["curves"]]
    curves = loop["curves"]
    entities = [c.get("entity") for c in curves]
    repeated = len(set(entities)) < len(entities)
    walked = [_lined_up(order, curves) for order in _walks(mapped, curves)] if repeated else []
    if walked:
        best = min(walked, key=lambda w: w[2])
        return best[0], best[1]
    order = _nearest(mapped, curves)
    if order is None:
        return None
    aligned, gap, _ = _lined_up(order, curves)
    return aligned, gap


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
    out = {keys.plane(prefix): plane}
    for at, loop in enumerate(loops):
        numbers = {}
        _numbers(loop, [], numbers)
        out.update({keys.loop_field(prefix, at, k): v for k, v in numbers.items()})
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
            key = keys.curve(prefix, k, j)
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
    return keys.profile(target["item"], target["p"])


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
    item = target["item"]
    if read is None:
        return {keys.hole_point(item, n, c): float(p[c]) for n, p in enumerate(target["positions"])
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
        out.update({keys.hole_point(item, n, c): float(p[c]) for c in range(3)})
    return out, None


def _axis_values(target, read):
    item = target["item"]
    if read is None:
        return {keys.axis_point(item, c): float(target["axis"]["point"][c]) for c in range(3)}, None
    line = (read.get("lines") or {}).get(target["entity"])
    if not line:
        return None, UNREAD
    if _turned(line["dir"], target["axis"]["dir"]):
        return None, TURNS
    return {keys.axis_point(item, c): float(line["point"][c]) for c in range(3)}, None


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
    (within 1e-4 mm). A sketch that fails is not followed: the sizes that change it are loose."""
    bad = set()
    for target in found.targets:
        values, _ = state_values(target, e0 or {}, e0)
        want = captured_values(target)
        if values is None or values.keys() != want.keys() or any(
                abs(values[k] - v) > POINT_TOLERANCE for k, v in want.items()):
            bad.add(target["sketch_token"])
    return {t for t in found.covered if t not in bad}


def _all_numbers(node, out):
    if isinstance(node, dict):
        for key in sorted(node):
            _all_numbers(node[key], out)
    elif isinstance(node, list):
        for value in node:
            _all_numbers(value, out)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        out.append(float(node))


def _read_signature(record):
    """(frame numbers, curves sorted by their sketch curve token) of a sketch read."""
    frame = []
    _all_numbers(record.get("frame"), frame)
    curves = []
    for profile in record.get("profiles") or []:
        for loop in profile.get("loops") or []:
            for curve in loop.get("curves") or []:
                numbers = []
                _all_numbers({k: v for k, v in curve.items() if k not in ("entity", "kind", "type")}, numbers)
                curves.append((str(curve.get("entity") or ""), str(curve.get("kind") or ""), numbers))
    return frame, sorted(curves)


def _close(a, b):
    return len(a) == len(b) and all(abs(x - y) <= POINT_TOLERANCE for x, y in zip(a, b))


def same_read(before, now):
    """True when two reads of one sketch (`{ frame, profiles }`) have the same frame and curves, within 1e-4 mm."""
    frame_a, curves_a = _read_signature(before)
    frame_b, curves_b = _read_signature(now)
    return _close(frame_a, frame_b) and len(curves_a) == len(curves_b) and all(
        a[:2] == b[:2] and _close(a[2], b[2]) for a, b in zip(curves_a, curves_b))
