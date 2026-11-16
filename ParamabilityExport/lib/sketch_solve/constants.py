"""The entities of a sketch that no size moves, for `solve_sketch`'s `constants`: projections of another component,
and projections of the origin point, the origin axes and the origin planes of the sketch's own component."""


def _origin_axis(record, curve):
    """True for a projected line through the sketch origin that the sketch's lists did not hold: an axis of the
    component's origin, which no size moves."""
    origin = next((p for p in record.get("points") or [] if p.get("origin")), None)
    if curve.get("kind") != "line" or not curve.get("implicit") or origin is None:
        return False
    points = {p["id"]: p["xy"] for p in record.get("points") or [] if "id" in p and p.get("xy")}
    try:
        (ax, ay), (bx, by) = points[curve["points"][0]], points[curve["points"][1]]
    except (KeyError, TypeError, ValueError):
        return False
    length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    ox, oy = origin["xy"]
    return length > 0 and abs((bx - ax) * (oy - ay) - (by - ay) * (ox - ax)) / length < 1e-6


def own_origin(record, reference, fixed_plane):
    """True when `reference` (of an entity of the sketch graph `record`) is a projection of the origin point, an
    origin axis or an origin plane (`origin`) of the sketch's own component, and the sketch plane moves with no size
    (`fixed_plane`, from the caller): it then sits still in the sketch. On a plane that a size moves or turns, the
    projection moves in the sketch and stays a measured input. The graph names its component by token; a graph that
    names none counts the target's own (`own`)."""
    if not fixed_plane or not isinstance(reference, dict) or not reference.get("origin"):
        return False
    component = record.get("component")
    token = component.get("token") if isinstance(component, dict) else None
    if token:
        return reference.get("component") == token
    return reference.get("source") == "own"


def constants_of(record, linked, fixed_plane=False):
    """The refs of the projected entities that no size moves, for `solve_sketch`: a projection of another component
    when no parameter reaches the sketch through that component (`linked` false), projections of the origin of the
    sketch's own component when the caller knows that no size moves the sketch plane (`fixed_plane`, `own_origin`),
    and an origin axis the reader did not mark. Other projections stay measured inputs: a size can move the body edge
    or sketch they come from."""
    points = {p["id"]: p for p in record.get("points") or [] if isinstance(p, dict) and "id" in p}
    out = []
    for curve in record.get("curves") or []:
        reference = curve.get("reference")
        if not isinstance(reference, dict):
            continue
        if (reference.get("source") == "other" and not linked) or own_origin(record, reference, fixed_plane) \
                or _origin_axis(record, curve):
            out.append(("curve", curve["id"]))
            out.extend(("point", p) for p in list(curve.get("points") or []) + [curve.get("center")]
                       if isinstance(p, int) and p in points)
    for pid, point in points.items():
        reference = point.get("reference")
        if isinstance(reference, dict) and ((reference.get("source") == "other" and not linked)
                                            or own_origin(record, reference, fixed_plane)):
            out.append(("point", pid))
    return out
