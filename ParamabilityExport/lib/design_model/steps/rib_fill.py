"""A rib To Next that Fusion fills up to the part (a gusset in a corner), as the closed outline Fusion made. Pure.

A rib with To Next grows across its sketch plane from its line until it meets the part. When the part closes in on
the line, as the base and the back wall of a bracket close in on a line across their corner, Fusion fills the whole
region between the line and the part. That wall is not a band of one depth along the line, so `rib_web.walls` gives
NEXT_SHAPE (or NEXT_LINE for a chain of several lines). The copy then writes the region as Fusion made it: a closed
outline of straight edges in the sketch frame, extruded by the thickness from the sketch plane, centred on it or to
one side (`as_extrude`).

`fill` proves the outline from what Fusion measured, for each way the thickness may run (`thin.spans`):

- The ends. Of the faces Fusion made (`wall_faces`), exactly one faces along the sketch normal and one against it, at
  the two ends of the span. Their corners give the same points in the sketch frame: the corners of the outline.
- The outline. Its edges are the lines of the rib and edges on the flat faces of the part before the step
  (`target_faces_before`) that stand square to the sketch plane. On each such face, the corners that lie on its plane
  join in their order along it. Every corner must join exactly two others, in one closed loop that does not cross
  itself, and each edge on the part must lie on a face of the part that faces into the outline.
- The sides. Every other face Fusion made stands square to the sketch plane, runs from one end of the wall to the
  other, lies along one edge of the outline and faces out of it. Each line of the rib has such a face.
- The volume. The part grew by the area of the outline times the thickness (within the tolerance of `rib_web`), so
  the wall met the part only on its faces.

Exactly one way must agree; else the step keeps the problem `rib_web.walls` gave.

Nothing of the outline follows sizes: the line, the faces of the part and the corners stay as Fusion measured them,
and each size read before the step is marked (`marks`). The thickness follows its parameter: the edges on the part lie
on faces square to the sketch plane, so a thicker rib fills the same outline while those faces reach that far.
"""
from ...geometry import vec
from ...package.numbers import is_number
from .. import words
from ..problem import is_problem
from . import rib_web, thin

# The problems of `rib_web.walls` after which the faces may show a filled outline.
FILLABLE = (rib_web.NEXT_SHAPE.code, rib_web.NEXT_LINE.code)
# A corner lies on a plane or matches another within this (mm).
TOL = rib_web.TOL
# Outlines of more corners are not tried.
MAX_CORNERS = 64


class Fill:
    """The filled wall of a rib: the closed outline `points` (2D, counter clockwise in the frame of `line`, the rib's
    `thin.Line`) extruded `length` along the sketch normal from the sketch plane, one `way` (+1 or -1) or centred on
    it (way 0)."""

    def __init__(self, line, points, way, length):
        self.line, self.points, self.way, self.length = line, points, way, length

    @property
    def symmetric(self):
        return self.way == 0


def _height(frame, point):
    return vec.dot(vec.sub(point, frame["origin"]), vec.unit(frame["z"]))


def _uv(frame, point):
    return vec.frame_to_local(frame, point)[:2]


def _near(a, b):
    return abs(a[0] - b[0]) <= TOL and abs(a[1] - b[1]) <= TOL


def _distinct(points):
    out = []
    for p in points:
        if not any(_near(p, q) for q in out):
            out.append(p)
    return out


def _index(points, p):
    found = [n for n, q in enumerate(points) if _near(p, q)]
    return found[0] if len(found) == 1 else None


def _faces(data):
    """The faces Fusion made, each with its corners, or None."""
    faces = data.get("wall_faces")
    if not isinstance(faces, list) or not faces:
        return None
    for face in faces:
        corners = face.get("vertices") if isinstance(face, dict) else None
        if not thin.flat_face(face) or not isinstance(corners, list) or not corners or not all(
                isinstance(p, list) and len(p) == 3 and all(is_number(c) for c in p) for p in corners):
            return None
    return faces


def _sorted_faces(faces, frame, span):
    """(low end, high end, sides) of the faces Fusion made for a wall over `span` along the sketch normal, or None
    when they are not the two ends of a prism and its square sides."""
    z = vec.unit(frame["z"])
    ends, sides = {}, []
    for face in faces:
        along = vec.dot(vec.unit(face["normal"]), z)
        heights = [_height(frame, p) for p in face["vertices"]]
        if abs(abs(along) - 1.0) <= thin.NORMAL_TOL:
            key = 1 if along > 0 else 0
            if key in ends or any(abs(h - span[key]) > TOL for h in heights):
                return None
            ends[key] = face
        elif abs(along) <= thin.NORMAL_TOL:
            if any(min(abs(h - span[0]), abs(h - span[1])) > TOL for h in heights):
                return None
            sides.append(face)
        else:
            return None
    if len(ends) != 2:
        return None
    return ends[0], ends[1], sides


