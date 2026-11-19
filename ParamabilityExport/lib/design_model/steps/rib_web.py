"""Ribs and webs as facts: the walls Fusion builds along their open sketch lines, from the settings and from what
Fusion measured. Pure.

Both are walls of one thickness along open chains of straight sketch lines (`thin.line_of`):

- A rib takes one chain. Its wall lies in the sketch plane: it runs across the plane from the line, `depth` wide (To
  Next: until it meets the part), and is `thickness` thick along the sketch normal, centred on the sketch plane
  (`symmetric`) or on one side of it.
- A web takes one or more chains. Its wall is `thickness` wide in the sketch plane, centred on each line or on one
  side of it, and runs `depth` along the sketch normal (To Next: until it meets the part).

So each chain gives the wall of a thin extrude of an open line (`thin.py`): a band along the line, `width` wide on one
side of it or centred on it, that runs along the sketch normal over a span. For a rib the width is the depth and the
span is the thickness; for a web the width is the thickness and the span is the depth.

The API gives no side or direction for `isFlipped` or for a thickness on one side, so the measured faces decide them
(`walls`). Each candidate (side of the line, way along the normal) is checked against the faces the feature made
(`wall_faces`): each face lies on a face of the wall or is a face of the wall that Fusion merged with a face of the
part (`thin.fits`), and every corner of every face lies on the wall, so Fusion did not stretch a line or add other
material. Exactly one candidate must fit.

Fusion stops the wall where it meets the part, also for a depth set as a distance: a wall that runs into the part
and out of it again ends where it met the part, not at its depth. So a wall is copied only when it is the whole band:
the part's volume grew by the volume of the band (`_whole_band`), so the band met the part only on its faces. To Next
stores no depth. The depth is then as far as the corners reach, and the far end must also lie on a flat face of the
part that faces the wall. A rib that reaches to the part takes one straight line, so that its far end is one face
along the line.

At other sizes a longer or moved wall may run into the part, where Fusion stops it and the copy does not, and a size
that moves the part may move it into the wall or away from it. `Wall.clear` says the wall's own sizes cannot run it
into the part: the band and all of the room it grows into lie outside the box of the part before the step
(`target_box_before`). `Wall.stands` says the wall starts on the face of the part its sketch is drawn on, so that face
moves the sketch with it. `marks` marks the sizes read before the step unless the wall is clear and stands, and the
wall's own depth (and a web's thickness) unless it is clear.
"""
from ...capture_model import gap_hints
from ...geometry import vec
from ...geometry.convex_union import union_area
from ...geometry.footprint import Footprint
from ...package.numbers import is_number
from .. import words
from ..problem import Problem, is_problem
from . import thin

RIB, WEB = "rib", "web"
TO_NEXT, DISTANCE = "toNext", "distance"

UNREADABLE = Problem("unreadable", words.RIB_UNREADABLE, gap_hints.RIB_WEB)
DRAFT = Problem("draft", words.RIB_DRAFT, gap_hints.RIB_WEB)
FILLET = Problem("fillet", words.RIB_FILLET, gap_hints.RIB_WEB)
EXTENT = Problem("extent", words.RIB_EXTENT, gap_hints.RIB_WEB)
LINES = Problem("lines", words.RIB_LINES, gap_hints.RIB_WEB)
CURVES = Problem("curves", words.RIB_CURVES, gap_hints.RIB_WEB)
OPPOSED = Problem("opposed", words.RIB_OPPOSED, gap_hints.RIB_WEB)
UNMEASURED = Problem("unmeasured", words.RIB_UNMEASURED, gap_hints.RIB_WEB)
NOT_MATCHING = Problem("not_matching", words.RIB_NOT_MATCHING, gap_hints.RIB_WEB)
UNSURE = Problem("unsure", words.RIB_UNSURE, gap_hints.RIB_WEB)
NEXT_SHAPE = Problem("next_shape", words.RIB_NEXT_SHAPE, gap_hints.RIB_WEB)
NEXT_LINE = Problem("next_line", words.RIB_NEXT_LINE, gap_hints.RIB_WEB)
MEETS_PART = Problem("meets_part", words.RIB_MEETS_PART, gap_hints.RIB_WEB)
EXTENDED = Problem("extended", words.RIB_EXTENDED, gap_hints.RIB_WEB)
BODY_UNMEASURED = Problem("body_unmeasured", words.RIB_BODY_UNMEASURED, gap_hints.RIB_WEB)
FLUSH = Problem("flush", words.RIB_FLUSH, gap_hints.RIB_WEB)

