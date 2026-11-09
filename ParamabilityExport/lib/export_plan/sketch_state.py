"""Where the sketches of the design sit: read before and during the size checks, then compared.

A size that moves a sketch cannot follow the form yet, so the export fixes it. The reader only uses members it
finds, and a member that cannot be read leaves a gap in the list, so a failing read never invents a move.
Numbers are Fusion internal units (cm). No adsk import: it works on the objects it is given.
"""

# 1e-4 mm in cm: the recompute noise Fusion leaves on an unchanged sketch.
MOVE_TOLERANCE = 1e-5

_POINT_MEMBERS = ("startSketchPoint", "endSketchPoint", "centerSketchPoint")


def _numbers(point):
    try:
        return [float(point.x), float(point.y), float(point.z)]
    except Exception:
        return []


def _curve_numbers(curve):
    """Radius and end points of one sketch curve, as far as the curve type has them."""
    out = []
    try:
        geometry = curve.worldGeometry
    except Exception:
        return out
    for member in ("radius", "majorRadius", "minorRadius"):
        value = getattr(geometry, member, None)
        if isinstance(value, (int, float)):
            out.append(float(value))
    for member in ("center", "startPoint", "endPoint"):
        point = getattr(geometry, member, None)
        if point is not None:
            out.extend(_numbers(point))
    return out


def _collection(collection):
    try:
        return [collection.item(i) for i in range(collection.count)]
    except Exception:
        return []


def _sketch_numbers(sketch):
    out = []
    try:
        out.extend(float(v) for v in sketch.transform.asArray())
    except Exception:
        pass
    for point in _collection(getattr(sketch, "sketchPoints", None)):
        try:
            out.extend(_numbers(point.worldGeometry))
        except Exception:
            pass
    for curve in _collection(getattr(sketch, "sketchCurves", None)):
        out.extend(_curve_numbers(curve))
    return out


def read_sketches(root):
    """{sketch name: numbers} for every sketch of the root component. Never raises."""
    state = {}
    for sketch in _collection(getattr(root, "sketches", None)):
        try:
            name = sketch.name
        except Exception:
            continue
        state[name] = _sketch_numbers(sketch)
    return state


def moved_sketches(before, after, tolerance=MOVE_TOLERANCE):
    """Names of sketches whose numbers differ between two reads, in the order of `after`.

    A sketch that is new, gone, or has another count of numbers counts as moved.
    """
    moved = []
    for name, numbers in after.items():
        old = before.get(name)
        if old is None or len(old) != len(numbers) or any(abs(a - b) > tolerance for a, b in zip(old, numbers)):
            moved.append(name)
    moved.extend(name for name in before if name not in after)
    return moved