def _part_edges(points, frame, before):
    """{(n, m): [unit outward normal of a face of the part, in the sketch frame]}: the edges between corners that lie
    on a flat face of the part square to the sketch plane, joined in their order along it."""
    z = vec.unit(frame["z"])
    out = {}
    for face in before:
        if not thin.flat_face(face):
            continue
        normal = vec.unit(face["normal"])
        if abs(vec.dot(normal, z)) > thin.NORMAL_TOL:
            continue
        on = [n for n, p in enumerate(points)
              if abs(vec.dot(vec.sub(vec.frame_apply(frame, p + [0.0]), face["point"]), normal)) <= TOL]
        flat = [vec.dot(normal, frame["x"]), vec.dot(normal, frame["y"])]
        along = [-flat[1], flat[0]]
        on.sort(key=lambda n: points[n][0] * along[0] + points[n][1] * along[1])
        for n, m in zip(on, on[1:]):
            out.setdefault(tuple(sorted((n, m))), []).append(flat)
    return out


def _loop(count, edges):
    """The corner numbers in the order of the one closed loop that `edges` make through all `count` corners, or
    None."""
    links = {n: [] for n in range(count)}
    for n, m in edges:
        links[n].append(m)
        links[m].append(n)
    if count < 3 or any(len(found) != 2 for found in links.values()):
        return None
    order = [0, links[0][0]]
    while len(order) < count:
        a, b = links[order[-1]]
        step = b if a == order[-2] else a
        if step == order[0]:
            return None
        order.append(step)
    return order if order[0] in links[order[-1]] else None


def _signed_area(points):
    return 0.5 * sum(points[n - 1][0] * points[n][1] - points[n][0] * points[n - 1][1] for n in range(len(points)))


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _meet(a, b, c, d):
    """True when the segments ab and cd share a point (touching counts)."""
    d1, d2, d3, d4 = _cross(c, d, a), _cross(c, d, b), _cross(a, b, c), _cross(a, b, d)
    if ((d1 > TOL and d2 < -TOL) or (d1 < -TOL and d2 > TOL)) and ((d3 > TOL and d4 < -TOL) or
                                                                    (d3 < -TOL and d4 > TOL)):
        return True

    def on(p, q, r, side):
        return abs(side) <= TOL and min(p[0], q[0]) - TOL <= r[0] <= max(p[0], q[0]) + TOL and \
            min(p[1], q[1]) - TOL <= r[1] <= max(p[1], q[1]) + TOL
    return on(c, d, a, d1) or on(c, d, b, d2) or on(a, b, c, d3) or on(a, b, d, d4)


def _simple(points):
    """True when no two edges of the closed outline that do not follow each other meet."""
    count = len(points)
    for n in range(count):
        for m in range(n + 2, count):
            if n == 0 and m == count - 1:
                continue
            if _meet(points[n], points[(n + 1) % count], points[m], points[(m + 1) % count]):
                return False
    return True


def _inward(points, n):
    """The unit normal of edge n (corner n to corner n + 1) of a counter clockwise outline, into the outline."""
    a, b = points[n], points[(n + 1) % len(points)]
    d = [b[0] - a[0], b[1] - a[1]]
    size = (d[0] ** 2 + d[1] ** 2) ** 0.5
    return [-d[1] / size, d[0] / size]


