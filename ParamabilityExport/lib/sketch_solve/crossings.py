"""Points at a known distance from other points: crossings of a circle with a line or with another circle.

A `Dist` relation says two points lie a known distance apart. Once that distance is known and only one coordinate
gap between the points is unknown, the gap is plus or minus a square root. When both gaps are unknown, a linear
relation over the same two unknowns (a line through the point) gives the crossing of that line with the circle; a
second circle around the same point gives that line first (the line through both crossings). The drawing picks the
crossing, and the choice is recorded with the square root's argument as its guard.

`Crossings` is a part of the solver (`solve._Solver`): it uses its slots, its relations and its checks.
"""
from ..sketch_values.expr import ExprDomainError, sqrt
from .slots import Dist, Lin, Rel, slot_text, x, y

_MATH_ERRORS = (ExprDomainError, ZeroDivisionError, OverflowError, ValueError)


class Conflict(Exception):
    """The sketch's rules disagree with each other or with the drawing; the text says where."""


class Crossings:
    def _distances(self):
        for item in list(self.items):
            if not isinstance(item, Dist):
                continue
            rho_unknown, rho = self.slots.reduce(item.rho)
            if rho_unknown:
                continue
            u_unknown, u = self.slots.reduce(Lin({x(item.a): 1.0, x(item.b): -1.0}))
            w_unknown, w = self.slots.reduce(Lin({y(item.a): 1.0, y(item.b): -1.0}))
            if not u_unknown and not w_unknown:
                if not self._zero_everywhere(u * u + w * w - rho * rho, rho * rho):
                    raise Conflict("%s does not agree with the other rules when the sizes change" % item.source)
                self.items.remove(item)
                continue
            if self._distance_one(item, rho, u_unknown, u, w_unknown, w):
                self.items.remove(item)
                return True
            if self._distance_two(item, rho, u_unknown, u, w_unknown, w):
                return True
        return False

    def _base_gap(self, item):
        (ax, ay), (bx, by) = self.g.xy(item.a), self.g.xy(item.b)
        return ax - bx, ay - by

    def _distance_one(self, item, rho, u_unknown, u, w_unknown, w):
        """One coordinate gap known: the other is plus or minus the square root."""
        if len(u_unknown) + len(w_unknown) != 1 or set(u_unknown) & set(w_unknown):
            return False
        gaps = self._base_gap(item)
        if u_unknown:
            (root, a), known, base, axis = next(iter(u_unknown.items())), w, gaps[0], "x"
            const = u
        else:
            (root, a), known, base, axis = next(iter(w_unknown.items())), u, gaps[1], "y"
            const = w
        if abs(base) <= self.tol or abs(self._at_base(a)) <= 1e-9:
            return False
        side = 1.0 if base > 0 else -1.0
        inside = rho * rho - known * known
        self._assume("%s: the %s gap keeps its sign" % (item.source, axis), inside, "point %d" % item.a)
        gap = sqrt(inside).scaled(side)
        if not a.is_constant:
            self._assume("%s divides by a value that must not reach zero" % item.source,
                         a.scaled(1.0 if self._at_base(a) > 0 else -1.0), slot_text(root))
        self._assign(root, (gap - const) / a, item.source)
        return True

    def _distance_two(self, item, rho, u_unknown, u, w_unknown, w):
        """Both gaps unknown, each in one unknown of its own: crossing with a line through the same two unknowns, or
        first the line through two circles' crossings."""
        if len(u_unknown) != 1 or len(w_unknown) != 1 or set(u_unknown) == set(w_unknown):
            return False
        (r1, a1), = u_unknown.items()
        (r2, a2), = w_unknown.items()
        for other in self.items:
            if isinstance(other, Rel):
                unknown, const = self.slots.reduce(other.lin)
                if set(unknown) == {r1, r2}:
                    return self._line_circle(item, other, rho, (r1, a1, u), (r2, a2, w), unknown, const)
        for other in self.items:
            if other is item or not isinstance(other, Dist):
                continue
            rho2_unknown, rho2 = self.slots.reduce(other.rho)
            if rho2_unknown:
                continue
            for first, second in ((other.a, other.b), (other.b, other.a)):
                u2_unknown, u2 = self.slots.reduce(Lin({x(first): 1.0, x(second): -1.0}))
                w2_unknown, w2 = self.slots.reduce(Lin({y(first): 1.0, y(second): -1.0}))
                if set(u2_unknown) != {r1} or set(w2_unknown) != {r2}:
                    continue
                if not (u2_unknown[r1].same(a1) and w2_unknown[r2].same(a2)):
                    continue
                # (U + u)^2 - (U + u2)^2 + (W + w)^2 - (W + w2)^2 = rho^2 - rho2^2, with U = a1 r1 and W = a2 r2
                lin = Lin({r1: a1 * (u - u2) * 2.0, r2: a2 * (w - w2) * 2.0},
                          u * u - u2 * u2 + w * w - w2 * w2 - rho * rho + rho2 * rho2)
                self._add(Rel(lin, "%s and %s" % (item.source, other.source)))
                return True
        return False

    def _line_circle(self, item, line, rho, first, second, unknown, const):
        (r1, a1, u0), (r2, a2, w0) = first, second
        p, q = unknown[r1], unknown[r2]
        # p r1 + q r2 + const = 0, with u = a1 r1 + u0 and w = a2 r2 + w0: alpha u + beta w = gamma
        alpha, beta = p / a1, q / a2
        gamma = alpha * u0 + beta * w0 - const
        norm = alpha * alpha + beta * beta
        inside = rho * rho * norm - gamma * gamma
        foot_u, foot_w = gamma * alpha / norm, gamma * beta / norm
        half = sqrt(inside) / norm
        bu, bw = self._base_gap(item)
        try:
            h0 = self._at_base(half)
            fu, fw = self._at_base(foot_u), self._at_base(foot_w)
            bx, by = self._at_base(beta), self._at_base(alpha)
        except _MATH_ERRORS:
            return False
        choices = [s for s in (1.0, -1.0) if abs(fu - s * h0 * bx - bu) <= self.tol * 10 and
                   abs(fw + s * h0 * by - bw) <= self.tol * 10]
        if len(choices) != 1:
            if not choices:
                raise Conflict("%s and %s cross away from the drawn point %d" % (item.source, line.source, item.a))
            return False
        side = choices[0]
        where = "point %d" % item.a
        self._assume("%s meets %s on the side the drawing shows" % (line.source, item.source), inside, where)
        for coef in (a1, a2, norm):
            if not coef.is_constant:
                self._assume("%s divides by a value that must not reach zero" % item.source,
                             coef.scaled(1.0 if self._at_base(coef) > 0 else -1.0), where)
        uu = foot_u - half * beta * side
        ww = foot_w + half * alpha * side
        self._assign(r1, (uu - u0) / a1, "%s and %s" % (item.source, line.source))
        self._assign(r2, (ww - w0) / a2, "%s and %s" % (item.source, line.source))
        return True
