"""Compute the box and volume of the target body of each capture fixture, from the capture itself.

Run from the add-in root (needs numpy; the add-in and its tests do not):
    python3 scripts/fixture_geometry.py            list fixtures whose stored values differ
    python3 scripts/fixture_geometry.py --write    write the computed values into the fixtures
    python3 scripts/fixture_geometry.py name ...   limit to the named fixtures

The model is a voxel count of extrudes, revolves, holes, combines, patterns and mirrors, read straight from the
capture data (not from the translated recipe). Boxes are exact to half a voxel (0.1 mm), volumes within about
0.5 percent. Fillets, chamfers, shells, modeled threads, tapers, thin walls, face profiles and unreadable fields
are not modelled: the box stays, `volume_mm3` becomes null. The same box rule fills each item's
`target_box_before`.
"""
import glob
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "captures")
STEP = 0.2
BIG = 1000.0
ARC_POINTS = 64


class Unmodelled(Exception):
    """The capture holds something this script does not model; the volume is left null."""


# ---------------------------------------------------------------- shapes


class Shape:
    """A solid as a point test plus a box that surely contains it."""

    def __init__(self, test, lo, hi):
        self.test = test
        self.lo = np.asarray(lo, float)
        self.hi = np.asarray(hi, float)

    def union(self, other):
        return Shape(lambda p: self.test(p) | other.test(p),
                     np.minimum(self.lo, other.lo), np.maximum(self.hi, other.hi))

    def cut(self, other):
        return Shape(lambda p: self.test(p) & ~other.test(p), self.lo, self.hi)

    def intersect(self, other):
        lo, hi = np.maximum(self.lo, other.lo), np.minimum(self.hi, other.hi)
        return Shape(lambda p: self.test(p) & other.test(p), lo, np.maximum(lo, hi))

    def moved(self, rot, shift):
        """Rigid move p -> rot p + shift."""
        rot, shift = np.asarray(rot, float), np.asarray(shift, float)
        corners = np.array([[x, y, z] for x in (self.lo[0], self.hi[0]) for y in (self.lo[1], self.hi[1])
                            for z in (self.lo[2], self.hi[2])]) @ rot.T + shift
        return Shape(lambda p: self.test((p - shift) @ rot), corners.min(axis=0), corners.max(axis=0))

    def reflected(self, point, normal):
        n = np.asarray(normal, float) / np.linalg.norm(normal)
        point = np.asarray(point, float)
        flip = lambda p: p - 2.0 * ((p - point) @ n)[..., None] * n  # noqa: E731
        corners = flip(np.array([[x, y, z] for x in (self.lo[0], self.hi[0]) for y in (self.lo[1], self.hi[1])
                                 for z in (self.lo[2], self.hi[2])]))
        return Shape(lambda p: self.test(flip(p)), corners.min(axis=0), corners.max(axis=0))


def grid_of(shape, step):
    lo = np.floor(shape.lo / step) * step
    hi = np.ceil(shape.hi / step) * step
    axes = [np.arange(lo[i] + step / 2, hi[i], step) for i in range(3)]
    return axes


def measure(shape, step=STEP, need_volume=True):
    """(box, volume) of the shape from a voxel count. Box edges are the occupied voxel faces."""
    axes = grid_of(shape, step)
    if any(len(a) == 0 for a in axes):
        return None, 0.0
    gx, gy, gz = np.meshgrid(*axes, indexing="ij")
    pts = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)
    inside = np.zeros(len(pts), bool)
    chunk = 2_000_000
    for start in range(0, len(pts), chunk):
        inside[start:start + chunk] = shape.test(pts[start:start + chunk])
    if not inside.any():
        return None, 0.0
    occupied = pts[inside]
    box = {"min": [round(float(v - step / 2), 6) + 0.0 for v in occupied.min(axis=0)],
           "max": [round(float(v + step / 2), 6) + 0.0 for v in occupied.max(axis=0)]}
    return box, float(inside.sum()) * step ** 3


