"""The owner's filter box parameters (names and formulas from a Fusion screenshot), as reader dicts."""
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


def reader_dicts():
    design = FakeDesign([])
    design._params = [FakeFusionParam(r) for r in RAW]
    design.userParameters._items = design._params
    design.userParameters.count = len(design._params)
    return list_user_parameters(design)
