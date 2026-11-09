"""The filter box design's parameters (names with `$`, formulas over a count and a cube width), as reader dicts."""
from lib.fusion_reader.parameters import list_user_parameters
from tests.fakes import FakeDesign

W = "FilterBox_$_width__contains_CeramicMedium"
H = "FilterBox_$_height__contains_CeramicMedium"
D = "FilterBox_$_depth__contains_CeramicMedium"
CUBE = "_CeramicMedium__Cube_width_mm"
CUBE_MM = 18.0


def mm(value):
    return value / 10.0


def _plain(name, expression, value, unit, **extra):
    return dict(name=name, expression=expression, value=value, unit=unit, comment=extra.pop("comment", ""),
                isFavorite=extra.pop("isFavorite", False), **extra)


RAW = [
    _plain(W, "1.8", 1.8, "", isFavorite=True),
    _plain(H, "1.2", 1.2, "", isFavorite=True),
    _plain(D, "1.8", 1.8, "", isFavorite=True),
    _plain(CUBE, "18 mm", mm(CUBE_MM), "mm", isFavorite=True),
    _plain("FilterBox_width_mm", f"{W} * {CUBE} + 2 mm", mm(34.4), "mm"),
    _plain("FilterBox_height_mm", f"{H} * {CUBE}", mm(21.6), "mm"),
    _plain("FilterBox_depth_mm", f"{D} * {CUBE} + 2 mm", mm(34.4), "mm"),
    _plain("FilterBox__PipeTop_offsetFromCenter_mm", "0.05 mm", mm(0.05), "mm"),
    _plain("FilterBox__PipeBottom_offsetFromCenter_mm", "0.05 mm", mm(0.05), "mm"),
]

DEPENDENCIES = {
    "FilterBox_width_mm": [W, CUBE],
    "FilterBox_height_mm": [H, CUBE],
    "FilterBox_depth_mm": [D, CUBE],
}


class FakeFusionParam:
    """A parameter object with dependencyParameters as a plain list of named objects."""

    def __init__(self, raw):
        self.__dict__.update(raw)
        self.dependencyParameters = [type("P", (), {"name": n}) for n in DEPENDENCIES.get(raw["name"], [])]


def reader_dicts(raw=None, dependencies=None):
    """`raw` and `dependencies` default to the filter box."""
    deps = DEPENDENCIES if dependencies is None else dependencies

    class Param(FakeFusionParam):
        def __init__(self, r):
            self.__dict__.update(r)
            self.dependencyParameters = [type("P", (), {"name": n}) for n in deps.get(r["name"], [])]

    design = FakeDesign([])
    design._params = [Param(r) for r in (RAW if raw is None else raw)]
    design.userParameters._items = design._params
    design.userParameters.count = len(design._params)
    return list_user_parameters(design)


# A hobby storage box: unitless counts, a count turned into a length with `* 1 mm`, a setup value only read by other
# formulas, a chain three deep, an `if` on an intermediate, a plain number formula in a length, and a weight in grams.
HOBBY_RAW = [
    _plain("cols", "4", 4, "", isFavorite=True),
    _plain("rows", "3", 3, "", isFavorite=True),
    _plain("layers", "3", 3, ""),
    _plain("grid", "42 mm", mm(42), "mm"),
    _plain("clearance", "0.25 mm", mm(0.25), "mm", comment="Setup: gap per side"),
    _plain("cols_mm", "cols * 1 mm", mm(4), "mm"),
    _plain("wall", "layers * 0.4", mm(1.2), "mm"),
    _plain("width", "cols * grid - clearance * 2", mm(167.5), "mm"),
    _plain("inner", "width - wall * 2", mm(165.1), "mm"),
    _plain("lip", "if(inner > 100 mm; 3 mm; 2 mm)", mm(3), "mm"),
    _plain("lip_ratio", "lip / clearance", 12, ""),
    _plain("spacing", "cols_mm + rows * 1 mm + lip", mm(10), "mm"),
    _plain("weight", "50 g", 0.05, "g"),
]

HOBBY_DEPENDENCIES = {
    "cols_mm": ["cols"], "wall": ["layers"], "width": ["cols", "grid", "clearance"], "inner": ["width", "wall"],
    "lip": ["inner"], "lip_ratio": ["lip", "clearance"], "spacing": ["cols_mm", "rows", "lip"],
}


def hobby_dicts():
    return reader_dicts(HOBBY_RAW, HOBBY_DEPENDENCIES)