# ---------------------------------------------------------------- profiles


def _arc_points(c):
    cx, cy = c["center"]
    r = c["radius"]
    a0 = math.atan2(c["start"][1] - cy, c["start"][0] - cx)
    a1 = math.atan2(c["end"][1] - cy, c["end"][0] - cx)
    am = math.atan2(c["mid"][1] - cy, c["mid"][0] - cx)
    sweep = (a1 - a0) % (2 * math.pi)
    if ((am - a0) % (2 * math.pi)) > sweep:
        sweep -= 2 * math.pi
    return [[cx + r * math.cos(a0 + sweep * i / ARC_POINTS), cy + r * math.sin(a0 + sweep * i / ARC_POINTS)]
            for i in range(ARC_POINTS + 1)]


def _polyline(c):
    if c["kind"] == "line":
        return [list(c["start"]), list(c["end"])]
    if c["kind"] == "arc":
        return _arc_points(c)
    if c["kind"] == "other" and c.get("samples"):
        return [list(p) for p in c["samples"]]
    raise Unmodelled("curve " + c["kind"])


def _chain(curves):
    pieces = [_polyline(c) for c in curves]
    chain = pieces.pop(0)
    while pieces:
        end = chain[-1]
        for i, piece in enumerate(pieces):
            if math.dist(piece[0], end) < 1e-3:
                chain += piece[1:]
            elif math.dist(piece[-1], end) < 1e-3:
                chain += piece[::-1][1:]
            else:
                continue
            pieces.pop(i)
            break
        else:
            raise Unmodelled("open outline")
    return np.array(chain)


def _inside_polygon(u, v, poly):
    inside = np.zeros(len(u), bool)
    x0, y0 = poly[:-1, 0], poly[:-1, 1]
    x1, y1 = poly[1:, 0], poly[1:, 1]
    for ax, ay, bx, by in zip(x0, y0, x1, y1):
        if ay == by:
            continue
        crosses = ((ay > v) != (by > v)) & (u < (bx - ax) * (v - ay) / (by - ay) + ax)
        inside ^= crosses
    return inside


def profile_test(profile):
    """Function (u, v) -> bool for one profile: even odd over all its loops. Also returns 2D bounds."""
    if profile.get("face") or "loops" not in profile:
        raise Unmodelled("face profile")
    parts = []
    pts = []
    for loop in profile["loops"]:
        curves = loop["curves"]
        if len(curves) == 1 and curves[0]["kind"] == "circle":
            c = curves[0]
            parts.append(("circle", c["center"], c["radius"]))
            pts += [[c["center"][0] + sx * c["radius"], c["center"][1] + sy * c["radius"]]
                    for sx in (-1, 1) for sy in (-1, 1)]
        elif len(curves) == 1 and curves[0]["kind"] == "ellipse":
            raise Unmodelled("ellipse")
        else:
            poly = _chain(curves)
            parts.append(("poly", poly))
            pts += poly.tolist()

    def test(u, v):
        out = np.zeros(len(u), bool)
        for part in parts:
            if part[0] == "circle":
                out ^= (u - part[1][0]) ** 2 + (v - part[1][1]) ** 2 < part[2] ** 2
            else:
                out ^= _inside_polygon(u, v, part[1])
        return out

    return test, np.array(pts)


def frame_of(frame):
    rot = np.array([frame["x"], frame["y"], frame["z"]], float).T
    return np.asarray(frame["origin"], float), rot


# ---------------------------------------------------------------- features


class Lenient:
    """Set while a feature the script cannot model exactly is read for its box only; the volume then turns null."""
    used = False


def _bend(reason):
    """Raise Unmodelled, or note it and carry on when the box is still wanted."""
    if not Lenient.on:
        raise Unmodelled(reason)
    Lenient.used = True


Lenient.on = False


