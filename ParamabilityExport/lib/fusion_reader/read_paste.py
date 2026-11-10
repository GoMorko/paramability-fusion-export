"""Copy Paste Body features as plain dicts (docs/capture-format.md).

The body that was copied (`sourceBody`) is read with the timeline marker just before the item: Fusion needs it there,
and it can be gone later. The bodies the paste made are read with the marker just after it. Both come with their
first vertex points, so the translator can tell how the pasted body sits against its source. A source that cannot be
read leaves `sources` empty and a result that cannot be read is null; the translator refuses both.
"""
from . import read_geometry as geo
from .read_bodies import result_bodies, with_points


def paste_before(feature, ctx):
    source = geo.safe(lambda: feature.sourceBody, None)
    found = geo.safe(lambda: with_points(source, ctx), None) if source is not None else None
    return {"sources": [found] if found is not None else [], "result_bodies": None}


def paste_after(feature, ctx, data):
    return {"result_bodies": result_bodies(feature, ctx)}


# type name -> (before, after); either may be None
READERS = {
    "CopyPasteBody": (paste_before, paste_after),
}
