"""A simple polygon as a formula of the half-planes of its edges, each edge used once, and the check that the formula
still gives the polygon when its corners move.

A corner of a counter clockwise polygon where the outline turns left (a convex corner) joins its two edges with
"and": the inside lies left of both. Where it turns right (an inward corner) it joins them with "or". Over a whole
polygon these joins nest. The formula is found as Dobkin, Guibas, Hershberger and Snoeyink describe ("An efficient
algorithm for finding the CSG representation of a simple polygon", 1988): split the outline into two chains at its
lowest and highest corner, and split each chain at a corner whose two edges, carried on as rays, meet no other edge
of the chain. Each part is solved the same way; the corner where it was split decides "and" or "or". Of the corners
where a chain may be split, the copy takes the one that nests the formula least.

A node is `("lit", i)`, the half-plane left of edge `i` (from corner `i` to corner `i + 1`), or `("and", kids)` and
`("or", kids)`, where the kids of an "and" are literals and "or" nodes, and the other way round.

`check` compares the formula with the polygon at a point of every cell of the lines through the edges: inside each
cell the formula has one answer, so agreement at one point of each cell is agreement everywhere. The copy builds an
outline from this formula with plane cuts (`outline_cuts`), and checks it again at other values of the variables,
since corners that move can make the same formula give another shape.

Pure numbers: points are `(x, y)` tuples in mm.
"""
import math

# Rays are carried this far (in lengths of their edge) when a split corner is tested.
_FAR = 1e7
# A ray meets an edge only when it crosses it this far (in lengths of the edge) inside its ends.
_INNER = 1e-7
# Lines closer to a point of the arrangement than this share of the outline's size pass through it.
_THROUGH = 1e-9
# A sample of a cell lies this share of the way to the nearest line that does not pass through its point, and never
# further than `_REACH` times the outline's size.
_SHARE = 0.3
_REACH = 1e-3


def area(points):
    """The signed area of a loop: above zero for a counter clockwise loop."""
    n = len(points)
    return 0.5 * sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n))


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def simple(points, shortest=0.0):
    """True when the closed loop has at least three corners, every edge is longer than `shortest`, and no two edges
    meet except neighbours at their shared corner."""
    n = len(points)
    if n < 3:
        return False
    edges = [(points[i], points[(i + 1) % n]) for i in range(n)]
    if any(math.hypot(*_sub(b, a)) <= shortest for a, b in edges):
        return False
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                if _folds_back(edges[i], edges[j], i == 0 and j == n - 1):
                    return False
                continue
            if _segments_meet(edges[i], edges[j]):
                return False
    return True


def _folds_back(first, second, wrapped):
    """True when two neighbouring edges run back over each other."""
    a, b = (second, first) if wrapped else (first, second)
    d1, d2 = _sub(a[1], a[0]), _sub(b[1], b[0])
    size = math.hypot(*d1) * math.hypot(*d2)
    return abs(_cross(d1, d2)) <= 1e-12 * size and d1[0] * d2[0] + d1[1] * d2[1] < 0


def _segments_meet(s, t):
    (a, b), (c, d) = s, t
    d1, d2 = _sub(b, a), _sub(d, c)
    den = _cross(d1, d2)
    w = _sub(c, a)
    if abs(den) <= 1e-12 * math.hypot(*d1) * math.hypot(*d2):
        if abs(_cross(w, d1)) > 1e-12 * math.hypot(*d1) * (math.hypot(*w) + 1.0):
            return False
        length = d1[0] * d1[0] + d1[1] * d1[1]
        lo = (w[0] * d1[0] + w[1] * d1[1]) / length
        hi = ((d[0] - a[0]) * d1[0] + (d[1] - a[1]) * d1[1]) / length
        return max(lo, hi) >= 0.0 and min(lo, hi) <= 1.0
    s_at = _cross(w, d2) / den
    t_at = _cross(w, d1) / den
    return -1e-12 <= s_at <= 1 + 1e-12 and -1e-12 <= t_at <= 1 + 1e-12


