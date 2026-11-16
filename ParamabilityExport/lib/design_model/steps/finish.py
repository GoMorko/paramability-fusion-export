"""Round and chamfer steps (FilletFeature, ChamferFeature) as facts: what each set of edges asks for, in numbers.

A step holds one or more sets. A set has the edges Fusion picked (records with measured points), a kind and its
sizes. This module reads a set and says only what is known about it; each destination decides what to copy, which
reason to give and how to name the edges.

- `RoundSet`: the kind (`CONSTANT`, `VARIABLE`, `CHORD_LENGTH`, `ASYMMETRIC`, or anything else Fusion has), the radius
  and the smoothness of the join; for a chord length set the chord, for a changing radius the radii at the two ends
  and the number of radii set between them.
- `face_angle`, `chord_radius`, `matches_radius`, `law`: what the samples of an edge (`samples` of the edge records)
  show. The angle between the edge's two faces, the radius a chord length gives at that angle, whether the radius
  measured on the round matches a radius, and how a changing radius runs along the edge.
- `ChamferSet`: the kind (`EQUAL`, `TWO_DISTANCES`, `DISTANCE_ANGLE`), the first distance and the second measure
  (`second` when the two sides differ, `held` when it is a second way to write an even chamfer), and `problem` when
  a value cannot be read. `sides` splits the edges of an uneven chamfer by the face that takes the first distance,
  measured on the edges (`sides` and `cut_normals` of the edge records).
- `Part`, `merge`: the edges of a step grouped into parts of one size (and one side, one second measure), so a step
  with sets of different sizes is a list of steps of one size each.
- `reach`: how far from its edge a set takes material along a face.

A size that follows the sizes of the design is a `Quantity` (`design_model.values`). The destination makes it: each
set gives `size(quantity)` the number and the path of its parameter, and `quantity(path, number, dim)` gives back the
`Quantity`.
Pure: it reads capture dicts only.
"""
import math

from ...geometry import vec
from ...package.numbers import is_number

CONSTANT, VARIABLE, CHORD_LENGTH, ASYMMETRIC = "constant", "variable", "chordLength", "asymmetric"
EQUAL, TWO_DISTANCES, DISTANCE_ANGLE = "equal", "twoDistances", "distanceAngle"
# What a chamfer set that cannot be read lacks: its size, its angle, or a kind that is not known.
NO_SIZE, NO_ANGLE, UNKNOWN_KIND = "size", "angle", "kind"
# The kinds of `Measure`: a second distance, or the angle of the cut.
DISTANCE, ANGLE = "distance", "angle"

SIZE_TOL = 1e-9
ANGLE_TOL = 1e-6
EVEN_ANGLE_DEG = 45.0
# A chamfer by distance and angle reaches along the second face by distance * tan(angle); it is measured only below
# this angle (degrees).
REACH_ANGLE_DEG = 89.0
# The chamfer face normal is a mix of the two face normals, weighted by the two distances. It must be that mix within
# SPAN_TOL, and its weights must be within RATIO_SHARE of the distance ratio (in log scale) to name the face.
SPAN_TOL = 0.05
RATIO_SHARE = 0.5
# Of the two faces at each edge, the one that takes the first distance must lean this much more towards the
# direction that names it.
SIZE_ON_MARGIN = 0.1


_UNMEASURED = object()


def _positive(value):
    return is_number(value) and value > 0


def _close(a, b, tol=SIZE_TOL):
    return abs(a - b) <= tol


def point_count(edges):
    """The number of measured points of `edges`."""
    return sum(len(edge.get("points") or []) for edge in edges)


class FinishSet:
    """One set of a round or chamfer step as the capture holds it.

    index: the place of the set in the step (it names the set's parameters, `path`). kind: the kind Fusion gave.
    edges: the edge records. entry: the capture dict itself, for the picks that read the faces or tangent chains Fusion
    was given.
    """

    def __init__(self, index, entry):
        self.index = index
        self.entry = entry if isinstance(entry, dict) else {}
        self.kind = self.entry.get("kind")
        self.edges = list(self.entry.get("edges") or [])

    def path(self, field):
        """The key of a parameter of this set in the item's `params`."""
        return "sets.%d.%s" % (self.index, field)

    @property
    def follows_step(self):
        """True when Fusion was given the edges of another step."""
        return "feature" in (self.entry.get("input_kinds") or [])

    @property
    def unlocated(self):
        """True when an edge has no measured point."""
        return any(not edge.get("points") for edge in self.edges)

    @property
    def foreign(self):
        """True when an edge is on another component."""
        return any(edge.get("foreign") for edge in self.edges)


