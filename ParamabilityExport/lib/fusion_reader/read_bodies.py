"""Body records for the steps that copy or move bodies: tools of a Combine, a Paste, a body pattern, a Move.

A record is `{ token, name }` (`geo.body_ref`). A body of another component also names its native `token`, its
`component` and the occurrence `path` (`placement.tool_identity`), so the steps that made it can be found and read.
`points` are the first vertices of the body in its own component's coordinates, in the body's vertex order: the
translator matches a body before and after a step by them. A body with no vertices (a sphere, a torus) is followed by
its box instead (`box_of`).
"""
from . import read_geometry as geo
from .placement import tool_identity


def tool_ref(body, ctx):
    """The body ref of `body`; one of another component is marked `foreign` and carries its identity."""
    ref = geo.body_ref(body, ctx)
    if ref.get("foreign"):
        ref.update(geo.safe(lambda: tool_identity(body), {}))
    return ref


def with_points(body, ctx):
    """`tool_ref` plus the `points` of the body (empty when they cannot be read)."""
    ref = tool_ref(body, ctx)
    ref["points"] = geo.vertex_points(geo.native_object(body))
    return ref


def points_of(ctx, token):
    """The vertex points of the body with this token at the current marker position, or [] when it is not found."""
    body = geo.find_native(ctx.design, token) if token else None
    return geo.vertex_points(body) if body is not None else []


def box_of(body):
    """The box `{min, max}` of a body in its own component's coordinates, or None when it cannot be read."""
    return geo.safe(lambda: geo.box_of(geo.native_object(body)), None)


def box_by_token(ctx, token):
    """The box of the body with this token at the current marker position, or None when it is not found or read."""
    body = geo.find_native(ctx.design, token) if token else None
    return box_of(body) if body is not None else None


def result_bodies(feature, ctx):
    """`with_points` of each body a feature made, read with the marker just after it; None when the list cannot be
    read."""
    return geo.safe(lambda: [with_points(b, ctx) for b in
                             (feature.bodies.item(i) for i in range(feature.bodies.count))], None)
