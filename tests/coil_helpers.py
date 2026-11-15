"""Captures of coils built from numbers: the geometry the reader measures for a coil, worked out exactly.

`coil_data` gives the `data` of a CoilFeature item (parameters, volumes, end faces and sampled helical edges) for a
helix about the vertical axis through `origin`; `coil_capture` puts it after a 40 x 20 x 10 block. Tests edit the
result to break one thing at a time.
"""
import copy
import math

from tests.translator_helpers import load_capture

BLOCK_VOLUME = 8000.0
FRAME_X = [1.0, 0.0, 0.0]


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _frame(origin, x, z):
    return {"origin": list(origin), "x": list(x), "y": _cross(z, x), "z": list(z)}


def _local(frame, p):
    d = _sub(p, frame["origin"])
    return [_dot(d, frame["x"]), _dot(d, frame["y"])]


def _section(shape, size):
    """The wire as (r, h) points about its centre, and its area."""
    if shape == "circle":
        return None, math.pi * (size / 2.0) ** 2
    if shape == "square":
        half = size / 2.0
        return [(-half, -half), (half, -half), (half, half), (-half, half)], size * size
    return [(-size / 2.0, -size / 3.0), (size / 2.0, -size / 3.0), (0.0, 2.0 * size / 3.0)], size * size / 2.0


def _helix_point(origin, radius, height, angle, rise, hand):
    sign = 1.0 if hand == "right" else -1.0
    t = sign * angle
    return [origin[0] + radius * math.cos(t), origin[1] + radius * math.sin(t), origin[2] + height + rise]


def _loops(shape, frame, size, centre3, corners3):
    """The section of an end face as loops in the face's own coordinates."""
    if shape == "circle":
        c = _local(frame, centre3)
        return [{"outer": True, "curves": [{"kind": "circle", "center": c, "radius": size / 2.0}]}]
    pts = [_local(frame, p) for p in corners3]
    return [{"outer": True, "curves": [{"kind": "line", "start": pts[n], "end": pts[(n + 1) % len(pts)]}
                                       for n in range(len(pts))]}]


def coil_data(shape="circle", diameter=10.0, size=2.0, turns=3.0, pitch=4.0, hand="right", place=-1.0,
              origin=(20.0, 10.0, 14.0), kind="revolutions_height", operation="join", height_is="rise"):
    """The `data` of a coil. `place` is where the wire sits against the diameter: -1 inside, 0 on, 1 outside."""
    rho = diameter / 2.0 + place * size / 2.0
    rise = pitch * turns
    corners, area = _section(shape, size)
    offsets = corners if corners else [(size / 2.0, 0.0)]
    sign = 1.0 if hand == "right" else -1.0
    axis = [0.0, 0.0, 1.0]
    frames, caps = [], []
    for angle, lift in ((0.0, 0.0), (2.0 * math.pi * turns, rise)):
        radial = [math.cos(sign * angle), math.sin(sign * angle), 0.0]
        travel = _cross(axis, radial) if hand == "right" else [-v for v in _cross(axis, radial)]
        z = [-v for v in travel] if angle == 0.0 else travel
        frame = _frame([origin[0], origin[1], origin[2] + lift], radial, z)
        centre = [origin[0] + rho * radial[0], origin[1] + rho * radial[1], origin[2] + lift]
        corner3 = [[origin[0] + (rho + r) * radial[0], origin[1] + (rho + r) * radial[1], origin[2] + lift + h]
                   for r, h in (corners or [])]
        flat = {"frame": frame, "loops": _loops(shape, frame, size, centre, corner3), "area": area}
        frames.append(frame)
        caps.append((flat, centre, corner3))
    edges = []
    for r, h in offsets:
        points = [_helix_point(origin, rho + r, h, 2.0 * math.pi * turns * i / 16.0, pitch * turns * i / 16.0, hand)
                  for i in range(17)]
        edges.append(points)
    for flat, centre, corner3 in caps:
        ring = corner3 or [[centre[0] + (size / 2.0) * math.cos(a) * flat["frame"]["x"][0],
                            centre[1] + (size / 2.0) * math.cos(a) * flat["frame"]["x"][1],
                            centre[2] + (size / 2.0) * math.sin(a)] for a in
                           [2 * math.pi * i / 16 for i in range(17)]]
        edges.append(ring)
    volume = 2.0 * math.pi * turns * area * rho
    params = {
        "diameter": {"name": "d5", "expression": "%s mm" % diameter, "value": diameter},
        "section_size": {"name": "d6", "expression": "%s mm" % size, "value": size},
        "taper_deg": {"name": "d7", "expression": "0 deg", "value": 0.0},
    }
    if kind in ("revolutions_height", "revolutions_pitch"):
        params["revolutions"] = {"name": "d8", "expression": str(turns), "value": turns}
    if kind in ("revolutions_height", "height_pitch"):
        params["height"] = {"name": "d9", "expression": "%s mm" % rise, "value": rise}
    if kind in ("revolutions_pitch", "height_pitch"):
        params["pitch"] = {"name": "d10", "expression": "%s mm" % pitch, "value": pitch}
    block = [{"token": "t1", "name": "Body1", "volume": BLOCK_VOLUME}]
    if operation == "newBody":
        made = [{"token": "c1", "name": "Body2", "volume": volume}]
    elif operation == "join":
        made = [{"token": "t1", "name": "Body1", "volume": BLOCK_VOLUME + volume}]
    else:
        made = [{"token": "t1", "name": "Body1", "volume": BLOCK_VOLUME - volume}]
    return {
        "roles": ["Diameter", "SectionSize", "TaperAngle", "Revolutions", "Height"],
        "volumes_before": block,
        "made": made,
        "faces": {"flat": [c[0] for c in caps], "curved": len(offsets), "edges": edges},
        "params": params,
    }


