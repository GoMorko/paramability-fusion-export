"""The placer protocol: what follow.py asks of every step that makes faces later picks can land on.

A placer stands for the faces and material of one written step (an extrude slab, the inner walls of a shell, the
faces an offset moved, a pattern copy of a slab). The context keeps them in the order they were made
(`Context.placers`); `order` is the place in that list, and a search for a point tries the latest placer first.
"""

ADD = "add"
CUT = "cut"


class Placer:
    order = 0
    # True for a step whose material is known but whose faces cannot be placed (a thin wall): a step on another
    # part's sketch cannot be checked to keep meeting such a part.
    opaque = False

    def place(self, p, edge):
        """The Place (slabs.Place or a subclass) of measured point `p` on this placer's faces, or None. `edge` asks
        for a point on an edge."""
        raise NotImplementedError

    def material_at(self, p):
        """What this step leaves at `p`: ADD when `p` lies in or on material it adds, CUT when in or on material it
        removes, None when it does not change `p`."""
        raise NotImplementedError

    def crossings(self, q, n, offsets):
        """Parameters t where the line q + t * n may cross a face of this placer (or a face moved sideways by one of
        `offsets`), for meets_part.py."""
        return []

    @property
    def wall_offsets(self):
        """How far this step moves the faces of the steps before it, both ways (a shell's thickness), for
        meets_part.py."""
        return ()
