"""The gaps file of a package: the steps the recipe leaves out, with where each belongs and the Fusion data it had.

One file per recipe (`gaps.json`, or `parts/NN/gaps.json` in a parts package). The manifest names it, and a package
that names one is version 2 (`manifest.VERSION_WITH_GAPS`).
"""
import json

from .caps import MAX_GAPS_BYTES

SCHEMA = "paramability.recipeGaps"
VERSION = 1


def build_gaps_file(gaps, to_recipe):
    """The file as a dict. `gaps` are the translator's gap records, `to_recipe` the 12 numbers that map the capture's
    coordinates to the recipe's."""
    return {"schema": SCHEMA, "version": VERSION, "toRecipe": list(to_recipe), "gaps": list(gaps)}


def _encode(file):
    return json.dumps(file, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def gaps_file_bytes(gaps, to_recipe):
    """UTF-8 bytes of the gaps file, or None when it cannot be written or does not fit the cap. A file over the cap
    is tried once more without the Fusion data of the gaps (each then says `trimmed`)."""
    if not gaps or to_recipe is None:
        return None
    try:
        data = _encode(build_gaps_file(gaps, to_recipe))
        if len(data) > MAX_GAPS_BYTES:
            bare = [dict(gap, data={}, trimmed=True) for gap in gaps]
            data = _encode(build_gaps_file(bare, to_recipe))
    except (TypeError, ValueError):
        return None
    return data if len(data) <= MAX_GAPS_BYTES else None