def extrude_intervals(data, origin, rot):
    """Intervals of the sketch normal coordinate the extrude covers."""
    z = rot[:, 2]
    start = data.get("start") or {"kind": "profilePlane"}
    shift = 0.0
    if start["kind"] == "offset":
        shift = start["offset"]
    elif start["kind"] == "fromEntity" and start.get("plane"):
        shift = float(np.dot(np.asarray(start["plane"]["point"]) - origin, z))
    elif start["kind"] != "profilePlane":
        _bend("start")

    def side(extent, sign):
        if extent["kind"] == "distance":
            if extent.get("taper_deg") not in (0, 0.0):
                _bend("taper")
            return sorted([shift, shift + sign * abs(extent["distance"])])
        if extent["kind"] == "throughAll":
            return [shift, BIG] if extent["positive"] else [-BIG, shift]
        if extent["kind"] == "toEntity":
            plane = extent.get("plane")
            if not plane or abs(abs(float(np.dot(plane["normal"], z))) - 1) > 1e-9:
                _bend("tilted end")
                return [shift, shift + 10.0]
            end = float(np.dot(np.asarray(plane["point"]) - origin, z)) + (extent.get("offset") or 0.0)
            return sorted([shift, end])
        raise Unmodelled("extent " + extent["kind"])

    kind = data.get("extent_type")
    if data.get("thin") is not False:
        _bend("thin")
    if kind == "one":
        one = data["side_one"]
        end = data.get("end_offset")
        if one["kind"] == "distance":
            sign = (1 if end >= 0 else -1) if end is not None else (1 if one["distance"] >= 0 else -1)
            return [side(one, sign)]
        return [side(one, 1)]
    if kind == "two":
        one, two = data["side_one"], data["side_two"]
        return [side(one, 1), side(two, -1)]
    if kind == "symmetric":
        sym = data["symmetric"]
        if sym.get("taper_deg") not in (0, 0.0) or sym.get("full_length") is None:
            _bend("symmetric")
        half = sym["distance"] / 2.0 if sym.get("full_length") else sym["distance"]
        return [[shift - half, shift + half]]
    raise Unmodelled("extent type")


def extrude_shape(data):
    profiles = data["profiles"]
    if not profiles:
        raise Unmodelled("no profile")
    pieces = []
    for profile in profiles:
        test2d, pts2d = profile_test(profile)
        origin, rot = frame_of(profile["frame"])
        intervals = extrude_intervals(data, origin, rot)
        lo_w = min(i[0] for i in intervals)
        hi_w = max(i[1] for i in intervals)

        def test(p, test2d=test2d, origin=origin, rot=rot, intervals=intervals):
            local = (p - origin) @ rot
            hit = np.zeros(len(p), bool)
            for a, b in intervals:
                hit |= (local[:, 2] >= a) & (local[:, 2] <= b)
            idx = np.nonzero(hit)[0]
            out = np.zeros(len(p), bool)
            if len(idx):
                out[idx] = test2d(local[idx, 0], local[idx, 1])
            return out

        local_corners = np.array([[x, y, w] for x, y in (pts2d.min(axis=0), pts2d.max(axis=0), (pts2d[:, 0].min(), pts2d[:, 1].max()),
                                                         (pts2d[:, 0].max(), pts2d[:, 1].min())) for w in (lo_w, hi_w)])
        world = local_corners @ rot.T + origin
        pieces.append(Shape(test, world.min(axis=0), world.max(axis=0)))
    shape = pieces[0]
    for other in pieces[1:]:
        shape = shape.union(other)
    return shape


