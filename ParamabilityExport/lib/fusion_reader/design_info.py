"""Design name, Fusion version, up direction and default length unit."""
import adsk.core


def document_name(app):
    doc = app.activeDocument
    return doc.name if doc else ""


def fusion_version(app):
    return app.version or ""


def detect_up_axis(app):
    """"y" or "z". Reads the modeling orientation preference; the dialog lets the person correct it."""
    try:
        orientation = app.preferences.generalPreferences.defaultModelingOrientation
        if orientation == adsk.core.DefaultModelingOrientations.YUpModelingOrientation:
            return "y"
    except Exception:
        pass
    return "z"


def default_length_unit(design):
    """The design's default length unit, which a bare number in a length formula is read in."""
    try:
        return design.fusionUnitsManager.defaultLengthUnits or "mm"
    except Exception:
        return "mm"
