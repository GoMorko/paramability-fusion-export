"""Turn a sketch state read in Fusion into the numbers the translator writes, keyed as in the motion file.

A state profile is matched to the capture profile by the sketch entity tokens of its curves, mapped into the sketch
frame of the capture, and run through the translator's own `profile_loops`, so a value here is the value the
translator writes. Pieces of one sketch curve are paired by their place along the loop, so a loop that moved further
than its pieces are apart still pairs each piece with its own. A state that cannot be turned into the same outline is
a problem with a cause (`motion.SHAPE`, `TURNS`, `UNREAD`), not a number.

A flat face used as an outline is read the same way, from its edges (`read["faces"]`): edges carry no sketch token,
so its curves pair by kind and by their place along the loop.
"""
import math

from ..geometry import vec
from ..geometry.tolerances import POINT_TOLERANCE_MM
from ..translator.sketch.loops import profile_loops
from ..translator.paths.path_motion import swept_degrees
from ..translator.result import Refusal
from ..sketch_values import keys
from ..sketch_values.motion import SHAPE, TURNS, UNREAD

TURN_TOLERANCE = 1e-6
ANGLE_TOLERANCE = 1e-6
_SKIP = ("angleDeg",)


def _dist(a, b):
    return math.hypot(*(x - y for x, y in zip(a, b)))


def _turned(z, ref):
    """True when the unit normal `z` is not the unit normal `ref`."""
    cross = [z[1] * ref[2] - z[2] * ref[1], z[2] * ref[0] - z[0] * ref[2], z[0] * ref[1] - z[1] * ref[0]]
    return math.sqrt(vec.dot(cross, cross)) > TURN_TOLERANCE or vec.dot(z, ref) < 0


def _faces_back(z, ref):
    """True when the unit normal `z` is `ref` reversed: the plane stays, but the face looks the other way."""
    cross = [z[1] * ref[2] - z[2] * ref[1], z[2] * ref[0] - z[0] * ref[2], z[0] * ref[1] - z[1] * ref[0]]
    return math.sqrt(vec.dot(cross, cross)) <= TURN_TOLERANCE and vec.dot(z, ref) < 0


def _to_ref(world_vector, ref):
    return [vec.dot(world_vector, ref["x"]), vec.dot(world_vector, ref["y"])]


def _point(p, frame, ref):
    world = [frame["origin"][i] + p[0] * frame["x"][i] + p[1] * frame["y"][i] for i in range(3)]
    return _to_ref(vec.sub(world, ref["origin"]), ref)


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
    return sum(_dist(vec.sub(curve[k], shift), other[k]) for k in _POINT_KEYS[curve["kind"]])


def _aligned(curve, like, shift=(0.0, 0.0)):
    """`curve` turned to run the way `like` does (a line or arc swapped end to end, an ellipse axis flipped), compared
    once moved back by `shift`."""
    if curve["kind"] in ("line", "arc"):
        swapped = dict(curve, start=curve["end"], end=curve["start"])
        return swapped if _gap(swapped, like, shift) < _gap(curve, like, shift) else curve
    if curve["kind"] == "ellipse" and vec.dot(curve["major_dir"], like["major_dir"]) < 0:
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
    moves = [vec.sub(_centre(state), _centre(curve)) for state, curve in pairs]
    return tuple(sum(m[i] for m in moves) / len(moves) for i in range(2))


def _joined_end(curves, at):
    """"start" or "end": the end of the line or arc `curves[at]` that touches the curve before it in the loop, or None
    when neither or both do (a loop of fewer than three curves, a curve that is not a line or arc, a gap)."""
    curve, before = curves[at], curves[at - 1]
    if len(curves) < 3 or curve["kind"] not in ("line", "arc") or before["kind"] not in ("line", "arc"):
        return None
    touches = [min(_dist(curve[k], before[e]) for e in ("start", "end")) <= POINT_TOLERANCE_MM
               for k in ("start", "end")]
    if touches[0] == touches[1]:
        return None
    return "start" if touches[0] else "end"


def _chained(aligned, curves):
    """The state curves run the way the capture's run along the loop: a curve that starts where the curve before it
    ends in the capture does so in the state too. Fusion lists a profile curve with its ends either way round, and a
    curve that turned far can look nearer swapped, so where the loop's joins tell, they decide."""
    out = list(aligned)
    for at, curve in enumerate(aligned):
        want, got = _joined_end(curves, at), _joined_end(aligned, at)
        if want and got and want != got:
            out[at] = dict(curve, start=curve["end"], end=curve["start"])
    return out


