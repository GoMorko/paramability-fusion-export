"""Captures, sketch graphs and probe states for the derived values (shadow mode) tests.

The plate is a rectangle sketch (width and height, the height written twice) with a circle placed from the right
edge. `read_plate` draws what Fusion would read for it at other sizes, `plate_capture` is a capture whose extrude uses
it, and `plate_graph` is the sketch as the reader writes it (`capture["sketch_graphs"]`). The corner outline and the
centred box are two more sketches of the same kind.
"""
import copy
import math
import re

from tests import context  # noqa: F401
from tests.probe_helpers import IDENT, capture, extrude, line, loop, model, profile, read, sketch_state, state, \
    table, user
from tests.sketch_solve_helpers import A, C, L, P, Sketch, rectangle
from tests.translator_helpers import load_capture

PARAMS = [user("width", "40 mm", 40), user("height", "20 mm", 20), user("margin", "5 mm", 5)]
MODEL = [model("d1", "width", 40, sketch="Sketch1"), model("d2", "height", 20, sketch="Sketch1"),
         model("d3", "height", 20, sketch="Sketch1"), model("d4", "4 mm", 4, sketch="Sketch1"),
         model("d5", "margin", 5, sketch="Sketch1"), model("d6", "height / 2", 10, sketch="Sketch1")]
TICKED = ["width", "height", "margin"]
RADIUS = 2.0


def plate_table(ticked=TICKED):
    return table(PARAMS, ticked, MODEL)


def dimension(sketch, kind, on, value, param, expression, orientation=None):
    """A driving dimension whose model parameter `param` reads `expression`."""
    found = sketch.dim(kind, on, value, param, orientation)
    sketch.dimensions[found]["expression"] = expression
    sketch.dimensions[found]["reads"] = [n for n in re.findall(r"[A-Za-z_]\w*", expression) if n not in ("mm", "deg")]
    return found


def plate_graph(width=40.0, height=20.0, margin=5.0):
    """The graph of Sketch1: a rectangle from the origin and a circle `margin` from its right edge, half way up."""
    s = Sketch()
    p1, p2, p3 = s.point(width, 0.0), s.point(width, height), s.point(0.0, height)
    lines = rectangle(s, [0, p1, p2, p3])
    centre = s.point(width - margin, height / 2)
    ring = s.circle(centre, RADIUS)
    dimension(s, "linear", [P(0), P(p1)], width, "d1", "width", "horizontal")
    dimension(s, "linear", [P(p1), P(p2)], height, "d2", "height", "vertical")
    dimension(s, "linear", [P(0), P(p3)], height, "d3", "height", "vertical")
    dimension(s, "diameter", [C(ring)], 2 * RADIUS, "d4", "4 mm")
    dimension(s, "linear", [P(centre), P(p1)], margin, "d5", "margin", "horizontal")
    dimension(s, "linear", [P(0), P(centre)], height / 2, "d6", "height / 2", "vertical")
    record = s.record()
    for number, entity in enumerate(record["curves"]):
        entity["token"] = "e%d" % number
    return record, lines


def plate_profile(width=40.0, height=20.0, margin=5.0, token="s1", name="Sketch1"):
    """The profile an extrude reads: the rectangle (curves `e0` to `e3`) with the circle (`e4`) as a hole."""
    corners = [(0, 0), (width, 0), (width, height), (0, height)]
    outline = [line(corners[i], corners[(i + 1) % 4], "e%d" % i) for i in range(4)]
    hole = {"kind": "circle", "center": [width - margin, height / 2], "radius": RADIUS, "entity": "e4"}
    return profile(name, token, [loop(outline), loop([hole], False)])


def plate_capture(graph=True):
    """A capture of one extrude over the plate, with the graph of its sketch unless `graph` is false."""
    out = capture(extrude(4, plate_profile()))
    out["parameters"] = {"user": PARAMS, "model": MODEL}
    if graph:
        out["sketch_graphs"] = [plate_graph()[0]]
    return out