def revolve_shape(data):
    ext = data["extent"]
    if ext["kind"] not in ("angle", "twoSidesAngle"):
        raise Unmodelled("revolve extent")
    if data["profiles"][0].get("face") or len(data["profiles"]) != 1:
        raise Unmodelled("revolve profiles")
    profile = data["profiles"][0]
    test2d, pts2d = profile_test(profile)
    origin, rot = frame_of(profile["frame"])
    axis_point = np.asarray(data["axis"]["point"], float)
    axis_dir = np.asarray(data["axis"]["dir"], float)
    axis_dir /= np.linalg.norm(axis_dir)
    mid3 = origin + (rot[:, :2] @ pts2d.mean(axis=0))
    to_mid = mid3 - axis_point
    e = to_mid - np.dot(to_mid, axis_dir) * axis_dir
    e /= np.linalg.norm(e)
    side = np.cross(axis_dir, e)
    normal = data.get("start_face_normal")
    turn = 1.0
    if normal is not None and np.dot(-np.asarray(normal, float), side) < 0:
        turn = -1.0
    if ext["kind"] == "angle":
        a = math.radians(ext["angle_deg"])
        window = (-a / 2, a / 2) if ext.get("symmetric") else ((0.0, a) if turn > 0 else (-a, 0.0))
    else:
        window = (-math.radians(ext["angle_two_deg"]), math.radians(ext["angle_one_deg"]))
        if turn < 0:
            window = (-window[1], -window[0])
    full = ext["kind"] == "angle" and ext["angle_deg"] >= 360

    def test(p):
        rel = p - axis_point
        along = rel @ axis_dir
        radial = rel - along[:, None] * axis_dir
        rho = np.linalg.norm(radial, axis=1)
        theta = np.arctan2(radial @ side, radial @ e)
        ok = np.ones(len(p), bool) if full else ((theta >= window[0]) & (theta <= window[1]))
        idx = np.nonzero(ok & (rho > 0))[0]
        out = np.zeros(len(p), bool)
        if len(idx):
            on_plane = axis_point + along[idx, None] * axis_dir + rho[idx, None] * e
            local = (on_plane - origin) @ rot
            out[idx] = test2d(local[:, 0], local[:, 1])
        return out

    reach = 0.0
    spans = []
    for pt in pts2d:
        p3 = origin + rot[:, :2] @ pt
        rel = p3 - axis_point
        spans.append(rel @ axis_dir)
        reach = max(reach, float(np.linalg.norm(rel - (rel @ axis_dir) * axis_dir)))
    lo_a, hi_a = min(spans), max(spans)
    ends = [axis_point + lo_a * axis_dir, axis_point + hi_a * axis_dir]
    lo = np.min(ends, axis=0) - reach
    hi = np.max(ends, axis=0) + reach
    return Shape(test, lo, hi)


def cylinder(origin, axis, radius, a, b):
    """Cylinder along `axis` from distance a to b past `origin`."""
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    origin = np.asarray(origin, float)

    def test(p):
        rel = p - origin
        along = rel @ axis
        radial = rel - along[:, None] * axis
        return (along >= a) & (along <= b) & ((radial ** 2).sum(axis=1) <= radius ** 2)

    ends = [origin + a * axis, origin + b * axis]
    return Shape(test, np.min(ends, axis=0) - radius, np.max(ends, axis=0) + radius)


def cone(origin, axis, r0, r1, a, b):
    """Cone along `axis`, radius r0 at distance a and r1 at distance b."""
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    origin = np.asarray(origin, float)

    def test(p):
        rel = p - origin
        along = rel @ axis
        radial = rel - along[:, None] * axis
        t = (along - a) / (b - a)
        r = r0 + (r1 - r0) * t
        return (t >= 0) & (t <= 1) & ((radial ** 2).sum(axis=1) <= r ** 2)

    ends = [origin + a * axis, origin + b * axis]
    reach = max(r0, r1)
    return Shape(test, np.min(ends, axis=0) - reach, np.max(ends, axis=0) + reach)