# The shared line problems of `thin.line_of`, in the words of a rib or web.
_LINE_PROBLEMS = {thin.LINE_CURVES.code: CURVES, thin.LINE_OPPOSED.code: OPPOSED}

# A corner lies on the wall within this (mm); the wall is at least this deep.
TOL = 1e-3
# The part's volume grew by the wall's volume within this share of it plus this (mm3).
VOLUME_RELATIVE_TOL = 1e-4
VOLUME_ABSOLUTE_TOL = 1e-2
# How far (mm) the room a wall grows into is followed past its far end.
GROWTH_MM = 1e5
# The sketch-frame location `thin.line_side` reads for each side, so a thin extrude of the wall finds the same side.
LOCATION_OF = {"inside": "side1", "outside": "side2", "middle": "center"}


def _positive(value):
    return is_number(value) and value > 0


def settings_problem(data):
    """The Problem of a setting that keeps a rib or web from being copied, or None."""
    if data.get("kind") not in (RIB, WEB) or data.get("symmetric") is None or data.get("flipped") is None:
        return UNREADABLE
    if not _positive(data.get("thickness")):
        return UNREADABLE
    if data.get("extent") not in (TO_NEXT, DISTANCE):
        return EXTENT
    if data["extent"] == DISTANCE and not _positive(data.get("depth")):
        return UNREADABLE
    if data.get("kind") == WEB and data.get("extended") is None:
        return UNREADABLE
    for key, problem in (("draft_deg", DRAFT), ("fillet", FILLET)):
        if not is_number(data.get(key)):
            return UNREADABLE
        if data[key]:
            return problem
    return None


def chains_of(data):
    """The path records of the chains of a rib or web: `path` for one chain, `paths` for several. None when they
    could not be read."""
    if isinstance(data.get("path"), dict):
        return [data["path"]]
    paths = data.get("paths")
    if isinstance(paths, list) and paths and all(isinstance(p, dict) for p in paths):
        return paths
    return None


def lines_of(data):
    """The `thin.Line` of each chain, or a Problem: open chains of straight lines of one sketch that run one after
    the other, one chain for a rib."""
    chains = chains_of(data)
    if chains is None or (data.get("kind") == RIB and len(chains) != 1):
        return LINES
    lines = []
    for chain in chains:
        line = thin.line_of({"path": chain})
        if is_problem(line):
            return _LINE_PROBLEMS.get(line.code, LINES)
        lines.append(line)
    if len({line.path.get("sketch_token") or line.sketch for line in lines}) != 1:
        return LINES
    return lines


class Wall:
    """The wall along one `thin.Line`: a band on `side` of the line (`inside`, `outside` or `middle`, in the line's
    own sketch frame) `width` wide, that runs `length` along the sketch normal from the sketch plane, one `way` (+1
    or -1) or centred on the plane (way 0). `measured` is True when the depth is the one measured for To Next.
    `clear` is True when a longer wall cannot meet the part, and `stands` True when the wall stands on the face of
    the part its sketch is drawn on (see the module text)."""

    def __init__(self, line, side, width, way, length, measured, clear=False, stands=False):
        self.line, self.side, self.width, self.way, self.length = line, side, width, way, length
        self.measured, self.clear, self.stands = measured, clear, stands

    @property
    def symmetric(self):
        return self.way == 0


class _Candidate:
    def __init__(self, side, width, way, span):
        self.side, self.width, self.way, self.span = side, width, way, span


def _corners(faces):
    """Every corner of every face, or None when a face's corners were not read."""
    out = []
    for face in faces:
        corners = face.get("vertices") if isinstance(face, dict) else None
        if not isinstance(corners, list) or not all(isinstance(p, list) and len(p) == 3 for p in corners):
            return None
        out += corners
    return out


def _height(frame, point):
    return vec.dot(vec.sub(point, frame["origin"]), vec.unit(frame["z"]))


def _rib_widths(line, corners):
    """[(side, width)]: for a rib that reaches to the part, how far the corners reach across the plane from its one
    straight line, on each side that holds them all."""
    a, b = line.points
    d = vec.unit([b[0] - a[0], b[1] - a[1], 0.0])
    out = []
    for side, normal in (("inside", [-d[1], d[0]]), ("outside", [d[1], -d[0]])):
        across = [(uv[0] - a[0]) * normal[0] + (uv[1] - a[1]) * normal[1]
                  for uv in (vec.frame_to_local(line.frame, p)[:2] for p in corners)]
        if min(across) >= -TOL and max(across) > TOL:
            out.append((side, max(across)))
    return out