def _lined_up(order, curves):
    """(state curves turned like the capture's, their gap, the gap left once the loop's slide is taken out)."""
    shift = _shift(list(zip(order, curves)))
    aligned = _chained([_aligned(o, c, shift) for o, c in zip(order, curves)], curves)
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


def _bulge(arc):
    """The direction from an arc's centre to its middle point: the side of its circle the arc piece lies on."""
    centre = arc.get("center")
    if centre is None:
        return None
    return vec.sub(arc["mid"], centre)


def _likeness(arranged, profile):
    """How a candidate state profile ranks against the capture's: first by how many of its arcs lie on the other side
    of their circle than the captured arcs they pair with, then by its gap. Regions of one sketch share curves (each
    piece of a cut circle bounds its own region), and a region that moved further than the pieces are apart lies
    nearer to its neighbour's place; the piece of the circle each region holds does not change side."""
    flipped = 0
    for state_loop, loop in zip(arranged[0], profile["loops"]):
        for got, want in zip(state_loop["curves"], loop["curves"]):
            if got["kind"] != "arc" or want["kind"] != "arc" or "mid" not in got or "mid" not in want:
                continue
            a, b = _bulge(got), _bulge(want)
            if a is not None and b is not None and vec.dot(a, b) < 0:
                flipped += 1
    return flipped, arranged[1]


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
                d0 = _unit(vec.sub(base["end"], base["start"]))
                d = _unit(vec.sub(curve["end"], curve["start"]))
                out[key + "offset"] = -d0[1] * curve["start"][0] + d0[0] * curve["start"][1]
                out[key + "turn"] = math.degrees(math.atan2(d0[0] * d[1] - d0[1] * d[0], vec.dot(d0, d)))
            elif curve["kind"] == "arc":
                out.update({key + "center.0": float(curve["center"][0]), key + "center.1": float(curve["center"][1]),
                            key + "radius": float(curve["radius"])})
    return out


def prefix(target):
    """`<item>/p<profile>` of a profile record, `<item>/path` of a sweep path, `<item>/face` of a face."""
    if target["kind"] == "path":
        return keys.path(target["item"])
    if target["kind"] == "face":
        return keys.face(target["item"])
    return keys.profile(target["item"], target["p"])


def _capture_profile_values(target):
    profile = target["profile"]
    frame = profile["frame"]
    loops = _profile_loops(profile, target["sketch"])
    out = _values_of([loops[0]] + list(loops[1]), vec.dot(frame["origin"], frame["z"]), prefix(target))
    out.update(curve_values(profile["loops"], profile["loops"], prefix(target)))
    return out


def _by_kind(loops):
    """Face loops with each curve named by its kind, so the pairing above matches edges by kind and place."""
    return [dict(loop, curves=[dict(c, entity=c.get("kind")) for c in loop.get("curves") or []]) for loop in loops]


def _capture_face_values(target):
    profile = target["profile"]
    loops = _profile_loops(profile, target["sketch"])
    return _values_of([loops[0]] + list(loops[1]), vec.dot(profile["frame"]["origin"], profile["frame"]["z"]),
                      prefix(target))


def _state_face_values(target, read):
    record = (read.get("faces") or {}).get(target["sketch_token"])
    if not isinstance(record, dict) or not isinstance(record.get("frame"), dict) or not record.get("loops"):
        return None, UNREAD
    ref, frame = target["profile"]["frame"], record["frame"]
    if _faces_back(frame["z"], ref["z"]):
        # The body behind the face lies on its other side (an earlier extrude reached past its start): the step
        # that starts on the face goes the other way, another shape, which limits the range like another outline.
        return None, SHAPE
    if _turned(frame["z"], ref["z"]):
        return None, TURNS
    arranged = _arrange({"loops": _by_kind(record["loops"])}, {"loops": _by_kind(target["profile"]["loops"])}, frame,
                        ref)
    if arranged is None:
        return None, SHAPE
    mapped = _profile_loops({"loops": arranged[0]}, target["sketch"])
    base = _profile_loops(target["profile"], target["sketch"])
    if isinstance(mapped, Refusal) or isinstance(base, Refusal):
        return None, SHAPE
    got, want = [mapped[0]] + list(mapped[1]), [base[0]] + list(base[1])
    if _outline(got) != _outline(want) or not all(_angles_equal(a, b) for a, b in zip(got, want)):
        return None, SHAPE
    return _values_of(got, vec.dot(frame["origin"], ref["z"]), prefix(target)), None


def _loops_of(record):
    """Every loop of a sketch read, as lists of curves."""
    return [loop.get("curves") or [] for profile in record.get("profiles") or [] for loop in profile.get("loops") or []]


