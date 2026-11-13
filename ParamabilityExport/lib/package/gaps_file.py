"""The gaps file of a package: the steps the recipe leaves out, with where each belongs and the Fusion data it had.

One file per recipe (`gaps.json`, or `parts/NN/gaps.json` in a parts package). The manifest names it, and a package
that names one is version 2 (`manifest.VERSION_WITH_GAPS`).

The file is version 1 when it holds at most VERSION_ONE_GAPS gaps, so it still opens in an app that reads only
version 1, and version 2 (which allows up to `translator.gaps.stops.MAX_GAPS`) when it holds more.
"""
import json

from .caps import MAX_GAPS_BYTES

SCHEMA = "paramability.recipeGaps"
VERSION_ONE_GAPS = 16


def build_gaps_file(gaps, to_recipe):
    """The file as a dict. `gaps` are the translator's gap records, `to_recipe` the 12 numbers that map the capture's
    coordinates to the recipe's."""
    gaps = list(gaps)
    version = 1 if len(gaps) <= VERSION_ONE_GAPS else 2
    return {"schema": SCHEMA, "version": version, "toRecipe": list(to_recipe), "gaps": gaps}


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