def _ray_meets(p, d, q, e, qlo, qhi):
    """True when the ray `p + s d` (s above zero) crosses the piece `q + u e`, u in [qlo, qhi], inside its ends."""
    den = _cross(d, e)
    if abs(den) < 1e-12 * (math.hypot(*d) * math.hypot(*e)):
        return False  # parallel: a ray along the line of another edge does not split it
    w = _sub(q, p)
    s = _cross(w, e) / den
    u = _cross(w, d) / den
    return _INNER < s < _FAR - _INNER and qlo - _INNER < u < qhi + _INNER


def formula(points):
    """The formula of the counter clockwise simple polygon `points` (each edge once), or None when no split is
    found. Among the corners where a chain may be split, the one that nests the formula least is taken (then the one
    with the fewest "and" and "or" nodes), so the copy needs few tool bodies, nested shallowly. A polygon of more than
    `_SEARCH_MAX` corners takes the first split nearest the middle of each chain."""
    n = len(points)
    search = n <= _SEARCH_MAX
    memo = {}

    def piece(j, first, last):
        a, b = points[j % n], points[(j + 1) % n]
        return a, _sub(b, a), (-_FAR if first else 0.0), (_FAR if last else 1.0)

    def splits(chain):
        """(k, op) of each corner `chain[k]` where the chain may be split."""
        pieces = [piece(j, k == 0, k == len(chain) - 1) for k, j in enumerate(chain)]
        middle = len(chain) / 2.0
        for k in sorted(range(1, len(chain)), key=lambda k: abs(k - middle)):
            v = points[chain[k] % n]
            u, w = points[chain[k - 1] % n], points[(chain[k] + 1) % n]
            ahead, back = _sub(v, u), _sub(v, w)
            if any((m != k - 1 and _ray_meets(v, ahead, *pieces[m])) or (m != k and _ray_meets(v, back, *pieces[m]))
                   for m in range(len(pieces))):
                continue
            yield k, "and" if _cross(ahead, _sub(w, v)) > 0 else "or"

    def solve(chain):
        """The trees of a chain by their top node: `{"lit" | "and" | "or": tree}`, the best of each kind."""
        key = (chain[0], len(chain))
        if key in memo:
            return memo[key]
        found = {"lit": ("lit", chain[0] % n)} if len(chain) == 1 else {}
        for k, op in splits(chain) if len(chain) > 1 else ():
            left, right = solve(chain[:k]), solve(chain[k:])
            if not left or not right:
                continue
            tree = (op, _flat(op, [_pick(left, op), _pick(right, op)]))
            if op not in found or _cost(tree) < _cost(found[op]):
                found[op] = tree
            if not search:
                break
        memo[key] = found
        return found

    low = min(range(n), key=lambda i: (points[i][0], points[i][1]))
    high = max(range(n), key=lambda i: (points[i][0], points[i][1]))
    chains = (tuple(range(low, high if high > low else high + n)), tuple(range(high, low if low > high else low + n)))
    found = [solve(chain) for chain in chains]
    if not all(found):
        return None
    return ("and", _flat("and", [_pick(options, "and") for options in found]))


# Polygons up to this many corners get the search for the least nested formula; it takes time as the fourth power
# of the corners.
_SEARCH_MAX = 40


def _pick(options, op):
    """The tree of `options` (by top node) that adds the least nesting under a node of `op`: one with the same top
    node merges into it."""
    def under(tree):
        if tree[0] == "lit":
            return (0, 0)
        depth, nodes = _cost(tree)
        return (depth, nodes) if tree[0] == op else (depth + 1, nodes + 1)
    return min(options.values(), key=under)


def _cost(tree):
    """(depth, number of "and" and "or" nodes below the top one) of a tree."""
    if tree[0] == "lit":
        return (0, 0)
    kids = [k for k in tree[1] if k[0] != "lit"]
    costs = [_cost(k) for k in kids]
    return (1 + max(c[0] for c in costs) if costs else 0, len(kids) + sum(c[1] for c in costs))


def _flat(op, parts):
    kids = []
    for part in parts:
        kids += part[1] if part[0] == op else [part]
    return kids