def read_plate(width=40.0, height=20.0, margin=5.0, follow_margin=True):
    """What Fusion reads for the plate at these sizes: the rectangle with the circle as a hole, and the disc inside the
    circle as a second profile. With `follow_margin` false the circle stays where it was drawn."""
    shown = margin if follow_margin else 5.0
    drawn = plate_profile(width, height, shown)
    disc = {"loops": [dict(drawn["loops"][1], outer=True)]}
    return read(sketch_state("s1", [{"loops": drawn["loops"]}, disc], IDENT))


def plate_states(follow_margin=True):
    """E0 and four states that change one size each."""
    def at(**sizes):
        values = dict({"width": 40.0, "height": 20.0, "margin": 5.0}, **sizes)
        return state(sizes, read_plate(follow_margin=follow_margin, **values))
    return [state({}, read_plate(), e0=True), at(width=30.0), at(width=50.0), at(height=15.0), at(margin=3.0)]


# ---- a rectangle with one round corner ---------------------------------------------------------------------

def corner_graph(w=40.0, h=20.0, r=5.0):
    """Sketch1 as a rectangle whose bottom right corner is an arc of radius `margin` (width and height sized)."""
    s = Sketch()
    a, b = s.point(w - r, 0.0), s.point(w, r)
    top_right, top_left, centre = s.point(w, h), s.point(0.0, h), s.point(w - r, r)
    bottom, side = s.line(0, a), s.line(b, top_right)
    s.line(top_right, top_left)
    s.line(top_left, 0)
    for i, found in enumerate((bottom, side, 2, 3)):
        s.con("horizontal" if i in (0, 2) else "vertical", L(found))
    arc = s.arc(centre, a, b)
    s.con("tangent", L(bottom), A(arc))
    s.con("tangent", L(side), A(arc))
    dimension(s, "linear", [P(0), P(top_right)], w, "d1", "width", "horizontal")
    dimension(s, "linear", [P(0), P(top_right)], h, "d2", "height", "vertical")
    dimension(s, "radial", [A(arc)], r, "d5", "margin")
    record = s.record()
    for number, entity in enumerate(record["curves"]):
        entity["token"] = "e%d" % number
    return record


def corner_profile(w=40.0, h=20.0, r=5.0):
    """The outline of `corner_graph` as a profile: bottom line, corner arc, right side, top, left side."""
    centre = [w - r, r]
    mid = [centre[0] + r * math.cos(math.radians(-45)), centre[1] + r * math.sin(math.radians(-45))]
    curves = [line((0, 0), (w - r, 0), "e0"),
              {"kind": "arc", "start": [w - r, 0], "end": [w, r], "mid": mid, "center": centre, "radius": r,
               "entity": "e4"},
              line((w, r), (w, h), "e1"), line((w, h), (0, h), "e2"), line((0, h), (0, 0), "e3")]
    return profile("Sketch1", "s1", [loop(curves)])


def corner_capture():
    out = capture(extrude(4, corner_profile()))
    out["parameters"] = {"user": PARAMS, "model": MODEL}
    out["sketch_graphs"] = [corner_graph()]
    return out


def corner_states():
    def at(**sizes):
        v = dict({"width": 40.0, "height": 20.0, "margin": 5.0}, **sizes)
        return state(sizes, read(sketch_state("s1", [{"loops": corner_profile(v["width"], v["height"],
                                                                              v["margin"])["loops"]}], IDENT)))
    return [state({}, read(sketch_state("s1", [{"loops": corner_profile()["loops"]}], IDENT)), e0=True),
            at(width=30.0), at(height=26.0), at(margin=3.0), at(width=52.0, margin=7.0)]


# ---- the centred rectangle capture of the pipeline tests ----------------------------------------------------------

def centred_graph():
    """The graph of Sketch1 of the `sketch_rect_centred` fixture: an 80 by 60 rectangle centred on the origin by the
    middle of a diagonal, sized by `box_width_mm` and `depth_mm`."""
    s = Sketch()
    corners = [s.point(-40.0, -30.0), s.point(40.0, -30.0), s.point(40.0, 30.0), s.point(-40.0, 30.0)]
    lines = rectangle(s, corners)
    diagonal = s.line(corners[0], corners[2], construction=True)
    s.con("midpoint", P(0), L(diagonal))
    dimension(s, "linear", [L(lines[0])], 80.0, "d1", "box_width_mm", "horizontal")
    dimension(s, "linear", [L(lines[1])], 60.0, "d2", "depth_mm", "vertical")
    record = s.record()
    for number, entity in enumerate(record["curves"]):
        entity["token"] = "e%d" % number
    return record