def _tokens(record):
    return {c.get("entity") for curves in _loops_of(record) for c in curves if c.get("entity")}


def _rename_pairs(base_curves, curves, missing, new):
    """The `{new token: missing token}` pairs of the one walk of a state loop along a base loop of the same length in
    which every other curve keeps its token and each pair keeps its kind; None when no walk or more than one lines them
    up that way. A walk counts only with at least one curve that kept its token, so a loop of new curves pairs nothing."""
    n = len(base_curves)
    found = []
    for step in (1, -1):
        for start in range(n):
            order = [curves[(start + step * i) % n] for i in range(n)]
            pairs, kept = {}, 0
            for before, now in zip(base_curves, order):
                if before.get("kind") != now.get("kind"):
                    break
                a, b = before.get("entity"), now.get("entity")
                if a == b:
                    kept += 1
                elif a in missing and b in new and pairs.get(b, a) == a:
                    pairs[b] = a
                else:
                    break
            else:
                if kept and pairs:
                    found.append(pairs)
    return found[0] if len(found) == 1 else None


def renamed(record, base):
    """`record` (a sketch read) with the curves Fusion made again under a new token named as in `base` (an earlier read
    of the same sketch). Fusion may give a projected or intersection curve a new token when it recomputes it, although
    it is the same curve: a curve of `base` whose token is gone pairs with a new curve of the same kind that sits in its
    place along a loop, between curves that kept their tokens. A pair is used only when every loop agrees on it. The
    record itself when nothing is renamed."""
    if not isinstance(record, dict) or not isinstance(base, dict):
        return record
    before, now = _tokens(base), _tokens(record)
    missing, new = before - now, now - before
    if not missing or not new:
        return record
    pairs = {}
    for curves in _loops_of(record):
        if not any(c.get("entity") in new for c in curves):
            continue
        for base_curves in _loops_of(base):
            if len(base_curves) != len(curves) or not any(c.get("entity") in missing for c in base_curves):
                continue
            for b, a in (_rename_pairs(base_curves, curves, missing, new) or {}).items():
                pairs.setdefault(b, set()).add(a)
    names = {b: next(iter(a)) for b, a in pairs.items() if len(a) == 1}
    if not names or len(set(names.values())) != len(names):
        return record
    profiles = [dict(p, loops=[dict(loop, curves=[dict(c, entity=names.get(c.get("entity"), c.get("entity")))
                                                    for c in loop.get("curves") or []])
                               for loop in p.get("loops") or []]) for p in record.get("profiles") or []]
    return dict(record, profiles=profiles)


def _state_profile_values(target, read, e0=None):
    profile = target["profile"]
    ref = profile["frame"]
    record = (read.get("sketches") or {}).get(target["sketch_token"])
    if not isinstance(record, dict) or not isinstance(record.get("frame"), dict):
        return None, UNREAD
    record = renamed(record, ((e0 or {}).get("sketches") or {}).get(target["sketch_token"]))
    frame = record["frame"]
    if _turned(frame["z"], ref["z"]):
        return None, TURNS
    best = None
    for candidate in record.get("profiles") or []:
        arranged = _arrange(candidate, profile, frame, ref)
        if arranged and (best is None or _likeness(arranged, profile) < _likeness(best, profile)):
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
    out = _values_of(got, vec.dot(frame["origin"], ref["z"]), prefix(target))
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


_PATH_POINTS = {"line": ("start", "end"), "arc": ("start", "mid", "end", "center"), "circle": ("center",)}


def _path_curve_values(prefix, curve):
    """The keys of one sweep path curve (`sketch_values.keys`): its points in the sketch plane, an arc's or circle's
    radius, and the angle an arc turns."""
    out = {}
    for name in _PATH_POINTS[curve["kind"]]:
        out.update({"%s%s.%d" % (prefix, name, c): float(curve[name][c]) for c in range(2)})
    if curve["kind"] != "line":
        out[prefix + "radius"] = float(curve["radius"])
    if curve["kind"] == "arc":
        out[prefix + "turn"] = swept_degrees(curve)
    return out