def coil_capture(**kwargs):
    """A block, then a coil joined to it (or cut from it). The coil is item 2."""
    capture = load_capture("extrude_plate")
    data = coil_data(**kwargs)
    capture["items"].append({
        "index": 2, "name": "Coil1", "type": "CoilFeature", "suppressed": False, "health": "ok", "message": "",
        "in_target_component": True, "bodies_before": [{"token": "t1", "name": "Body1"}],
        "bodies_after": [{"token": "t1", "name": "Body1"}], "target_changed": True, "data": data})
    return capture


def edit_coil(capture, edit):
    """`capture` with `edit(data)` applied to the coil's data."""
    capture = copy.deepcopy(capture)
    edit(capture["items"][2]["data"])
    return capture


def _user(name, expression, value, unit="mm"):
    kind = "count" if not unit else "length"
    return {"name": name, "expression": expression, "value": value / 10.0 if unit else value, "unit": unit,
            "comment": "", "is_favorite": True, "value_type": "numeric", "dependency_parameters": [],
            "dependent_parameters": [], "kind": kind, "display_value": value}


def _model(param, role, user):
    return {"name": param["name"], "expression": param["expression"], "value": param["value"] / 10.0, "unit": "mm",
            "kind": "derived", "role": role, "dependency_parameters": [user],
            "created_by": {"kind": "feature", "token": "tok_" + param["name"], "name": "Coil1", "sketch": "",
                           "component": ""}}


def with_sizes(capture, diameter="coil_d", size="coil_s", turns="coil_n", height="coil_h", pitch="coil_p"):
    """The coil's parameters read user parameters: its diameter, section size, revolutions, height and pitch. The
    section size is a quarter of the diameter; the height is the pitch times the turns."""
    data = capture["items"][2]["data"]
    params = data["params"]
    d, s = params["diameter"]["value"], params["section_size"]["value"]
    users = [_user(diameter, "%s mm" % d, d), _user(size, "%s mm" % s, s)]
    expression = {"diameter": diameter, "section_size": size}
    if "revolutions" in params:
        users.append(_user(turns, str(params["revolutions"]["value"]), params["revolutions"]["value"], ""))
        expression["revolutions"] = turns
    if "height" in params:
        users.append(_user(height, "%s mm" % params["height"]["value"], params["height"]["value"]))
        expression["height"] = height
    if "pitch" in params:
        users.append(_user(pitch, "%s mm" % params["pitch"]["value"], params["pitch"]["value"]))
        expression["pitch"] = pitch
    models = []
    for path, user in expression.items():
        params[path]["expression"] = user
        models.append(_model(params[path], path, user))
    capture["parameters"] = {"user": users, "model": models}
    return capture