def _web_spans(frame, corners):
    """[(way, span)]: for a web that reaches to the part, how far the corners reach along the sketch normal, on each
    side of the sketch plane that holds them all."""
    heights = [_height(frame, p) for p in corners]
    out = []
    if max(heights) <= TOL and min(heights) < -TOL:
        out.append((-1, (min(heights), 0.0)))
    if min(heights) >= -TOL and max(heights) > TOL:
        out.append((1, (0.0, max(heights))))
    return out


def _candidates(data, lines, corners):
    """The walls Fusion may have built: each side, width and way its settings allow."""
    thickness, symmetric = data["thickness"], data["symmetric"]
    if data["kind"] == RIB:
        spans = thin.spans(thickness, symmetric)
        if data["extent"] == DISTANCE:
            widths = [(side, data["depth"]) for side in ("inside", "outside")]
        elif len(lines[0].points) != 2:
            return NEXT_LINE
        else:
            widths = _rib_widths(lines[0], corners)
        return [_Candidate(side, width, way, span) for side, width in widths for way, span in spans]
    sides = ("middle",) if symmetric else ("inside", "outside")
    if data["extent"] == DISTANCE:
        spans = thin.spans(data["depth"], False)
    else:
        spans = _web_spans(lines[0].frame, corners)
    return [_Candidate(side, thickness, way, span) for side in sides for way, span in spans]


def _footprints(lines, candidate):
    return [Footprint(thin.band_profile(line.frame, thin.band(line.points, *thin.reaches(candidate.side,
                                                                                        candidate.width))))
            for line in lines]


def _on_some_wall(footprints, face, frame, span, before):
    start = frame["origin"]
    if any(thin.on_wall(f, face, frame, start, span) for f in footprints):
        return True
    return any(thin.merged(f, face, frame, start, span, before) for f in footprints)


def _corner_on_wall(footprints, frame, span, point):
    h = _height(frame, point)
    if not span[0] - TOL <= h <= span[1] + TOL:
        return False
    uv = vec.frame_to_local(frame, point)[:2]
    return any(f.covers(uv) or f.nearest_curve(uv)[1] <= TOL for f in footprints)


def _fits(lines, candidate, faces, before, merged_corners=True):
    """True when the faces Fusion made fit the walls of `candidate` along all lines: each face flat and on a wall or
    merged with the part, at least one face on each wall, and every corner on a wall. Without `merged_corners`, the
    corners of a face that lies off every wall (a face Fusion merged with the part) are not checked."""
    frame = lines[0].frame
    start = frame["origin"]
    footprints = _footprints(lines, candidate)
    if not all(thin.flat_face(face) for face in faces):
        return False
    if not all(_on_some_wall(footprints, face, frame, candidate.span, before) for face in faces):
        return False
    if not all(any(thin.on_wall(f, face, frame, start, candidate.span) for face in faces) for f in footprints):
        return False
    checked = faces if merged_corners else [
        face for face in faces if any(thin.on_wall(f, face, frame, start, candidate.span) for f in footprints)]
    return all(_corner_on_wall(footprints, frame, candidate.span, p) for p in _corners(checked))


def _wall_area(lines, candidate):
    pieces = [piece for line in lines
              for piece in thin.band_pieces(line.points, *thin.reaches(candidate.side, candidate.width))]
    return union_area(pieces)


def _far_face(lines, candidate, kind):
    """(point, unit normal) of the plane the far end of a To Next wall lies on, the normal facing back to the
    wall."""
    frame = lines[0].frame
    z = vec.unit(frame["z"])
    if kind == WEB:
        far = candidate.span[0] if candidate.way < 0 else candidate.span[1]
        return vec.add(frame["origin"], vec.scale(z, far)), vec.scale(z, -float(candidate.way))
    a, b = lines[0].points
    d = vec.unit([b[0] - a[0], b[1] - a[1], 0.0])
    across = [-d[1], d[0]] if candidate.side == "inside" else [d[1], -d[0]]
    point = vec.frame_apply(frame, [a[0] + across[0] * candidate.width, a[1] + across[1] * candidate.width, 0.0])
    normal = [-(across[0] * frame["x"][i] + across[1] * frame["y"][i]) for i in range(3)]
    return point, vec.unit(normal)