class RoundSet(FinishSet):
    """A set of a round. radius: the radius when it is a positive number, else None. continuity: how the round joins
    its faces as read ("tangent", "curvature", "other"), or None. chord: the chord length of a `CHORD_LENGTH` set.
    start, end: the radii at the start and end of the edge of a `VARIABLE` set. mid_count: how many more radii a
    `VARIABLE` set gives between them. Each is None when it is not a positive number (a count: a whole number)."""

    def __init__(self, index, entry):
        super().__init__(index, entry)
        radius = self.entry.get("radius")
        self.radius = radius if _positive(radius) else None
        self.continuity = self.entry.get("continuity")
        chord = self.entry.get("chord_length") if self.kind == CHORD_LENGTH else None
        self.chord = chord if _positive(chord) else None
        start, end = (self.entry.get("start_radius"), self.entry.get("end_radius")) if self.kind == VARIABLE \
            else (None, None)
        self.start = start if _positive(start) else None
        self.end = end if _positive(end) else None
        count = self.entry.get("mid_count")
        self.mid_count = count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else None

    def size(self, quantity):
        """The radius as a `Quantity`."""
        return quantity(self.path("radius"), self.radius, "length")

    def chord_size(self, quantity):
        """The chord length as a `Quantity`."""
        return quantity(self.path("chord_length"), self.chord, "length")

    def end_sizes(self, quantity):
        """The radii at the start and at the end of the edge as `Quantity`s."""
        return (quantity(self.path("start_radius"), self.start, "length"),
                quantity(self.path("end_radius"), self.end, "length"))

    @property
    def reach(self):
        """How far (mm) the round reaches along a face from its edge, or None when that is not known."""
        if self.kind == CONSTANT and self.continuity != "curvature":
            return self.radius
        return None


class Measure:
    """The second value of a chamfer: `kind` is `DISTANCE` or `ANGLE`, `number` its value (mm or degrees), `path`
    the key of its parameter and `dim` its unit kind ("length" or "angle")."""

    def __init__(self, kind, path, number):
        self.kind, self.path, self.number = kind, path, number
        self.dim = "angle" if kind == ANGLE else "length"

    def size(self, quantity):
        return quantity(self.path, self.number, self.dim)


class ChamferSet(FinishSet):
    """A set of a chamfer.

    distance: the first distance when it is a positive number, else None. other: the second distance of
    `TWO_DISTANCES` and angle: the angle of `DISTANCE_ANGLE` (between 0 and 90 degrees), else None.
    even: True when both sides of the cut have the same size: two equal distances, or a distance and 45 degrees.
    """

    def __init__(self, index, entry):
        super().__init__(index, entry)
        distance = self.entry.get("distance")
        self.distance = distance if _positive(distance) else None
        other = self.entry.get("distance_two") if self.kind == TWO_DISTANCES else None
        self.other = other if _positive(other) else None
        angle = self.entry.get("angle_deg") if self.kind == DISTANCE_ANGLE else None
        self.angle = angle if is_number(angle) and 0 < angle < 90 else None
        self._sides = _UNMEASURED

    @property
    def problem(self):
        """What a value of the set lacks (`NO_SIZE`, `NO_ANGLE`, `UNKNOWN_KIND`), or None when it can be read."""
        if self.kind == TWO_DISTANCES and self.other is None:
            return NO_SIZE
        if self.kind == DISTANCE_ANGLE and self.angle is None:
            return NO_ANGLE
        if self.kind not in (EQUAL, TWO_DISTANCES, DISTANCE_ANGLE):
            return UNKNOWN_KIND
        return NO_SIZE if self.distance is None else None

    @property
    def even(self):
        if self.distance is None:
            return False
        if self.kind == EQUAL:
            return True
        if self.kind == TWO_DISTANCES:
            return self.other is not None and _close(self.distance, self.other)
        if self.kind == DISTANCE_ANGLE:
            return self.angle is not None and _close(self.angle, EVEN_ANGLE_DEG, ANGLE_TOL)
        return False

    def _measure(self):
        if self.kind == TWO_DISTANCES and self.other is not None:
            return Measure(DISTANCE, self.path("distance_two"), self.other)
        if self.kind == DISTANCE_ANGLE and self.angle is not None:
            return Measure(ANGLE, self.path("angle_deg"), self.angle)
        return None

    @property
    def second(self):
        """The second `Measure` of an uneven chamfer that can be read, else None."""
        return None if self.problem or self.even else self._measure()

    @property
    def held(self):
        """The second `Measure` of a chamfer that is even only while that value stays so, else None."""
        return self._measure() if not self.problem and self.even else None

    def size(self, quantity):
        """The first distance as a `Quantity`."""
        return quantity(self.path("distance"), self.distance, "length")

    @property
    def ratio(self):
        """The first distance over the second on a square edge, or None for an even chamfer or one not readable."""
        measure = self.second
        if measure is None:
            return None
        if measure.kind == DISTANCE:
            return self.distance / measure.number
        return 1.0 / math.tan(math.radians(measure.number))

    @property
    def reach(self):
        """The largest distance (mm) the chamfer reaches along a face from its edge, or None when not known."""
        if self.distance is None:
            return None
        if self.kind == EQUAL:
            return float(self.distance)
        if self.kind == TWO_DISTANCES and self.other is not None:
            return float(max(self.distance, self.other))
        if self.kind == DISTANCE_ANGLE and self.angle is not None and self.angle < REACH_ANGLE_DEG:
            return float(max(self.distance, self.distance * math.tan(math.radians(self.angle))))
        return None

    def sides(self):
        """The edges as [(direction, edges)]: one part with direction None for an even chamfer, else the edges split
        by the face that takes the first distance, each with the direction that names that face (`sizeOn`). None when
        the chamfer is uneven and the face of an edge was not measured or cannot be told."""
        if self.problem:
            return None
        if self.even:
            return [(None, list(self.edges))]
        if self._sides is _UNMEASURED:
            self._sides = _uneven_groups(self.edges, self.ratio)
        return self._sides


