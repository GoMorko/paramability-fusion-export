"""Edge and face lists to recipe selector `near` points.

A `near` point picks the closest edge (or face) of the part at the time of the step. A selector holds at most
MAX_NEAR_POINTS points, so long edge lists are split into groups that each fit.
"""

MAX_NEAR_POINTS = 32


def _point(values):
    return [round(float(v), 9) + 0.0 for v in values]


def near_points(edges):
    """Capture EDGE dicts ({token, closed, points}) to selector `near` points, in order: [[x, y, z], ...].

    An open edge gives its middle point; a closed edge gives its two points, so a kernel that splits the edge at a
    seam still picks both halves. An edge with no points gives none.
    """
    return [_point(p) for edge in edges for p in edge.get("points") or []]


def face_points(faces):
    """Capture face dicts ({token, point}) to selector `near` points, in order: [[x, y, z], ...]."""
    return [_point(face["point"]) for face in faces if face.get("point")]


def edge_groups(edges, limit=MAX_NEAR_POINTS):
    """Split `edges`, keeping order, into groups whose points total at most `limit`. No edge is cut in two."""
    groups, current, count = [], [], 0
    for edge in edges:
        size = len(edge.get("points") or [])
        if current and count + size > limit:
            groups.append(current)
            current, count = [], 0
        current.append(edge)
        count += size
    if current:
        groups.append(current)
    return groups
