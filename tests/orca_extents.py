"""Captures of extrudes that end on a face or plane, start from one, or taper, for the Orca tests and the live check
(`scripts/orca_live_check.py write <file>` with a capture these write). Each target box and volume is worked out from
the shapes, so the live check can compare what Orca builds."""
import math

from tests.probe_helpers import user

B1 = {"token": "t1", "name": "Body1"}
UP = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}


def rect(x0, y0, x1, y1):
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [{"kind": "line", "start": list(corners[n]), "end": list(corners[(n + 1) % 4])} for n in range(4)]


def circle(r, cx=0.0, cy=0.0):
    return [{"kind": "circle", "center": [cx, cy], "radius": r}]


def slot(half, r):
    """A slot along x: two lines `2 * half` long joined by half circles of radius `r` (tangent ends)."""
    return [{"kind": "line", "start": [-half, -r], "end": [half, -r]},
            {"kind": "arc", "start": [half, -r], "end": [half, r], "center": [half, 0.0], "radius": r,
             "mid": [half + r, 0.0]},
            {"kind": "line", "start": [half, r], "end": [-half, r]},
            {"kind": "arc", "start": [-half, r], "end": [-half, -r], "center": [-half, 0.0], "radius": r,
             "mid": [-half - r, 0.0]}]


def lens():
    """Two arcs of radius 5 that meet at two sharp corners, (-4, 0) and (4, 0)."""
    return [{"kind": "arc", "start": [4.0, 0.0], "end": [-4.0, 0.0], "center": [0.0, -3.0], "radius": 5.0,
             "mid": [0.0, 2.0]},
            {"kind": "arc", "start": [-4.0, 0.0], "end": [4.0, 0.0], "center": [0.0, 3.0], "radius": 5.0,
             "mid": [0.0, -2.0]}]


def at(z):
    return dict(UP, origin=[0.0, 0.0, float(z)])


def profile(sketch, frame, outer, holes=()):
    loops = [{"outer": True, "curves": outer}] + [{"outer": False, "curves": h} for h in holes]
    return {"sketch": sketch, "frame": frame, "loops": loops}


def side(distance, taper=0.0):
    return {"kind": "distance", "distance": float(distance), "taper_deg": float(taper)}


def plane_target(z, token, offset_from_origin=True, **extra):
    """A toEntity or fromEntity record of a construction plane at height `z`, offset from the origin XY plane."""
    record = {"plane": {"point": [0.0, 0.0, float(z)], "normal": [0.0, 0.0, 1.0]}, "entity_type": "ConstructionPlane",
              "token": token, "definition": "ConstructionPlaneOffsetDefinition", "made_by": 0}
    if offset_from_origin:
        record["built_on"] = [{"origin": True}]
    record.update(extra)
    return record


def face_target(z, point_xy):
    """A toEntity or fromEntity record of a flat face of Body1 at height `z`, measured at `point_xy`."""
    point = [float(point_xy[0]), float(point_xy[1]), float(z)]
    return {"plane": {"point": point, "normal": [0.0, 0.0, 1.0]}, "entity_type": "BRepFace", "face_point": point,
            "body": dict(B1), "token": "face%g" % z}


def extrude(index, name, profiles, operation="newBody", side_one=None, extent="one", side_two=None, symmetric=None,
            start=None, end_offset=None, params=None, **extra):
    data = {"operation": operation, "profiles": profiles, "start": start or {"kind": "profilePlane"},
            "extent_type": extent, "side_one": side_one, "side_two": side_two, "symmetric": symmetric, "thin": False,
            "participants": [dict(B1)] if operation != "newBody" else [], "end_offset": end_offset,
            "params": params or {}}
    data.update(extra)
    return {"index": index, "name": name, "type": "ExtrudeFeature", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [dict(B1)], "data": data}


def sketch_item(index, name):
    return {"index": index, "name": name, "type": "Sketch", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [], "data": {}}


def plane_item(index, name):
    return {"index": index, "name": name, "type": "ConstructionPlane", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [], "data": {}}