# ---- rounds measured along their edges ----------------------------------------------------------------------

# How far (degrees) the angle between the two faces of an edge may change along it.
FACE_ANGLE_TOL = 0.05
# The angle between the faces (degrees) a round by chord length needs: near 0 the faces run on into each other, near
# 180 they fold back on each other.
FACE_ANGLE_RANGE = (1.0, 179.0)
# How far a measured radius may be from the radius it should have: mm, plus a share of that radius.
RADIUS_TOL = 0.01
RADIUS_SHARE = 0.002
# How a changing radius runs along an edge (`law`): from the start radius at the edge's first sample, from the end
# radius there, or the same at both ends (the two radii are equal, so the measured radii cannot tell).
FROM_START, FROM_END, LEVEL = "fromStart", "fromEnd", "level"


def samples(edge):
    """The samples of an edge record that can be read: {at, point, tangent, ...} in order along the edge."""
    found = edge.get("samples")
    if not isinstance(found, list):
        return []
    return [s for s in found if isinstance(s, dict) and is_number(s.get("at")) and isinstance(s.get("point"), list)]


def _angle_between(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, vec.dot(vec.unit(a), vec.unit(b))))))


def face_angle(edge):
    """The angle (degrees) between the outward normals of the edge's two faces when it is the same at every sample
    (within FACE_ANGLE_TOL), else None. Also None when a sample has no two normals."""
    found = samples(edge)
    angles = []
    for sample in found:
        sides = sample.get("sides")
        if not isinstance(sides, list) or len(sides) != 2 or not all(
                isinstance(n, list) and len(n) == 3 and vec.length(n) > 0 for n in sides):
            return None
        angles.append(_angle_between(*sides))
    if not angles or max(angles) - min(angles) > FACE_ANGLE_TOL:
        return None
    return sum(angles) / len(angles)


def chord_radius(chord, angle):
    """The radius of a round whose chord is `chord` (mm) between faces whose normals are `angle` degrees apart; None
    outside FACE_ANGLE_RANGE."""
    if not FACE_ANGLE_RANGE[0] <= angle <= FACE_ANGLE_RANGE[1]:
        return None
    return chord / (2.0 * math.sin(math.radians(angle) / 2.0))


def _near(measured, wanted):
    return is_number(measured) and abs(measured - wanted) <= RADIUS_TOL + RADIUS_SHARE * abs(wanted)


def matches_radius(edge, radius_at, ends=True):
    """True when the radius measured at every sample of the edge is `radius_at(at)` within the tolerance. `ends`
    False skips the samples at the two ends of the edge, where the round may meet another round of the step. False
    when no sample is checked."""
    checked = [s for s in samples(edge) if ends or 0.0 < s["at"] < 1.0]
    return bool(checked) and all(_near(s.get("radius"), radius_at(s["at"])) for s in checked)


def law(edge, start, end):
    """How a radius that changes from `start` to `end` runs along the edge, read from the radius measured at each of
    its samples (at 0, 1/4, 1/2, 3/4 and 1): `FROM_START` when it changes evenly from `start` at the first sample to
    `end` at the last, `FROM_END` the other way round, `LEVEL` when both fit (the radii are equal), None when neither
    fits (it changes some other way, or a sample is missing)."""
    found = samples(edge)
    if [s["at"] for s in found] != [0.0, 0.25, 0.5, 0.75, 1.0]:
        return None
    forward = matches_radius(edge, lambda at: start + (end - start) * at)
    backward = matches_radius(edge, lambda at: end + (start - end) * at)
    if forward and backward:
        return LEVEL
    return FROM_START if forward else FROM_END if backward else None