def box_capture(graph=True):
    """The `sketch_rect_centred` capture, with the graph of its first sketch unless `graph` is false."""
    out = copy.deepcopy(load_capture("sketch_rect_centred"))
    if graph:
        out["sketch_graphs"] = [centred_graph()]
    return out


# ---- a triangle drawn from an angle size ----------------------------------------------------------------------

ANGLE_PARAMS = [user("len", "30 mm", 30), user("leg", "18 mm", 18), user("ang", "35 deg", 35, "deg")]
ANGLE_MODEL = [model("d1", "ang", 35, sketch="Sketch1"), model("d2", "len", 30, sketch="Sketch1"),
               model("d3", "leg", 18, sketch="Sketch1")]
ANGLE_MODEL[0].update(unit="deg", value=math.radians(35))


def _at(degrees):
    return math.cos(math.radians(degrees)), math.sin(math.radians(degrees))


def triangle_graph(ang=35.0, length=30.0, leg=18.0):
    """A base along x (`len`), a leg at an angle (`ang`, `leg` long) and the line that closes them."""
    s = Sketch()
    cos, sin = _at(ang)
    p1, p2 = s.point(length, 0.0), s.point(leg * cos, leg * sin)
    base, bevel, close = s.line(0, p1), s.line(0, p2), s.line(p1, p2)
    s.con("horizontal", L(base))
    dimension(s, "linear", [L(base)], length, "d2", "len", "horizontal")
    dimension(s, "linear", [L(bevel)], leg, "d3", "leg", "aligned")
    dimension(s, "angular", [L(base), L(bevel)], ang, "d1", "ang")
    record = s.record()
    for number, entity in enumerate(record["curves"]):
        entity["token"] = "e%d" % number
    return record


def triangle_profile(ang=35.0, length=30.0, leg=18.0):
    cos, sin = _at(ang)
    corners = [(0, 0), (length, 0), (leg * cos, leg * sin)]
    return profile("Sketch1", "s1", [loop([line(corners[0], corners[1], "e0"), line(corners[1], corners[2], "e2"),
                                            line(corners[2], corners[0], "e1")])])


def triangle_capture():
    out = capture(extrude(4, triangle_profile()))
    out["parameters"] = {"user": ANGLE_PARAMS, "model": ANGLE_MODEL}
    out["sketch_graphs"] = [triangle_graph()]
    return out


def triangle_states():
    def read_of(**sizes):
        v = dict({"len": 30.0, "leg": 18.0, "ang": 35.0}, **sizes)
        drawn = triangle_profile(v["ang"], v["len"], v["leg"])
        return read(sketch_state("s1", [{"loops": drawn["loops"]}], IDENT))
    return [state({}, read_of(), e0=True)] + [state(s, read_of(**s)) for s in (
        {"ang": 45.0}, {"len": 20.0}, {"leg": 9.0}, {"ang": 20.0, "len": 25.0})]


# ---- a sketch with hundreds of entities ---------------------------------------------------------------------------

def row_of_rectangles(count):
    """`count` plate sized rectangles side by side, `margin` apart: eight entities each, sized by width, height and
    margin like the plate."""
    s = Sketch()
    previous = 0
    for i in range(count):
        x = 5.0 + 45.0 * i
        a, b, c, d = s.point(x, 0.0), s.point(x + 40.0, 0.0), s.point(x + 40.0, 20.0), s.point(x, 20.0)
        rectangle(s, [a, b, c, d])
        s.con("horizontal_points", P(previous), P(a))
        dimension(s, "linear", [P(previous), P(a)], 5.0, "g%d" % i, "margin", "horizontal")
        dimension(s, "linear", [P(a), P(b)], 40.0, "w%d" % i, "width", "horizontal")
        dimension(s, "linear", [P(b), P(c)], 20.0, "h%d" % i, "height", "vertical")
        previous = b
    record = s.record()
    for number, entity in enumerate(record["curves"]):
        entity["token"] = "e%d" % number
    return record