def capture(items, box, volume, users=(), models=()):
    return {"capture": 3, "fusion": "2.0.0", "design": "Extents", "up_axis": "z", "design_units": "mm",
            "target": dict(B1, box={"min": list(box[0]), "max": list(box[1])}, volume_mm3=round(volume, 4)),
            "items": items, "parameters": {"user": list(users), "model": list(models)}}


def model(name, expression, value_mm, kind="feature", token="", unit="mm"):
    """A model parameter whose value is `value_mm` (stored in cm, as Fusion keeps lengths)."""
    internal = value_mm * 0.1 if unit == "mm" else math.radians(value_mm) if unit == "deg" else value_mm
    return {"name": name, "expression": expression, "value": internal, "unit": unit, "kind": "derived", "role": "",
            "dependency_parameters": [], "created_by": {"kind": kind, "token": token or "tok_" + name, "name": ""}}


def angle_user(name, deg):
    """A user parameter of `deg` degrees (a negative one too)."""
    return dict(user(name, "%g deg" % deg, deg, "deg"), kind="angle")


def param(name, expression, value):
    return {"name": name, "expression": expression, "value": value}


def plate_items(height=10.0, sized=True):
    """Sketch1 and Extrude1: a 40 by 20 plate from z 0, `height` tall (the size `h` when `sized`)."""
    params = {"side_one.distance": param("d1", "h", height)} if sized else {}
    return [sketch_item(0, "Sketch1"),
            extrude(1, "Extrude1", [profile("Sketch1", UP, rect(-20, -10, 20, 10))], side_one=side(height),
                    end_offset=height, params=params, target_box_before=None)]


def plate_users(height=10.0):
    return [user("h", "%g mm" % height, height, "mm")], [model("d1", "h", height)]


# ---- To ----------------------------------------------------------------------------------------------------------

def to_top_face(offset=5.0):
    """A 40 by 20 plate `h` (10) tall, and a 10 by 10 post from its base sketch up to the plate's top face plus
    `offset`: the post's length follows h."""
    users, models = plate_users()
    target = dict(face_target(10.0, (15.0, 5.0)), kind="toEntity", chained=False, offset=offset)
    items = plate_items() + [
        sketch_item(2, "Sketch2"),
        extrude(3, "Post", [profile("Sketch2", UP, rect(-5, -5, 5, 5))], operation="join", side_one=target,
                end_offset=10.0 + offset, target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]})]
    return capture(items, ((-20, -10, 0), (20, 10, 10 + offset)), 8000.0 + 100.0 * offset, users, models)


def to_offset_plane(lift=15.0):
    """A 40 by 20 by 10 plate and a 10 by 10 post from the base sketch up to Plane1, `lift_mm` above the origin XY
    plane: the post's length is lift_mm."""
    users = [user("lift_mm", "%g mm" % lift, lift, "mm")]
    models = [model("d20", "lift_mm", lift, kind="constructionPlane", token="cp1")]
    target = dict(plane_target(lift, "cp1", made_by=2), kind="toEntity", chained=False, offset=0.0)
    items = plate_items(sized=False) + [
        plane_item(2, "Plane1"), sketch_item(3, "Sketch2"),
        extrude(4, "Post", [profile("Sketch2", UP, rect(-5, -5, 5, 5))], operation="join", side_one=target,
                end_offset=lift, target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]})]
    return capture(items, ((-20, -10, 0), (20, 10, max(10.0, lift))), 8000.0 + 100.0 * max(0.0, lift - 10.0),
                   users, models)


