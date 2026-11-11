"""Copy Paste Body features as plain dicts (docs/capture-format.md).

The bodies that were copied (`sourceBody`, a collection) are read with the timeline marker just before the item: Fusion
needs it there, and some can be gone later. The bodies the paste made are read with the marker just after it. All come
with their first vertex points, so the translator can pair each result with its source and tell how it sits against
it. A source that cannot be read is left out of `sources` and results that cannot be read are null; the translator
refuses when the two lists do not pair up.
"""
from . import read_geometry as geo
from .read_bodies import result_bodies, with_points


def _copied_bodies(feature):
    """The bodies the paste copied. Fusion documents a collection; a single body is accepted too."""
    found = geo.safe(lambda: feature.sourceBody, None)
    return [found] if geo.type_name(found) == "BRepBody" else geo.collection_items(found)


def paste_before(feature, ctx):
    read = [geo.safe(lambda: with_points(body, ctx), None) for body in _copied_bodies(feature)]
    return {"sources": [found for found in read if found is not None], "result_bodies": None}


def paste_after(feature, ctx, data):
    return {"result_bodies": result_bodies(feature, ctx)}


# type name -> (before, after); either may be None
READERS = {
    "CopyPasteBody": (paste_before, paste_after),
}