def _ends_on_part(lines, candidate, kind, before):
    point, normal = _far_face(lines, candidate, kind)
    for face in before or []:
        if not thin.flat_face(face):
            continue
        if (vec.dot(vec.unit(face["normal"]), normal) >= 1.0 - thin.NORMAL_TOL
                and abs(vec.dot(vec.sub(face["point"], point), normal)) <= TOL):
            return True
    return False


def _whole_band(data, lines, candidate):
    """True when the part grew by the whole wall of `candidate`: the band met the part only on its faces."""
    before_volume, after_volume = data.get("volume_before"), data.get("volume_after")
    area = _wall_area(lines, candidate)
    if not is_number(before_volume) or not is_number(after_volume) or area is None:
        return False
    expected = area * (candidate.span[1] - candidate.span[0])
    return abs(after_volume - before_volume - expected) <= VOLUME_RELATIVE_TOL * expected + VOLUME_ABSOLUTE_TOL


def _growth_points(lines, candidate, kind):
    """The 3D corners of the walls of `candidate` and of the room they grow into as the depth grows: along the sketch
    normal for a web, across the plane away from each line for a rib."""
    low, high = candidate.span
    if kind == WEB:
        low, high = (low - GROWTH_MM, high) if candidate.way < 0 else (low, high + GROWTH_MM)
    left, right = thin.reaches(candidate.side, candidate.width)
    out = []
    for line in lines:
        for k, piece in enumerate(thin.band_pieces(line.points, left, right)):
            corners = list(piece)
            if kind == RIB:
                a, b = line.points[k], line.points[k + 1]
                d = vec.unit([b[0] - a[0], b[1] - a[1], 0.0])
                across = [-d[1], d[0]] if candidate.side == "inside" else [d[1], -d[0]]
                corners += [[p[0] + across[0] * GROWTH_MM, p[1] + across[1] * GROWTH_MM] for p in piece]
            out += [vec.frame_apply(line.frame, [p[0], p[1], h]) for p in corners for h in (low, high)]
    return out


def _clear(data, lines, candidate):
    """True when the walls of `candidate` and the room they grow into lie on the outer side of one face of the box of
    the part before the step, so a longer wall cannot meet the part."""
    box = data.get("target_box_before")
    if not isinstance(box, dict) or not all(isinstance(box.get(k), list) and len(box[k]) == 3 for k in ("min", "max")):
        return False
    points = _growth_points(lines, candidate, data["kind"])
    for axis in range(3):
        if all(p[axis] >= box["max"][axis] - TOL for p in points):
            return True
        if all(p[axis] <= box["min"][axis] + TOL for p in points):
            return True
    return False


def _stands(lines, candidate, before):
    """True when the wall starts on the face of the part its sketch is drawn on and runs away from it: the sketch of
    every line sits on a face (`reference`), and a flat face of the part before the step lies on the sketch plane
    with its outward normal along the way of the wall. A size that moves that face then moves the sketch and the wall
    with it."""
    if candidate.way == 0 or not before:
        return False
    for line in lines:
        if (line.path.get("reference") or {}).get("kind") != "face":
            return False
    frame = lines[0].frame
    normal = vec.scale(vec.unit(frame["z"]), float(candidate.way))
    return any(thin.flat_face(face) and vec.dot(vec.unit(face["normal"]), normal) >= 1.0 - thin.NORMAL_TOL
               and abs(vec.dot(vec.sub(face["point"], frame["origin"]), normal)) <= TOL for face in before)


