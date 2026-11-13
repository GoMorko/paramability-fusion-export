"""The order the outlines of one extrude are written in, so that each one joins what is built."""
import heapq

from .. import follow
from ...geometry import vec
from ...geometry.footprint import Footprint, polyline
from .common import SAMPLE_INSET


def _samples(footprint):
    """Sketch points just inside an outline: the middle of each curve, moved inward."""
    points = []
    for n, curve in enumerate(footprint.curves):
        mid = curve.get("mid") or [(a + b) / 2.0 for a, b in zip(curve["start"], curve["end"])]
        out = footprint.outward(n, mid)
        if out is not None:
            points.append([mid[0] - SAMPLE_INSET * out[0], mid[1] - SAMPLE_INSET * out[1]])
    return points


def _in_model(profile, uv, height):
    return vec.frame_apply(profile["frame"], [uv[0], uv[1], height])


def _bounds(points):
    """(low, high) corners of the box around 3D points."""
    return ([min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)])


def _apart(a, b):
    """True when two boxes (low, high) do not overlap."""
    return any(a[1][i] < b[0][i] or b[1][i] < a[0][i] for i in range(3))


class _Outline:
    """One outline for the order search: its footprint, where its curve ends lie and the box around its region in
    model space (grown by the touch tolerance), all worked out once."""

    def __init__(self, profile):
        self.profile = profile
        self.footprint = Footprint(profile)
        self.ends = [_in_model(profile, curve[key], 0.0) for curve in self.footprint.curves
                     for key in ("start", "end")]
        flat = [p for curve in self.footprint.curves for p in polyline(curve)]
        corners = [(x, y) for x in (min(p[0] for p in flat), max(p[0] for p in flat))
                   for y in (min(p[1] for p in flat), max(p[1] for p in flat))]
        low, high = _bounds([_in_model(profile, c, 0.0) for c in corners])
        self.box = ([v - follow.LATERAL_TOL for v in low], [v + follow.LATERAL_TOL for v in high])
        self.ends_box = _bounds(self.ends)
        self._samples = None

    def samples(self):
        if self._samples is None:
            self._samples = _samples(self.footprint)
        return self._samples

    def meets(self, other):
        """True when a curve end of this outline lies in or on `other` (both on one plane)."""
        if _apart(self.ends_box, other.box):
            return False
        low, high = other.box
        for p in self.ends:
            if any(p[i] < low[i] or p[i] > high[i] for i in range(3)):
                continue
            local = vec.frame_to_local(other.profile["frame"], p)
            uv = [local[0], local[1]]
            if other.footprint.covers(uv) or other.footprint.nearest_curve(uv)[1] <= follow.LATERAL_TOL:
                return True
        return False


def _heights(entry, shift, join=False):
    """Heights (along the sketch normal) to test for material: inside the side. A join also tests just outside both
    ends, since a tool that stands on the part's face joins it."""
    reach = entry.distance or 0.0
    if entry.extent == "symmetric":
        ends = (-reach / 2.0, reach / 2.0)
    else:
        ends = (0.0, entry.sign * reach)
    low, high = min(ends), max(ends)
    inset = min(SAMPLE_INSET, (high - low) / 4.0)
    found = [low + inset, (low + high) / 2.0, high - inset]
    if join:
        found += [low - SAMPLE_INSET, high + SAMPLE_INSET]
    return [shift + h for h in found]


def _touches_part(ctx, outline, entry, shift, join=False):
    """True when the tool of one outline and side reaches into the part built so far."""
    profile = outline.profile
    return any(follow.inside(ctx, _in_model(profile, uv, h))
               for h in _heights(entry, shift, join) for uv in outline.samples())


def touching_order(ctx, units, shift, join):
    """(outline, side) pairs in an order where each one joins what is built: one that reaches into the part, or
    touches a pair already taken, comes next. Fusion adds all outlines at once, the recipe one step after the other,
    so a step that touches only a later one would stand apart for a while. The order stays Fusion's where it works.

    Both sides of one outline touch each other; outlines touch on one side when they meet in the sketch. `join` is
    true when the steps add to the part, so a tool that stands on a face of it counts as touching it.

    Candidates wait in a heap by position, so the work follows the number of outlines that really touch."""
    found = {}

    def outline(profile):
        if id(profile) not in found:
            found[id(profile)] = _Outline(profile)
        return found[id(profile)]

    profiles = [units[n][0][0] for n in range(len(units))]
    by_profile = {}
    for n, profile in enumerate(profiles):
        by_profile.setdefault(id(profile), []).append(n)
    first_of = {id(profile): profile for profile in profiles}
    touching = ([n for n, (built, entry) in enumerate(units) if _touches_part(ctx, outline(built[0]), entry, shift, join)]
                if ctx.slabs else [])
    heap = list(touching)
    heapq.heapify(heap)
    meeting = {}

    def meeting_it(pid):
        """Ids of the outlines that meet outline `pid` (a curve end of theirs lies in or on it)."""
        if pid not in meeting:
            target = outline(first_of[pid])
            meeting[pid] = [other for other in by_profile if other != pid and outline(first_of[other]).meets(target)]
        return meeting[pid]

    taken = [False] * len(units)
    order, ahead = [], 0
    for _ in units:
        pick = None
        while heap and pick is None:
            n = heapq.heappop(heap)
            pick = None if taken[n] else n
        if pick is None:
            while taken[ahead]:
                ahead += 1
            pick = ahead
        taken[pick] = True
        order.append(pick)
        pid, entry = id(profiles[pick]), units[pick][1]
        for n in by_profile[pid]:
            heapq.heappush(heap, n)
        for other in meeting_it(pid):
            for n in by_profile[other]:
                if units[n][1] is entry:
                    heapq.heappush(heap, n)
    return [units[n] for n in order]