def two_planes(top=20.0):
    """A rod of radius 5 sketched on Plane1 (5 above the origin), two sides: up to Plane2, `top_mm` above the
    origin, and down to the origin XY plane."""
    users = [user("top_mm", "%g mm" % top, top, "mm")]
    models = [model("d30", "5 mm", 5.0, kind="constructionPlane", token="cp1"),
              model("d31", "top_mm", top, kind="constructionPlane", token="cp2")]
    frame = dict(UP, origin=[0.0, 0.0, 5.0])
    sketch = dict(profile("Sketch1", frame, circle(5.0)),
                  reference={"kind": "constructionPlane", "token": "cp1", "made_by": 0,
                             "definition": "ConstructionPlaneOffsetDefinition", "built_on": [{"origin": True}]})
    up = dict(plane_target(top, "cp2", made_by=1), kind="toEntity", chained=False, offset=0.0)
    down = {"kind": "toEntity", "chained": False,
            "offset": 0.0, "plane": {"point": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0]},
            "entity_type": "ConstructionPlane", "origin": True}
    items = [plane_item(0, "Plane1"), plane_item(1, "Plane2"), sketch_item(2, "Sketch1"),
             extrude(3, "Rod", [sketch], extent="two", side_one=up, side_two=down, end_offset=top - 5.0,
                     target_box_before=None)]
    return capture(items, ((-5, -5, 0), (5, 5, top)), math.pi * 25.0 * top, users, models)


# ---- From ---------------------------------------------------------------------------------------------------------

def from_top_face(length=5.0):
    """A 40 by 20 plate `h` (10) tall, and a 10 by 10 boss sketched on the base plane that starts from the plate's
    top face and goes `length` up."""
    users, models = plate_users()
    start = dict(face_target(10.0, (15.0, 5.0)), kind="fromEntity")
    items = plate_items() + [
        sketch_item(2, "Sketch2"),
        extrude(3, "Boss", [profile("Sketch2", UP, rect(-5, -5, 5, 5))], operation="join", side_one=side(length),
                start=start, end_offset=10.0 + length, target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]})]
    return capture(items, ((-20, -10, 0), (20, 10, 10 + length)), 8000.0 + 100.0 * length, users, models)


def face_outline(length=5.0):
    """A 40 by 20 plate `h` (10) tall, and its top face extruded `length` up (the face as the outline)."""
    users, models = plate_users()
    face = {"face": True, "type": "BRepFace", "surface": "Plane", "frame": at(10.0), "space": "sketch",
            "loops": [{"outer": True, "curves": rect(-20, -10, 20, 10)}], "token": "top", "face_point": [0, 0, 10],
            "body": dict(B1), "made_by": {"index": 1, "name": "Extrude1", "which": "end"}}
    items = plate_items() + [
        extrude(2, "Raise", [face], operation="join", side_one=side(length), end_offset=length,
                target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]})]
    return capture(items, ((-20, -10, 0), (20, 10, 10 + length)), 800.0 * (10.0 + length), users, models)


# ---- taper --------------------------------------------------------------------------------------------------------

def _shrunk_rect_volume(w, d, length, deg):
    k = math.tan(math.radians(deg))
    return w * d * length - (w + d) * k * length ** 2 + 4.0 / 3.0 * k * k * length ** 3


def _cone_volume(r, length, deg):
    """A circle of radius `r` whose radius grows by tan(deg) per mm over `length`."""
    k = math.tan(math.radians(deg))
    return math.pi * (r * r * length + r * k * length ** 2 + k * k * length ** 3 / 3.0)


def _lean(deg):
    """The measured lean of a wall that Fusion's taper `deg` gives a one sided extrude going up."""
    return math.sin(math.radians(-deg))


def tapered_block(deg=-5.0, sized=False):
    """A 40 by 20 block 10 tall whose walls lean in by `deg` (Fusion's sign: negative narrows); `draft_deg` sets the
    taper when `sized`."""
    params = {"side_one.taper_deg": param("d2", "draft_deg", deg)} if sized else {}
    users = [angle_user("draft_deg", deg)] if sized else []
    models = [model("d2", "draft_deg", deg, unit="deg")] if sized else []
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Block", [profile("Sketch1", UP, rect(-20, -10, 20, 10))], side_one=side(10.0, deg),
                     end_offset=10.0, params=params, target_box_before=None, side_leans=[_lean(deg)] * 4)]
    return capture(items, ((-20, -10, 0), (20, 10, 10)), _shrunk_rect_volume(40, 20, 10, -deg), users, models)