def walls(data, before=None):
    """The `Wall` of each chain of a rib or web, or a Problem. `before` holds the faces of the part before the step
    (`target_faces_before`) when they are faces of the body the copy builds, else None: a face merged with the part,
    and the far end of a To Next wall, are then not proven."""
    problem = settings_problem(data)
    if problem is not None:
        return problem
    lines = lines_of(data)
    if is_problem(lines):
        return lines
    faces = data.get("wall_faces")
    corners = _corners(faces) if isinstance(faces, list) and faces else None
    if corners is None:
        return UNMEASURED
    for line in lines:
        reason = thin.line_problem(line.points, 0.0, 0.0)
        if reason:
            return Problem("folds", words.RIB_FOLDS % reason, gap_hints.RIB_WEB)
    candidates = _candidates(data, lines, corners)
    if is_problem(candidates):
        return candidates
    found = [c for c in candidates if _fits(lines, c, faces, before)]
    if len(found) > 1:
        return UNSURE
    if not found:
        # A web that Fusion extends to the part has faces past the ends of its lines.
        if data.get("extended"):
            return EXTENDED
        # The corners of a face merged with the part lie on the part's face too: such a wall is not proven.
        if any(_fits(lines, c, faces, before, merged_corners=False) for c in candidates):
            return FLUSH
        return NOT_MATCHING
    chosen = found[0]
    for line in lines:
        reason = thin.line_problem(line.points, *thin.reaches(chosen.side, chosen.width))
        if reason:
            return Problem("folds", words.RIB_FOLDS % reason, gap_hints.RIB_WEB)
    if not is_number(data.get("volume_before")) or not is_number(data.get("volume_after")):
        return BODY_UNMEASURED
    measured = data["extent"] == TO_NEXT
    if measured and not (_whole_band(data, lines, chosen) and _ends_on_part(lines, chosen, data["kind"], before)):
        return NEXT_SHAPE
    if not measured and not _whole_band(data, lines, chosen):
        return MEETS_PART
    length = chosen.span[1] - chosen.span[0]
    clear = not measured and _clear(data, lines, chosen)
    stands = _stands(lines, chosen, before)
    return [Wall(line, chosen.side, chosen.width, chosen.way, length, measured, clear, stands) for line in lines]


def as_extrude(data, wall):
    """The data of the thin extrude of an open line that builds `wall`: the band of its line, `width` wide on its
    side, extruded from the sketch plane along the normal by its length, one way or centred. `thin_wall.decided`
    carries the side, so the extrude takes the side found here. The parameters behind the width and the length go
    to the extrude's paths: for a rib the depth is the wall's width and the thickness its length, for a web the
    other way round."""
    params = data.get("params") or {}
    width_from, length_from = ("depth", "thickness") if data["kind"] == RIB else ("thickness", "depth")
    length_path = "symmetric.distance" if wall.symmetric else "side_one.distance"
    built = {
        "operation": "join",
        "profiles": [{"kind": "other", "type": "Path"}],
        "start": {"kind": "profilePlane"},
        "extent_type": "symmetric" if wall.symmetric else "one",
        "side_one": None if wall.symmetric else {"kind": "distance", "distance": wall.length, "taper_deg": 0.0,
                                                 "direction": wall.way},
        "side_two": None,
        "symmetric": {"distance": wall.length, "full_length": True, "taper_deg": 0.0} if wall.symmetric else None,
        "thin": True,
        "thin_wall": {"location": LOCATION_OF[wall.side], "thickness": wall.width, "decided": wall.side},
        "participants": data.get("participants") or [],
        "target_box_before": data.get("target_box_before"),
        "end_offset": None,
        "profile_area": None,
        "end_area": None,
        "path": wall.line.path,
        "wall_faces": data.get("wall_faces"),
        "target_faces_body": data.get("target_faces_body"),
        "target_faces_before": data.get("target_faces_before"),
    }
    # A To Next depth is measured: no parameter is behind it.
    given = {k: v for k, v in params.items() if k != "depth" or data.get("extent") == DISTANCE}
    mapped = {}
    if width_from in given:
        mapped["thin.thickness"] = given[width_from]
    if length_from in given:
        mapped[length_path] = given[length_from]
    if mapped:
        built["params"] = mapped
    return built


def paths_of(data, wall):
    """{value path of the rib or web: path of the thin extrude}: where `as_extrude` put the values `depth` and
    `thickness`."""
    length_path = "symmetric.distance" if wall.symmetric else "side_one.distance"
    if data["kind"] == RIB:
        return {"depth": "thin.thickness", "thickness": length_path}
    return {"thickness": "thin.thickness", "depth": length_path}


def marks(data, wall, name):
    """[(value paths, why)]: the reasons to mark the sizes of a rib or web written as `wall`. Each output marks every
    size read before the step with `why`, and the sizes the values at the paths read (the rib or web's own `depth`
    and, for a web, `thickness`). Empty when the wall follows its sizes as written."""
    out = []
    grows = ("depth",) if data["kind"] == RIB else ("depth", "thickness")
    if wall.measured:
        out.append((grows, words.RIB_MEASURED_MARK % name))
    elif not wall.clear:
        out.append((grows, words.RIB_MEETS_MARK % name))
    elif not wall.stands:
        out.append(((), words.RIB_PART_MOVES_MARK % name))
    if data.get("extended"):
        out.append(((), words.RIB_EXTENDED_MARK % name))
    return out
