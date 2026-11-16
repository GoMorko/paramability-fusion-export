"""The whole recipe (`CadDocument` as Orca saves it) and its bytes.

Framed layout (version 5 and 6, the same bytes):
    uint32 version, uint32 feature count,
    per feature: uint32 length, then that many bytes holding the feature's fields,
    uint32 length + the variables (map of name to formula),
    uint32 length + the user's body names (map of body index to name), optional,
    uint32 length + extras: modeling origin x, y, z (doubles), body colours (map of body index to 4 floats
        r, g, b, a), auto close sketch loops (bool), optional.
Orca reads what a block holds and leaves the rest at defaults, so short blocks and missing trailing blocks open.

Unframed layout (version 4, and the older 3 that Orca 2.5 refuses): uint32 version, a size tag with the feature
count, the features back to back with the field list of that version, then the variables map.
"""
from .cereal import Reader, RecipeFormatError, ShortRead, Writer
from .feature import FIELD_COUNT_V3, FIELD_COUNT_V4, read_feature_block, read_feature_flat, write_feature

RECIPE_VERSION = 6
FRAMED_VERSIONS = (5, 6)
FLAT_FIELD_COUNTS = {3: FIELD_COUNT_V3, 4: FIELD_COUNT_V4}


class Recipe:
    """A recipe: features, variables and the document extras.

    `body_names` and `extras` None mean the block is absent (an older file); a new recipe writes both.
    `block_tails` keeps bytes a block holds after what this code reads, `trailing` bytes after the last block.
    """

    def __init__(self, features=None, variables=None, version=RECIPE_VERSION):
        self.version = version
        self.features = list(features or [])
        self.variables = dict(variables or {})
        self.body_names = {}
        self.modeling_origin = (0.0, 0.0, 0.0)
        self.body_colours = {}
        self.auto_close_loops = True
        self.has_extras = True
        self.block_tails = {"variables": b"", "body_names": b"", "extras": b""}
        self.trailing = b""

    def add(self, feature):
        """Append a feature; returns its index, the number later features refer to it by."""
        self.features.append(feature)
        return len(self.features) - 1


def serialize(recipe):
    """The recipe's bytes in the layout of its version."""
    if recipe.version in FRAMED_VERSIONS:
        return _serialize_framed(recipe)
    if recipe.version in FLAT_FIELD_COUNTS:
        return _serialize_flat(recipe, FLAT_FIELD_COUNTS[recipe.version])
    raise RecipeFormatError("no layout for recipe version %r" % recipe.version)


def deserialize(data):
    """A Recipe from bytes of any layout this code knows. Raises RecipeFormatError."""
    r = Reader(data)
    try:
        version = r.u32()
        if version in FRAMED_VERSIONS:
            return _deserialize_framed(r, version)
        if version in FLAT_FIELD_COUNTS:
            return _deserialize_flat(r, version, FLAT_FIELD_COUNTS[version])
    except ShortRead as e:
        raise RecipeFormatError("the recipe ends early: %s" % e) from None
    raise RecipeFormatError("unknown recipe version %d" % version)


def _block(w, body):
    w.u32(len(body))
    w.raw(body)


def _serialize_framed(recipe):
    w = Writer()
    w.u32(recipe.version)
    w.u32(len(recipe.features))
    for feature in recipe.features:
        fw = Writer()
        write_feature(fw, feature)
        _block(w, fw.getvalue())
    vw = Writer()
    vw.string_map(recipe.variables)
    vw.raw(recipe.block_tails["variables"])
    _block(w, vw.getvalue())
    if recipe.body_names is not None:
        bw = Writer()
        bw.size(len(recipe.body_names))
        for index in sorted(recipe.body_names):
            bw.u32(index)
            bw.string(recipe.body_names[index])
        bw.raw(recipe.block_tails["body_names"])
        _block(w, bw.getvalue())
        if recipe.has_extras:
            xw = Writer()
            for v in recipe.modeling_origin:
                xw.f64(v)
            xw.size(len(recipe.body_colours))
            for index in sorted(recipe.body_colours):
                xw.u32(index)
                for c in recipe.body_colours[index]:
                    xw.f32(c)
            xw.bool(recipe.auto_close_loops)
            xw.raw(recipe.block_tails["extras"])
            _block(w, xw.getvalue())
    w.raw(recipe.trailing)
    return w.getvalue()


def _read_block(r):
    return Reader(r.raw(r.u32()))


def _deserialize_framed(r, version):
    recipe = Recipe(version=version)
    recipe.features = [read_feature_block(_read_block(r)) for _ in range(r.u32())]
    vr = _read_block(r)
    recipe.variables = vr.string_map()
    recipe.block_tails["variables"] = vr.rest()
    recipe.body_names = None
    recipe.has_extras = False
    if r.at_end():
        return recipe
    br = _read_block(r)
    names = {}
    for _ in range(br.size()):
        index = br.u32()
        names[index] = br.string()
    recipe.body_names = names
    recipe.block_tails["body_names"] = br.rest()
    if r.at_end():
        return recipe
    xr = _read_block(r)
    recipe.modeling_origin = (xr.f64(), xr.f64(), xr.f64())
    colours = {}
    for _ in range(xr.size()):
        index = xr.u32()
        colours[index] = (xr.f32(), xr.f32(), xr.f32(), xr.f32())
    recipe.body_colours = colours
    recipe.auto_close_loops = xr.bool()
    recipe.has_extras = True
    recipe.block_tails["extras"] = xr.rest()
    recipe.trailing = r.rest()
    return recipe


def _serialize_flat(recipe, count):
    w = Writer()
    w.u32(recipe.version)
    w.size(len(recipe.features))
    for feature in recipe.features:
        write_feature(w, feature, limit=count)
    w.string_map(recipe.variables)
    w.raw(recipe.trailing)
    return w.getvalue()


def _deserialize_flat(r, version, count):
    recipe = Recipe(version=version)
    recipe.features = [read_feature_flat(r, count) for _ in range(r.size())]
    recipe.variables = r.string_map()
    recipe.body_names = None
    recipe.has_extras = False
    recipe.trailing = r.rest()
    return recipe
