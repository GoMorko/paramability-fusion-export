"""Design name, Fusion version and up direction."""
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