def hole_shape(data):
    if data.get("tap_type") == "tapped" and data.get("thread_modeled"):
        raise Unmodelled("modeled thread")
    if data["extent"]["kind"] not in ("distance", "throughAll"):
        raise Unmodelled("hole extent")
    cylinders = data.get("side_cylinders") or []
    axis = np.asarray(cylinders[0]["axis"] if cylinders else data["direction"], float)
    radius = data["diameter"] / 2.0
    if cylinders and data.get("tap_type") == "tapped":
        radius = max(c["radius"] for c in cylinders if c["radius"] <= data["diameter"] / 2.0 + 1e-9) \
            if data.get("hole_type") == "simple" else radius
    through = data["extent"]["kind"] == "throughAll"
    depth = BIG if through else data["extent"]["depth"]
    shape = None
    for position in data["positions"]:
        parts = []
        if not through:
            tip = data.get("tip_angle_deg") or 180
            parts.append(cylinder(position, axis, radius, -0.05, depth))
            if tip < 180:
                height = radius / math.tan(math.radians(tip) / 2.0)
                parts.append(cone(position, axis, radius, 0.0, depth, depth + height))
        else:
            parts.append(cylinder(position, axis, radius, -0.05, depth))
        kind = data.get("hole_type")
        if kind == "counterbore" and data.get("counterbore"):
            cb = data["counterbore"]
            parts.append(cylinder(position, axis, cb["diameter"] / 2.0, -0.05, cb["depth"]))
        elif kind == "countersink" and data.get("countersink"):
            cs = data["countersink"]
            rs = cs["diameter"] / 2.0
            depth_cs = (rs - radius) / math.tan(math.radians(cs["angle_deg"]) / 2.0)
            parts.append(cone(position, axis, rs, radius, 0.0, depth_cs))
        one = parts[0]
        for extra in parts[1:]:
            one = one.union(extra)
        shape = one if shape is None else shape.union(one)
    return shape


# ---------------------------------------------------------------- the walk


def frame_move(frame):
    origin, rot = frame_of(frame)
    return rot, origin


def apply_op(body, op, shape):
    if body is None:
        if op in ("newBody", "join"):
            return shape
        return None
    if op in ("newBody", "join", "add"):
        return body.union(shape)
    if op == "cut":
        return body.cut(shape)
    if op == "intersect":
        return body.intersect(shape)
    raise Unmodelled("operation " + str(op))


def body_key(item, data, target):
    bodies = item.get("bodies_after") or data.get("participants") or []
    if bodies:
        return bodies[0].get("token") or bodies[0].get("name")
    return target.get("token") or target.get("name")