def holds(node, inside):
    """The formula's answer when `inside[i]` says whether a point lies left of edge `i`."""
    if node[0] == "lit":
        return inside[node[1]]
    if node[0] == "and":
        for kid in node[1]:
            if not holds(kid, inside):
                return False
        return True
    for kid in node[1]:
        if holds(kid, inside):
            return True
    return False


def depth(node):
    """How many "or" and "and" levels lie below the top node (0 for a convex polygon)."""
    kids = [k for k in node[1] if k[0] != "lit"] if node[0] != "lit" else []
    return 1 + max(depth(k) for k in kids) if kids else 0


def in_polygon(points, x):
    """True when `x` lies inside the loop (even and odd crossings)."""
    odd = False
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        if (a[1] > x[1]) != (b[1] > x[1]) and x[0] < a[0] + (x[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
            odd = not odd
    return odd


def _lines(points):
    n = len(points)
    out = []
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        d = _sub(b, a)
        length = math.hypot(*d)
        out.append((a, (d[0] / length, d[1] / length)))
    return out


def _gap(line, x):
    """Signed distance of `x` from a line, above zero on its left."""
    a, d = line
    return _cross(d, _sub(x, a))


def samples(points):
    """A point inside every cell of the lines through the edges of the loop: around each point where lines cross,
    one between each two neighbouring rays of the lines through it."""
    return list(line_samples(_lines(points), max(max(abs(c) for c in p) for p in points) or 1.0))


def line_samples(lines, size):
    """A point inside every cell of `lines` ((point, unit direction) pairs) that has a corner, as `samples` gives
    them, one at a time. `size` is the size of the region the lines bound, for the tolerances."""
    near = _THROUGH * size
    flat = [(a[0], a[1], d[0], d[1]) for a, d in lines]
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            (p, d), (q, e) = lines[i], lines[j]
            den = _cross(d, e)
            if abs(den) < 1e-12:
                continue
            s = _cross(_sub(q, p), e) / den
            x = (p[0] + s * d[0], p[1] + s * d[1])
            x0, x1 = x
            gaps = [abs(dx * (x1 - ay) - dy * (x0 - ax)) for ax, ay, dx, dy in flat]
            through = [k for k, g in enumerate(gaps) if g <= near]
            if through[:2] != [i, j]:
                continue  # this crossing is sampled from the first two of its lines
            held = set(through)
            rest = [g for k, g in enumerate(gaps) if k not in held]
            reach = min([_REACH * size] + [_SHARE * g for g in rest])
            rays = sorted({round(math.atan2(lines[k][1][1] * sign, lines[k][1][0] * sign) % (2 * math.pi), 12)
                           for k in through for sign in (1.0, -1.0)})
            for at, ray in enumerate(rays):
                after = rays[(at + 1) % len(rays)] + (2 * math.pi if at + 1 == len(rays) else 0.0)
                mid = (ray + after) / 2.0
                yield (x[0] + reach * math.cos(mid), x[1] + reach * math.sin(mid))


# What `check` answered, by the formula and the points as written out: the same polygon at the same numbers always
# gives the same answer, and the limit walks ask for the same polygons again and again.
_CHECKED = {}
_CHECKED_MAX = 50000


def check(points, node):
    """True when the formula gives the polygon at a point of every cell of the edge lines."""
    key = repr((node, points))
    found = _CHECKED.get(key)
    if found is None:
        found = _agrees(points, node)
        if len(_CHECKED) >= _CHECKED_MAX:
            _CHECKED.clear()
        _CHECKED[key] = found
    return found


def _agrees(points, node):
    lines = _lines(points)
    flat = [(a[0], a[1], d[0], d[1]) for a, d in lines]
    for x in line_samples(lines, max(max(abs(c) for c in p) for p in points) or 1.0):
        x0, x1 = x
        inside = [dx * (x1 - ay) - dy * (x0 - ax) > 0 for ax, ay, dx, dy in flat]
        if holds(node, inside) != in_polygon(points, x):
            return False
    return True
