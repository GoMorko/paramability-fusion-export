"""What the solver found for one sketch: a formula or a reason for every point coordinate and radius, the choices it
made, how each dimension and constraint was used, and a summary.

Outcomes: `derived` (every point and radius of the sketch's own geometry has a formula), `partly` (some have) and
`not_derived` (none, or the sketch could not be solved: a reading that disagrees with itself, a record that cannot be
read).
"""
from ..package.numbers import round9

DERIVED, PARTLY, NOT_DERIVED = "derived", "partly", "not_derived"

# Why a value has no formula.
BLOCKED = "blocked"  # a constraint or dimension the solver does not read names the entity
REFUSED = "refused"  # a dimension on the entity does not match the drawing, so it is not used
FREE = "free"  # Fusion says the entity is not fully constrained
NO_RULE = "no_rule"  # the rules reach it from nothing that is known
CONFLICT = "conflict"  # the sketch's rules disagree, so nothing of it is used
UNREAD = "unread"  # the entity or the sketch could not be read


class Value:
    """A formula (`expr`, an `Expr` over leaf names) or the reason there is none (`code`, `reason`)."""

    def __init__(self, expr=None, code="", reason=""):
        self.expr = expr
        self.code = code
        self.reason = reason

    @property
    def derived(self):
        return self.expr is not None

    @property
    def reads(self):
        """The leaf names the formula reads."""
        return self.expr.names() if self.expr is not None else ()

    def affine(self, sketch=""):
        """The formula as an `Affine` when it is linear, else None."""
        return self.expr.as_affine(sketch) if self.expr is not None else None

    def json(self):
        if self.expr is not None:
            return {"expr": self.expr.json(), "text": self.expr.text()}
        return {"open": self.code, "reason": self.reason}


class Assumption:
    """A choice between two solutions, made from the solved drawing. `guard` stays above zero while the choice holds;
    `flips` lists the numbers of the size settings where it does not (the other solution, or none)."""

    def __init__(self, text, guard, where):
        self.text = text
        self.guard = guard
        self.where = where
        self.flips = []

    def json(self):
        out = {"text": self.text, "where": self.where, "guard": self.guard.json()}
        if self.flips:
            out["flips"] = list(self.flips)
        return out


class Leaf:
    """A name the formulas read: a dimension's model parameter (`kind` "dimension", with the dimension's `expression`
    and `reads`) or a measured input of a projected entity (`kind` "input", with the `entity` ref and `field`)."""

    def __init__(self, name, kind, value, dimension=None, expression=None, reads=(), entity=None, field="",
                 token=""):
        self.name, self.kind, self.value = name, kind, value
        self.dimension, self.expression, self.reads = dimension, expression, tuple(reads)
        self.entity, self.field, self.token = entity, field, token

    def json(self):
        out = {"kind": self.kind, "value": round9(self.value)}
        if self.kind == "dimension":
            out.update(dimension=self.dimension, expression=self.expression, reads=list(self.reads))
        else:
            out.update(entity=list(self.entity), field=self.field, token=self.token)
        return out


class Usage:
    """How one dimension or constraint was used: `status` and, when it was not, why. For a dimension `measured` is
    what the solved drawing gives."""

    def __init__(self, status, reason="", measured=None):
        self.status, self.reason, self.measured = status, reason, measured

    def json(self):
        out = {"status": self.status}
        if self.reason:
            out["reason"] = self.reason
        if self.measured is not None:
            out["measured"] = round9(self.measured)
        return out


class Solution:
    """The result for one sketch.

    - `points`: point id to `(x, y)`, two `Value`;
    - `radii`: arc or circle id to a `Value`;
    - `leaves`: name to `Leaf`, every name a formula may read;
    - `assumptions`: list of `Assumption`;
    - `directions`: line id to the line's angle as a `Value` (the extended reading only);
    - `parallel_by_distance`: the pairs of lines the extended reading keeps parallel for a distance dimension alone;
    - `dimensions`, `constraints`: id to `Usage`;
    - `settings`: the size settings (leaf name to number) the redundant rules and the choices were checked at."""

    def __init__(self, sketch, token):
        self.sketch, self.token = sketch, token
        self.outcome = NOT_DERIVED
        self.reason = ""
        self.points = {}
        self.radii = {}
        self.own = set()  # refs of the sketch's own entities, which the outcome counts
        self.leaves = {}
        self.assumptions = []
        self.dimensions = {}
        self.constraints = {}
        # Line id to the angle of the line (degrees, from its first point to its second) as a `Value`; filled by the
        # extended reading only (`solve_sketch(extended=True)`).
        self.directions = {}
        # Pairs of line ids that only a driving distance dimension between them keeps parallel (the extended reading
        # with `distance_parallel`).
        self.parallel_by_distance = []
        self.settings = []
        self.notes = []

    def counts(self):
        """(derived, open) over the coordinates and radii of the sketch's own entities."""
        done = total = 0
        for pid, pair in self.points.items():
            if ("point", pid) in self.own:
                total += 2
                done += sum(1 for v in pair if v.derived)
        for cid, value in self.radii.items():
            if ("curve", cid) in self.own:
                total += 1
                done += 1 if value.derived else 0
        return done, total - done

    def finish(self):
        done, left = self.counts()
        if self.reason:
            self.outcome = NOT_DERIVED
        elif not left:
            self.outcome = DERIVED
        else:
            self.outcome = PARTLY if done else NOT_DERIVED

    @property
    def flips(self):
        return any(a.flips for a in self.assumptions)

    def json(self):
        done, left = self.counts()
        out = {"sketch": self.sketch, "token": self.token, "outcome": self.outcome, "derived": done, "open": left}
        if self.reason:
            out["reason"] = self.reason
        out["points"] = {str(p): {"x": vx.json(), "y": vy.json()} for p, (vx, vy) in sorted(self.points.items())}
        out["radii"] = {str(c): v.json() for c, v in sorted(self.radii.items())}
        out["leaves"] = {n: leaf.json() for n, leaf in self.leaves.items()}
        if self.assumptions:
            out["assumptions"] = [a.json() for a in self.assumptions]
        out["dimensions"] = {str(i): u.json() for i, u in sorted(self.dimensions.items())}
        out["constraints"] = {str(i): u.json() for i, u in sorted(self.constraints.items()) if u.status != "used"}
        if self.notes:
            out["notes"] = list(self.notes)
        return out