def evaluate(capture):
    """(box or None, volume or None, {item index: box before}) for the target body of a capture."""
    target = capture["target"]
    key_of = lambda ref: ref.get("token") or ref.get("name")  # noqa: E731
    bodies = {}
    features = {}
    exact = True
    before = {}
    Lenient.on = True
    Lenient.used = False
    for item in capture["items"]:
        outside = item.get("in_target_component") is False
        if item.get("suppressed") or outside or item["type"] in ("Sketch", "none"):
            continue
        data = item.get("data") or {}
        kind = item["type"]
        try:
            if "read_error" in data:
                raise Unmodelled("read error")
            if kind == "ExtrudeFeature":
                op = data["operation"]
                if op == "newComponent":
                    Lenient.used = True
                    op = "newBody"
                shape = extrude_shape(data)
                key = body_key(item, data, target)
                if data.get("target_box_before") is not None and bodies.get(key) is not None:
                    before[item["index"]] = measure(bodies[key], 0.5)[0]
                bodies[key] = apply_op(bodies.get(key), op, shape)
                features[item["index"]] = (key, op, shape)
            elif kind == "RevolveFeature":
                shape = revolve_shape(data)
                key = body_key(item, data, target)
                bodies[key] = apply_op(bodies.get(key), data["operation"], shape)
                features[item["index"]] = (key, data["operation"], shape)
            elif kind == "HoleFeature":
                shape = hole_shape(data)
                key = body_key(item, data, target)
                bodies[key] = apply_op(bodies.get(key), "cut", shape)
                features[item["index"]] = (key, "cut", shape)
            elif kind == "CombineFeature":
                tkey = key_of(data["target"])
                for tool in data["tools"]:
                    shape = bodies.get(key_of(tool))
                    if shape is not None and bodies.get(tkey) is not None:
                        bodies[tkey] = apply_op(bodies[tkey], {"join": "join", "cut": "cut", "intersect": "intersect"}[data["operation"]], shape)
                    if not data.get("keep_tools"):
                        bodies.pop(key_of(tool), None)
            elif kind in ("RectangularPatternFeature", "CircularPatternFeature"):
                if data.get("entity_type") != "features" or data.get("symmetric") or data.get("symmetric_one"):
                    raise Unmodelled("pattern kind")
                skipped = set(data.get("suppressed_ids") or [])
                for src in data["sources"]:
                    if src not in features:
                        raise Unmodelled("pattern source")
                    key, op, shape = features[src]
                    for el in data["elements"][1:]:
                        if el.get("suppressed") or el["id"] in skipped:
                            continue
                        rot, shift = frame_move(el["frame"])
                        bodies[key] = apply_op(bodies[key], op, shape.moved(rot, shift))
            elif kind == "MirrorFeature":
                plane = data["plane"]
                if data.get("entity_type") == "bodies":
                    key = key_of(item["bodies_after"][0]) if item.get("bodies_after") else key_of(target)
                    if data.get("target_box_before") is not None and bodies.get(key) is not None:
                        before[item["index"]] = measure(bodies[key], 0.5)[0]
                    bodies[key] = bodies[key].union(bodies[key].reflected(plane["point"], plane["normal"]))
                elif data.get("entity_type") == "features":
                    for src in data["sources"]:
                        key, op, shape = features[src]
                        if data.get("target_box_before") is not None and bodies.get(key) is not None:
                            before[item["index"]] = measure(bodies[key], 0.5)[0]
                        bodies[key] = apply_op(bodies[key], op, shape.reflected(plane["point"], plane["normal"]))
                else:
                    raise Unmodelled("mirror kind")
            elif kind == "ThreadFeature":
                if data.get("modeled"):
                    raise Unmodelled("modeled thread")
            elif kind in ("FilletFeature", "ChamferFeature", "ShellFeature"):
                exact = False
            else:
                raise Unmodelled(kind)
        except (Unmodelled, KeyError, IndexError, TypeError, ValueError):
            exact = False
    final = bodies.get(key_of(target))
    if final is None:
        raise Unmodelled("no target")
    box, volume = measure(final)
    return box, (round(volume, 1) if exact and not Lenient.used else None), before


def fixture_files(names):
    paths = sorted(glob.glob(os.path.join(FIXTURES, "*.json")))
    if names:
        paths = [p for p in paths if os.path.splitext(os.path.basename(p))[0] in names]
    return paths


def main(argv):
    write = "--write" in argv
    names = [a for a in argv if not a.startswith("--")]
    changed = 0
    for path in fixture_files(names):
        with open(path, encoding="utf-8") as f:
            capture = json.load(f)
        if not isinstance(capture, dict) or "items" not in capture or "target" not in capture:
            continue
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            box, volume, before = evaluate(capture)
        except Unmodelled as exc:
            print("%s: not modelled (%s)" % (name, exc))
            if name.startswith("core_") or capture["target"].get("volume_mm3") is None:
                continue
            box, volume, before = None, None, {}
        old = (capture["target"].get("box"), capture["target"].get("volume_mm3"))
        capture["target"]["box"] = box if box is not None else capture["target"].get("box")
        capture["target"]["volume_mm3"] = volume
        for item in capture["items"]:
            if item["index"] in before and before[item["index"]] is not None:
                item["data"]["target_box_before"] = before[item["index"]]
        new = (capture["target"]["box"], capture["target"]["volume_mm3"])
        if old != new:
            changed += 1
            print("%s: box %s volume %s -> box %s volume %s" % (name, old[0], old[1], new[0], new[1]))
            if write:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(capture, f, indent=2)
                    f.write("\n")
    print("%d fixture(s) %s" % (changed, "written" if write else "differ"))


if __name__ == "__main__":
    main(sys.argv[1:])
