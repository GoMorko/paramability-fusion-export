"""Captures of outlines with elliptical arcs, for the Orca tests and the live check
(`scripts/orca_live_check.py write <file>` with a capture these write, or the saved one in tests/fixtures/captures:
`orca_ellipse_arcs_slot`; `python3 -m tests.orca_ellipse_arcs` writes it again).

`arc_curve` makes a curve as the reader records an elliptical arc: a rational B-spline of degree two with one span for
each quarter turn of the arc at most, its ends and measured points. The slot is two straight sides 30 mm long joined
by two half ellipses of radii 10 and 5 (the right one runs counter clockwise, the left one clockwise), 2 mm thick:
area 300 + 50 pi, box 50 by 10 by 2."""
import math

from tests.orca_extents import UP, capture, extrude, profile, side, sketch_item

THICK = 2.0
AREA = 300.0 + 50.0 * math.pi
BOX = ((-25.0, -5.0, 0.0), (25.0, 5.0, THICK))


def _point(centre, major, minor, turn, t):
    c, s = major * math.cos(t), minor * math.sin(t)
    return [centre[0] + c * math.cos(turn) - s * math.sin(turn), centre[1] + c * math.sin(turn) + s * math.cos(turn)]


def arc_curve(centre, major, minor, turn, t0, t1, growth=1.0):
    """The capture curve of the ellipse arc from parametric angle `t0` to `t1` (clockwise when `t1` is less) of the
    ellipse with `major` and `minor` radius whose major axis is turned `turn` radians. The weights of the joints grow by
    the factor `growth` from span to span, which gives the same curve."""
    spans = max(1, math.ceil(abs(t1 - t0) / (math.pi / 2) - 1e-9))
    poles, weights = [_point(centre, major, minor, turn, t0)], [1.0]
    for n in range(spans):
        a, b = t0 + (t1 - t0) * n / spans, t0 + (t1 - t0) * (n + 1) / spans
        half = abs(b - a) / 2.0
        corner = _point((0.0, 0.0), major, minor, 0.0, (a + b) / 2.0)
        shoulder = [centre[0] + (corner[0] * math.cos(turn) - corner[1] * math.sin(turn)) / math.cos(half),
                    centre[1] + (corner[0] * math.sin(turn) + corner[1] * math.cos(turn)) / math.cos(half)]
        poles += [shoulder, _point(centre, major, minor, turn, b)]
        weights += [math.cos(half) * growth ** (n + 0.5), growth ** (n + 1)]
    knots = [0.0] * 3 + [float(k) for k in range(1, spans) for _ in range(2)] + [float(spans)] * 3
    samples = [_point(centre, major, minor, turn, t0 + (t1 - t0) * i / 24.0) for i in range(25)]
    return {"kind": "other", "type": "NurbsCurve3D", "start": samples[0], "end": samples[-1], "mid": samples[12],
            "samples": samples,
            "nurbs": {"degree": 2, "knots": knots, "poles": poles, "rational": True, "weights": weights,
                      "periodic": False}}


def line(a, b):
    return {"kind": "line", "start": list(a), "end": list(b)}


def slot_outline():
    return [line((-15, -5), (15, -5)), arc_curve((15.0, 0.0), 10.0, 5.0, 0.0, -math.pi / 2, math.pi / 2),
            line((15, 5), (-15, 5)), arc_curve((-15.0, 0.0), 10.0, 5.0, 0.0, 3 * math.pi / 2, math.pi / 2)]


def extruded(outline, volume, box):
    """`outline` extruded `THICK` from the plane z 0 as a new body of the given volume and box."""
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Extrude1", [profile("Sketch1", UP, outline)], side_one=side(THICK), end_offset=THICK)]
    return capture(items, box, volume)


def slot():
    return extruded(slot_outline(), THICK * AREA, BOX)


SAVED = {"orca_ellipse_arcs_slot": (slot, "two straight sides joined by two half ellipses of radii 10 and 5")}


def save(folder):
    import json
    import os
    for name, (make, what) in SAVED.items():
        found = make()
        comment = ("Synthetic, written by tests/orca_ellipse_arcs.py: %s, 2 mm thick, a new body. Box 50 x 10 x 2 and "
                   "volume 2 * (300 + 50 pi) = %g mm3." % (what, found["target"]["volume_mm3"]))
        with open(os.path.join(folder, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(dict({"_comment": comment}, **found), f, indent=1)
            f.write("\n")


if __name__ == "__main__":
    import os
    save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "captures"))