def _outline(data, line, faces, before, span):
    """The counter clockwise corners of the outline Fusion filled over `span`, or None when the faces, the part and
    the volume do not prove it."""
    frame = line.frame
    found = _sorted_faces(faces, frame, span)
    if found is None:
        return None
    low, high, sides = found
    points = _distinct([_uv(frame, p) for p in high["vertices"]])
    other = _distinct([_uv(frame, p) for p in low["vertices"]])
    if not 3 <= len(points) <= MAX_CORNERS or len(other) != len(points) or not all(
            _index(points, p) is not None for p in other):
        return None
    chain = []
    for a, b in zip(line.points, line.points[1:]):
        n, m = _index(points, a), _index(points, b)
        if n is None or m is None or n == m:
            return None
        chain.append(tuple(sorted((n, m))))
    part = _part_edges(points, frame, before)
    order = _loop(len(points), set(chain) | set(part))
    if order is None:
        return None
    outline = [points[n] for n in order]
    if _signed_area(outline) < 0:
        order, outline = order[::-1], outline[::-1]
    if not _simple(outline):
        return None
    count = len(order)
    edge_of = {tuple(sorted((order[k], order[(k + 1) % count]))): k for k in range(count)}
    for pair, normals in part.items():
        if pair in chain or pair not in edge_of:
            continue
        inward = _inward(outline, edge_of[pair])
        if not any(n[0] * inward[0] + n[1] * inward[1] > 0.5 for n in normals):
            return None
    covered = set()
    for face in sides:
        ends = _distinct([_uv(frame, p) for p in face["vertices"]])
        heights = [_height(frame, p) for p in face["vertices"]]
        pair = tuple(sorted(_index(points, p) for p in ends)) if len(ends) == 2 and all(
            _index(points, p) is not None for p in ends) else None
        if pair not in edge_of or min(heights) > span[0] + TOL or max(heights) < span[1] - TOL:
            return None
        normal = vec.unit(face["normal"])
        inward = _inward(outline, edge_of[pair])
        if vec.dot(normal, frame["x"]) * inward[0] + vec.dot(normal, frame["y"]) * inward[1] > -0.5:
            return None
        covered.add(pair)
    if not set(chain) <= covered:
        return None
    expected = _signed_area(outline) * (span[1] - span[0])
    change = data["volume_after"] - data["volume_before"]
    if abs(change - expected) > rib_web.VOLUME_RELATIVE_TOL * expected + rib_web.VOLUME_ABSOLUTE_TOL:
        return None
    return outline


def fill(data, before, problem):
    """The `Fill` of a rib To Next that Fusion filled up to the part, or `problem` (what `rib_web.walls` gave) when
    the problem is not one a filled outline answers or the faces Fusion made do not prove one. `before` holds the
    faces of the part before the step when they are faces of the body the copy builds, else None."""
    if not is_problem(problem) or problem.code not in FILLABLE or not before:
        return problem
    if rib_web.settings_problem(data) is not None or data["kind"] != rib_web.RIB or data["extent"] != rib_web.TO_NEXT:
        return problem
    lines = rib_web.lines_of(data)
    faces = _faces(data)
    if is_problem(lines) or len(lines) != 1 or faces is None:
        return problem
    if not is_number(data.get("volume_before")) or not is_number(data.get("volume_after")):
        return problem
    found = []
    for way, span in thin.spans(data["thickness"], data["symmetric"]):
        outline = _outline(data, lines[0], faces, before, span)
        if outline is not None:
            found.append(Fill(lines[0], outline, way, span[1] - span[0]))
    return found[0] if len(found) == 1 else problem


def length_path(found):
    """The value path of the extrude `as_extrude` writes that holds the thickness."""
    return "symmetric.distance" if found.symmetric else "side_one.distance"


def as_extrude(data, found):
    """The data of the extrude that builds `found`: its outline in the rib's sketch frame, joined, extruded from the
    sketch plane by the thickness, one way or centred. The outline is `measured`: it keeps its numbers in both
    outputs. The thickness parameter goes to the extrude's distance."""
    line, points = found.line, found.points
    curves = [{"kind": "line", "start": list(points[n - 1]), "end": list(points[n])} for n in range(len(points))]
    profile = {"sketch": line.sketch, "frame": line.frame, "space": "sketch", "measured": True,
               "reference": line.path.get("reference"), "loops": [{"outer": True, "curves": curves}]}
    area = _signed_area(points)
    built = {
        "operation": "join",
        "profiles": [profile],
        "start": {"kind": "profilePlane"},
        "extent_type": "symmetric" if found.symmetric else "one",
        "side_one": None if found.symmetric else {"kind": "distance", "distance": found.length, "taper_deg": 0.0,
                                                  "direction": found.way},
        "side_two": None,
        "symmetric": {"distance": found.length, "full_length": True, "taper_deg": 0.0} if found.symmetric else None,
        "thin": False,
        "participants": data.get("participants") or [],
        "target_box_before": data.get("target_box_before"),
        "end_offset": None if found.symmetric else found.way * found.length,
        "profile_area": area,
        "end_area": area,
    }
    held = (data.get("params") or {}).get("thickness")
    if held is not None:
        built["params"] = {length_path(found): held}
    return built


def marks(name):
    """[(value paths, why)]: every size read before the step is marked, since the outline keeps the numbers Fusion
    measured, and so is the thickness, since the faces the wall rests on were measured at one thickness only."""
    return [((), words.RIB_FILL_MARK % name), (("thickness",), words.RIB_FILL_THICKNESS_MARK % name)]