def _path_state(target, read):
    """`(frame, curves)` of the sweep path's sketch in a state read, or None and the cause. A state where the sketch
    plane turned, or its origin slid across the plane, has a cause."""
    path = target["path"]
    record = (read.get("sketches") or {}).get(target["sketch_token"])
    if not isinstance(record, dict) or not isinstance(record.get("frame"), dict) or not isinstance(
            record.get("curves"), dict):
        return None, UNREAD
    frame, ref = record["frame"], path["frame"]
    if _turned(frame["z"], ref["z"]) or _turned(frame["x"], ref["x"]) or any(
            abs(vec.dot(vec.sub(frame["origin"], ref["origin"]), ref[axis])) > POINT_TOLERANCE_MM
            for axis in ("x", "y")):
        return None, TURNS
    found = [record["curves"].get(curve["entity"]) for curve in path["curves"]]
    if any(not isinstance(f, dict) or f.get("kind") != c["kind"] for f, c in zip(found, path["curves"])):
        return None, UNREAD
    return (frame, found), None


def _path_values(target, read):
    """The keys of a sweep path: each curve of it and the position of its sketch plane along the plane's normal."""
    path = target["path"]
    frame, curves = path["frame"], [c["flat"] for c in path["curves"]]
    if read is not None:
        state, cause = _path_state(target, read)
        if state is None:
            return None, cause
        frame, curves = state
    out = {keys.path_plane(target["item"]): vec.dot(frame["origin"], path["frame"]["z"])}
    for number, curve in enumerate(curves):
        out.update(_path_curve_values(keys.path_curve(target["item"], number), curve))
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
    if target["kind"] == "face":
        return _capture_face_values(target)
    if target["kind"] == "hole":
        return _hole_values(target, None, None)[0]
    if target["kind"] == "path":
        return _path_values(target, None)[0]
    return _axis_values(target, None)[0]


def state_values(target, read, e0=None):
    """`(values, cause)` of one covered record in a state read: the numbers by key, or None and the cause."""
    if target["kind"] == "profile":
        return _state_profile_values(target, read, e0)
    if target["kind"] == "face":
        return _state_face_values(target, read)
    if target["kind"] == "hole":
        return _hole_values(target, read, e0)
    if target["kind"] == "path":
        return _path_values(target, read)
    return _axis_values(target, read)


def matches_capture(target, e0):
    """True when the first read `e0` gives back every value of the record `target` as the capture has it (within
    1e-4 mm)."""
    values, _ = state_values(target, e0 or {}, e0)
    want = captured_values(target)
    return values is not None and values.keys() == want.keys() and all(
        abs(values[k] - v) <= POINT_TOLERANCE_MM for k, v in want.items())


def readable(found, e0):
    """Tokens of the covered sketches whose every record the first read gives back as the capture has it
    (within 1e-4 mm), and the key prefixes of the faces that read back so. A sketch that fails is not followed: the
    sizes that change it are loose. A sweep path that fails does not count: only the path is left unfollowed
    (`matches_capture`), not the outlines drawn in its sketch. A face that fails is written as the capture has it."""
    bad = {t["sketch_token"] for t in found.targets if t["kind"] != "path" and not matches_capture(t, e0)}
    return {t for t in list(found.covered) + list(found.faces) if t not in bad}


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
    """(frame numbers, outline curves sorted by their sketch curve token, path curves sorted by kind and numbers) of
    a sketch read."""
    frame = []
    _all_numbers(record.get("frame"), frame)
    curves = []
    for profile in record.get("profiles") or []:
        for loop in profile.get("loops") or []:
            for curve in loop.get("curves") or []:
                numbers = []
                _all_numbers({k: v for k, v in curve.items() if k not in ("entity", "kind", "type")}, numbers)
                curves.append((str(curve.get("entity") or ""), str(curve.get("kind") or ""), numbers))
    path = []
    for curve in (record.get("curves") or {}).values():
        if not isinstance(curve, dict):
            continue
        numbers = []
        _all_numbers({k: v for k, v in curve.items() if k not in ("entity", "kind", "type")}, numbers)
        path.append((str(curve.get("kind") or ""), numbers))
    return frame, sorted(curves), sorted(path)


def _close(a, b):
    return len(a) == len(b) and all(abs(x - y) <= POINT_TOLERANCE_MM for x, y in zip(a, b))


def same_read(before, now):
    """True when two reads of one sketch (`{ frame, profiles, curves }`) have the same frame and curves, within 1e-4 mm.
    An outline curve Fusion made again under a new token counts as the same curve (`renamed`); path curves are
    compared by their numbers."""
    frame_a, curves_a, path_a = _read_signature(before)
    frame_b, curves_b, path_b = _read_signature(renamed(now, before))
    return (_close(frame_a, frame_b) and len(curves_a) == len(curves_b) and all(
        a[:2] == b[:2] and _close(a[2], b[2]) for a, b in zip(curves_a, curves_b))
        and len(path_a) == len(path_b) and all(a[0] == b[0] and _close(a[1], b[1]) for a, b in zip(path_a, path_b)))
