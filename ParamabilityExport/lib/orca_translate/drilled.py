"""Circle holes in the first outline of the part, drilled as Orca holes so that their centres follow sizes.

The first body of the part keeps the holes of its outline as cuts through it (`steps.extrude`). A circle hole is an
Orca circle sketch cut through all: its radius may follow a variable, but its sketch plane cannot move, so a centre
that sizes move would keep its place in Orca. An Orca Hole has bound fields for its place (`hole_x`, `hole_y`) on its
plane and for its diameter. So a circle hole whose centre moves is drilled instead: on the sketch plane, along the
extrude's direction, through all, at the centre's sketch coordinates as formulas of the sizes.

Orca drills a hole from its plane along the plane's normal only. The sketch plane is the base of a one sided extrude
without taper, and the whole body lies on the side it extrudes to, so the hole goes through all of it. Other extents
(symmetric, two sides, through all) put material on both sides of the sketch plane, and their holes stay cuts.
"""
from ..geometry import vec
from ..orca_recipe.enums import ExtrudeEnd, FeatureType
from ..orca_recipe.feature import CadFeature
from ..design_model.values import Quantity
from .hole_place import Place
from .sketches import reads_input


def drill(made, formulas, frame, side):
    """Turn a circle hole (`sketches.SketchOut`) whose centre moves into a drilled one: sets `made.drill` (the
    `hole_place.Place` and the diameter `Quantity`), adds the place to `made.bound` and clears `made.moves`. Returns
    whether it did; it does not when the extrude is not one sided without taper, or a centre or radius formula cannot
    be written exactly."""
    if made.shape != "circle" or not made.moves or formulas is None or made.centre is None:
        return False
    if side.end != ExtrudeEnd.BLIND or side.through or side.taper:
        return False
    coordinates = []
    for expr, number in zip(made.centre, made.at):
        if expr is None or reads_input(expr):
            return False
        formulas.why = ""
        found = formulas.sized(expr, number)
        if found is None and formulas.why:
            formulas.why = ""
            return False
        coordinates.append(Quantity(number) if found is None else Quantity(number, *found))
    sign = -1.0 if side.flip else 1.0
    radius = made.feature.radius
    diameter = Quantity(2.0 * radius)
    if "radius" in made.bound:
        formula, reads = made.bound["radius"]
        diameter = Quantity(2.0 * radius, "2 * (%s)" % formula, reads)
    x = vec.unit(list(frame["x"]))
    y = vec.scale(vec.unit(list(frame["y"])), sign)
    normal = vec.scale(vec.unit(list(frame["z"])), sign)
    place = Place(frame["origin"], x, y, normal, coordinates[0], coordinates[1].scaled(sign))
    made.drill = (place, diameter)
    for field, value in (("hole_x", place.x_value), ("hole_y", place.y_value)):
        if value.text is not None:
            made.bound[field] = (value.text, value.reads)
    made.moves = ()
    return True


def write(ctx, made, name):
    """The Orca Hole of a drilled circle (`drill`), through all from the sketch plane, its fields bound."""
    place, diameter = made.drill
    feature = CadFeature(type=FeatureType.HOLE, name=name, plane=place.plane(ctx.place), hole_style=0,
                         hole_through=True, thread_major_nominal=True, pattern_inclusive=True)
    ctx.bind(feature, "hole_x", place.x_value, "%s place" % name)
    ctx.bind(feature, "hole_y", place.y_value, "%s place" % name)
    ctx.bind(feature, "hole_diameter", diameter, "%s diameter" % name)
    ctx.add(feature)
    return feature