def round_sets(data):
    """The `RoundSet`s of the data of a fillet step."""
    return [RoundSet(n, entry) for n, entry in enumerate(data.get("sets") or [])]


def chamfer_sets(data):
    """The `ChamferSet`s of the data of a chamfer step."""
    return [ChamferSet(n, entry) for n, entry in enumerate(data.get("sets") or [])]


def edges_of(sets):
    """Every edge of `sets`, in order."""
    return [edge for one in sets for edge in one.edges]


# ---- edges of one size ----------------------------------------------------------------------------------------

class Part:
    """Edges that share one size, one side and one second measure. size: a `Quantity`. direction: the direction that
    names the face of the first distance, or None. extra: second measures as {kind: Quantity}. sets: the sets the
    edges come from."""

    def __init__(self, size, direction, extra, edges, sets=()):
        self.size, self.direction, self.extra = size, direction, dict(extra)
        self.edges, self.sets = list(edges), list(sets)

    def matches(self, other):
        return (self.size.same_as(other.size) and self.direction == other.direction
                and self.extra.keys() == other.extra.keys()
                and all(self.extra[k].same_as(other.extra[k]) for k in self.extra))


def merge(parts):
    """`parts` with those of one size, side and second measure joined, in order of first appearance; a part with no
    edge is dropped. A step whose parts are many is a list of steps of one size each."""
    found = []
    for part in parts:
        for held in found:
            if held.matches(part):
                held.edges += part.edges
                held.sets += part.sets
                break
        else:
            found.append(Part(part.size, part.direction, part.extra, part.edges, part.sets))
    return [part for part in found if part.edges]


# ---- the face that takes the first distance -------------------------------------------------------------------

def _first_face(sides, cut, ratio):
    """The outward normals (first, other) at one edge point: `first` is the face that takes the first distance.
    None when the chamfer face does not tell.

    `sides` are the normals of the edge's two faces, `cut` the normal of the chamfer face there, `ratio` the first
    distance over the second. The chamfer face normal is a * A + b * B with a / b the ratio of the distances on A and B.
    """
    a_n, b_n = [vec.unit(v) for v in sides]
    g = vec.dot(a_n, b_n)
    if abs(1.0 - g * g) < 1e-9:
        return None
    c = vec.unit(cut)
    ca, cb = vec.dot(c, a_n), vec.dot(c, b_n)
    a, b = (ca - g * cb) / (1 - g * g), (cb - g * ca) / (1 - g * g)
    if a <= 0 or b <= 0 or vec.length(vec.sub(c, vec.add(vec.scale(a_n, a), vec.scale(b_n, b)))) > SPAN_TOL:
        return None
    measured, wanted = math.log(a / b), math.log(ratio)
    if abs(measured - wanted) <= RATIO_SHARE * abs(wanted):
        return a_n, b_n
    if abs(measured + wanted) <= RATIO_SHARE * abs(wanted):
        return b_n, a_n
    return None


def _edge_leans(edge, ratio):
    """One (first - other) normal difference per point of an uneven chamfer edge, or None when not measured."""
    sides, cuts = edge.get("sides"), edge.get("cut_normals")
    points = edge.get("points") or []
    if not isinstance(sides, list) or not isinstance(cuts, list) or len(sides) != len(points) or len(cuts) != len(points):
        return None
    leans = []
    for pair, cut in zip(sides, cuts):
        if not isinstance(pair, list) or len(pair) != 2 or cut is None:
            return None
        found = _first_face(pair, cut, ratio)
        if found is None:
            return None
        leans.append(vec.sub(found[0], found[1]))
    return leans


def _size_on(leans):
    """The direction that picks the first face at every point, or None when one direction cannot do it."""
    total = [0.0, 0.0, 0.0]
    for lean in leans:
        total = vec.add(total, lean)
    if vec.length(total) < 1e-9:
        return None
    direction = vec.unit(total)
    if any(vec.dot(lean, direction) < SIZE_ON_MARGIN for lean in leans):
        return None
    return [round(c, 9) + 0.0 for c in direction]


def _uneven_groups(edges, ratio):
    """Edges of an uneven chamfer split into [(direction, edges)], or None when the face of an edge cannot be told."""
    groups = []
    for edge in edges:
        leans = _edge_leans(edge, ratio)
        if leans is None:
            return None
        for group in groups:
            direction = _size_on(group["leans"] + leans)
            if direction is not None:
                group.update(direction=direction, leans=group["leans"] + leans)
                group["edges"].append(edge)
                break
        else:
            direction = _size_on(leans)
            if direction is None:
                return None
            groups.append({"direction": direction, "leans": leans, "edges": [edge]})
    return [(g["direction"], g["edges"]) for g in groups]
