"""A flat face of the part used as an extrude outline.

The reader gives such a face as an outline record (docs/capture-format.md, section 4): its plane as a frame whose z is
the outward normal, its loops in that plane and, when it knows, the earlier extrude whose faces hold it (`made_by`).
`prepare` turns it into the outline the extrude handler writes, in one of two ways:

- Same outline: the face is the start or end face of an earlier extrude step of this walk, that step has no taper,
  and the face still has that step's outline (no round, cut or join changed it). The step's written outline is used
  again on a plane at that face, so the outline and the plane follow the sizes that step follows (its length, its
  start, its sketch). The face is compared at the measured sizes only: when steps came after that extrude, one of
  them may reach the face at other sizes, so the sizes read so far stay free with a warning.
- As measured: any other flat face, and a face used together with sketch outlines, is written from its read loops
  as numbers. The sizes read by the steps written so
  far may change that face, so they stay free with a warning (`Context.doubt`).

The extrude's own length, taper and operation follow their parameters in both cases (extrude.py).
"""
import copy

from ..sketch_values.motion import Stuck
from . import loops, vec
from .curved import combine
from .footprint import Footprint, polyline
from .result import Refusal
from .slabs import cleaned
from .values import Quantity, numbers_of

PARALLEL_TOL = 1e-9
# How far (mm) the face's edges may lie from the earlier step's outline, and that outline from the edges.
SAME_OUTLINE_TOL = 1e-3


class FaceOutline:
    """What the extrude handler writes for a face: `profile` (a capture outline record: frame and loops), `loops`
    (outer, inners) as numbers, and `drawn`, a `CapOutline` on the same outline path, else None."""

    def __init__(self, profile, loops_, drawn=None):
        self.profile, self.loops, self.drawn = profile, loops_, drawn


def refusal(profile):
    """A Refusal for a face record that cannot be an outline (curved, unread, or read without its plane and edges),
    else None."""
    if "loops" in profile and isinstance(profile.get("frame"), dict):
        return None
    if profile.get("surface") not in (None, "Plane"):
        return Refusal("This extrude uses a curved face as its outline, which is not copied.")
    if profile.get("problem"):
        return Refusal("The edges of the flat face this extrude uses as its outline could not be read from Fusion, "
                       "so it is not copied.")
    return Refusal("The flat face this extrude uses as its outline was read without its plane and edges, so it is "
                   "not copied. Export again with this version of the add-in.")


def prepare(ctx, item, profiles):
    """The `FaceOutline` of the flat face among an extrude's outlines (the others are sketch outlines), a Refusal, or
    None when no outline is a face."""
    faces = [p for p in profiles if isinstance(p, dict) and p.get("face")]
    if not faces:
        return None
    if len(faces) > 1:
        return Refusal("This extrude uses several flat faces as outlines, which is not copied yet.")
    face = faces[0]
    found = refusal(face)
    if found is not None:
        return found
    plain = {k: v for k, v in face.items() if k != "face"}
    measured = loops.profile_loops(plain)
    if isinstance(measured, Refusal):
        return measured
    if len(faces) < len(profiles):
        # Sketch outlines beside the face keep their own plane, so the face keeps the plane it was measured on.
        return _as_measured(ctx, item, plain, measured)
    return _same_outline(ctx, item, plain) or _as_measured(ctx, item, plain, measured)


def _as_measured(ctx, item, face, measured):
    """The face as read, with the sizes that may change it marked. A face of a body this walk does not build may
    change with any size."""
    body = face.get("body")
    if body and not ctx.is_target(body):
        names = ctx.table.ticked if ctx.table is not None else ()
    else:
        names = ctx.written_reads
    if names:
        ctx.doubt(names, "%s uses a flat face as its outline that may change with it, and the copy keeps that face "
                  "as it was measured" % item.get("name", "a step"))
    return FaceOutline(face, measured)


def _points(profile):
    return [p for loop in profile["loops"] for curve in loop["curves"] for p in polyline(curve)]


def _moved_into(points, source, target):
    """2D points of the frame `source` as 2D points of the frame `target` (both frames on parallel planes)."""
    return [vec.frame_to_local(target, vec.frame_apply(source, [u, v, 0.0]))[:2] for u, v in points]


def _same_shape(face, slab):
    """True when the face's edges lie on the slab's outline and the slab's outline on the face's edges."""
    theirs, mine = slab.footprint, Footprint(face)
    edges = _moved_into(_points(face), face["frame"], slab.frame)
    if any(theirs.nearest_curve(p)[1] > SAME_OUTLINE_TOL for p in edges):
        return False
    return all(mine.nearest_curve(p)[1] <= SAME_OUTLINE_TOL
               for p in _moved_into(_points(slab.profile), slab.frame, face["frame"]))