def tapered_rod(deg=-10.0, length=10.0, down=False):
    """A rod of radius 10, `length` long (down from its sketch when `down`), its taper `deg` (the size `draft_deg`)."""
    users = [angle_user("draft_deg", deg)]
    models = [model("d2", "draft_deg", deg, unit="deg")]
    params = {"side_one.taper_deg": param("d2", "draft_deg", deg)}
    signed = -length if down else length
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Rod", [profile("Sketch1", UP, circle(10.0))], side_one=side(signed, deg), end_offset=signed,
                     params=params, target_box_before=None, side_leans=[_lean(deg) * (-1 if down else 1)])]
    grow = max(0.0, length * math.tan(math.radians(deg)))
    z = (-length, 0.0) if down else (0.0, length)
    return capture(items, ((-10 - grow, -10 - grow, z[0]), (10 + grow, 10 + grow, z[1])),
                   _cone_volume(10.0, length, deg), users, models)


def tapered_symmetric(deg=-10.0):
    """A rod of radius 10, 20 long, centred on its sketch, both halves narrowing by `deg`."""
    sym = {"distance": 20.0, "full_length": True, "taper_deg": deg}
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Rod", [profile("Sketch1", UP, circle(10.0))], extent="symmetric", side_one=None, symmetric=sym,
                     end_offset=10.0, target_box_before=None, side_leans=[_lean(deg), -_lean(deg)])]
    return capture(items, ((-10, -10, -10), (10, 10, 10)), 2.0 * _cone_volume(10.0, 10.0, deg))


def tapered_two_sides(up=-10.0, down=-5.0):
    """A rod of radius 10: 10 up narrowing by `up`, and 5 down narrowing by `down`."""
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Rod", [profile("Sketch1", UP, circle(10.0))], extent="two", side_one=side(10.0, up),
                     side_two=side(5.0, down), end_offset=10.0, target_box_before=None,
                     side_leans=[_lean(up), -_lean(down)])]
    return capture(items, ((-10, -10, -5), (10, 10, 10)), _cone_volume(10.0, 10.0, up) + _cone_volume(10.0, 5.0, down))


def tapered_slot(deg=-5.0):
    """A slot (two 20 mm lines, ends of radius 6) 10 tall, narrowing by `deg`."""
    k = math.tan(math.radians(-deg))
    volume = sum((40.0 * (6.0 - k * h) + math.pi * (6.0 - k * h) ** 2) * 0.01 for h in [(n + 0.5) * 0.01
                                                                                       for n in range(1000)])
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Slot", [profile("Sketch1", UP, slot(10.0, 6.0))], side_one=side(10.0, deg),
                     end_offset=10.0, target_box_before=None, side_leans=[_lean(deg)] * 4)]
    return capture(items, ((-16, -6, 0), (16, 6, 10)), volume)


def tapered_cut(deg=-10.0):
    """A 40 by 20 by 10 plate with a round hole of radius 5 cut 10 down from its top, narrowing by `deg` going in."""
    items = plate_items(sized=False) + [
        sketch_item(2, "Sketch2"),
        extrude(3, "Countersunk", [profile("Sketch2", at(10.0), circle(5.0))], operation="cut",
                side_one=side(-10.0, deg), end_offset=-10.0, profile_area=math.pi * 25.0,
                end_area=math.pi * (5.0 + 10.0 * math.tan(math.radians(deg))) ** 2,
                target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]})]
    return capture(items, ((-20, -10, 0), (20, 10, 10)), 8000.0 - _cone_volume(5.0, 10.0, deg))


def tapered_outline(curves, deg, holes=()):
    """One tapered extrude of an outline (the shape rules only; no measured box)."""
    loop_count = 1 + len(holes)
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Tapered", [profile("Sketch1", UP, curves, holes)], side_one=side(2.0, deg), end_offset=2.0,
                     target_box_before=None, side_leans=[_lean(deg)] * 2 * loop_count)]
    return capture(items, ((-30, -30, 0), (30, 30, 2)), 0.0)