def _same_outline(ctx, item, face):
    """The `FaceOutline` of a face that is the untouched start or end face of an untapered extrude step of this walk,
    else None."""
    made = face.get("made_by") or {}
    point = face.get("face_point")
    if made.get("which") not in ("start", "end") or point is None:
        return None
    if face.get("body") and not ctx.is_target(face["body"]):
        return None
    ids = set(ctx.steps_of(made.get("index")))
    outward = vec.unit(face["frame"]["z"])
    for slab in reversed(ctx.slabs):
        if slab.id not in ids or slab.is_copy or slab.taper is not None:
            continue
        if abs(abs(vec.dot(slab.axis, outward)) - 1.0) > PARALLEL_TOL:
            continue
        found = slab.place(point, False)
        if found is None or found.which not in ("start", "end") or found.curve is not None:
            continue
        step = next((s for s in ctx.steps if s.get("id") == slab.id), None)
        if step is None or step.get("kind") != "extrude" or not _flips(step) or not _same_shape(face, slab):
            continue
        _doubt_later_steps(ctx, item, made, step)
        return _on_cap(slab, found.factor, step, outward)
    return None


def _doubt_later_steps(ctx, item, made, step):
    """Mark the sizes read so far when a step written, or left out, after the extrude that made the face may reach
    that face at other sizes: the face was only compared with its outline at the measured sizes."""
    later = ctx.steps[ctx.steps.index(step) + 1:]
    gaps_after = [gap for gap in ctx.gaps if gap.index is not None and gap.index > made.get("index", -1)]
    if (later or gaps_after) and ctx.written_reads:
        ctx.doubt(ctx.written_reads, "%s uses the face of %s as its outline, and a later step may change that face at "
                  "other sizes" % (item.get("name", "a step"), made.get("name") or "an earlier extrude"))


def _flips(step):
    """True when every loop of the step's sketch is a kind `loops.flip_y` can mirror."""
    sketch = step.get("sketch") or {}
    drawn = [sketch.get("outer")] + list(sketch.get("inner") or [])
    return all(isinstance(loop, dict) and loop.get("kind") in loops.FLIPPED_KINDS for loop in drawn)


def _mirrored(node):
    """Capture curves with every 2D point and direction mirrored across the x axis."""
    if isinstance(node, list) and len(node) == 2 and all(isinstance(v, (int, float)) for v in node):
        return [node[0], 0.0 - node[1]]
    if isinstance(node, list):
        return [_mirrored(v) for v in node]
    if isinstance(node, dict):
        return {k: _mirrored(v) for k, v in node.items()}
    return node


def _on_cap(slab, factor, step, outward):
    """The slab's written outline on a plane at its start or end face (`factor` of its length along its axis),
    facing `outward`."""
    frame = slab.frame
    turned = vec.dot(outward, frame["z"]) < 0
    sign = -1.0 if turned else 1.0
    cap = [q.plus(slab.length.scaled(factor * a)) if abs(factor * a) > 1e-12 else q
           for q, a in zip(slab.origin, slab.axis)]
    z = vec.scale(frame["z"], sign)
    cap_frame = {"origin": [q.n for q in cap], "x": list(frame["x"]), "y": vec.scale(frame["y"], sign), "z": z}
    held = slab.profile["loops"]
    profile = {"sketch": slab.profile.get("sketch", ""), "frame": cap_frame, "space": "sketch",
               "loops": _mirrored(held) if turned else copy.deepcopy(held)}
    sketch = step.get("sketch") or {}
    written = [copy.deepcopy(sketch.get("outer"))] + copy.deepcopy(sketch.get("inner") or [])
    if vec.dot(slab.axis, z) < 0:
        written = [loops.flip_y(loop) for loop in written]
    drawn = CapOutline(cap, z, written, slab.outline, slab.footprint, turned)
    numbers = numbers_of(written)
    return FaceOutline(profile, (numbers[0], numbers[1:]), drawn)


class CapOutline:
    """An earlier step's outline drawn again on a plane at its start or end face, for the extrude handler: the
    written loops, the plane's origin as Quantities and its normal `z`. Picks on the new step follow the earlier
    outline (`follow`). `turned` says the new plane faces the other way, so its 2D y axis is the earlier one
    mirrored."""

    def __init__(self, origin, z, written, outline, footprint, turned):
        self.cap, self.z = origin, z
        self._written = written
        self.outline, self.footprint, self.turned = outline, footprint, turned
        self.table = outline.table if outline is not None else None
        self.sketch = outline.sketch if outline is not None else ""

    def written(self, ctx):
        """(outer, inners) as written by the earlier step, seen from this plane."""
        loops_ = copy.deepcopy(self._written)
        return loops_[0], loops_[1:]

    def origin(self, ctx, shift):
        """The plane origin moved along its normal by the start `shift` (a Quantity), as written."""
        return [cleaned(q.plus(shift.scaled(d)) if abs(d) > 1e-12 else q) for q, d in zip(self.cap, self.z)]

    def plane_shift(self, ctx):
        """How far the plane moves along its normal from where it was measured, as a Quantity (zero number)."""
        total = Quantity(0.0)
        for q, d in zip(self.cap, self.z):
            if abs(d) > 1e-12:
                total = total.plus(q.scaled(d))
        return total.plus(-total.n)

    def follow(self, footprint, which, curve, corner, uv):
        """Where a point of the new step moves: the earlier outline's answer for the same point."""
        if self.outline is None:
            return None
        found = self.outline.follow(self.footprint, which, curve, corner, [uv[0], -uv[1]] if self.turned else uv)
        if found is None or isinstance(found, Stuck) or not self.turned:
            return found
        return found[0], combine([(-1.0, found[1])], self.sketch)
