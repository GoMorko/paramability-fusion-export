"""File and display names."""
import json
import re

EXTENSION = ".paramability"
_VERSION_SUFFIX = re.compile(r"\s+v\d+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_BAD_FILE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def design_title(document_name):
    """Design name without Fusion's version suffix ("Clip v3" becomes "Clip"), at most 120 characters."""
    text = _CONTROL.sub("", document_name or "")
    text = _VERSION_SUFFIX.sub("", text.strip()).strip()
    return (text or "Design")[:120]


def body_file_title(document_name, component_names):
    """Title for the default file name: the component that holds the exported bodies, or the design when the
    bodies sit in several components (or none is known)."""
    names = {design_title(n) for n in component_names if n}
    return names.pop() if len(names) == 1 else design_title(document_name)


def component_names(bodies):
    """Names of the components that hold `bodies`; a body whose component cannot be read gives None."""
    names = []
    for body in bodies:
        try:
            names.append(body.parentComponent.name)
        except Exception:
            names.append(None)
    return names


def package_file_name(title):
    """Safe default file name with the package extension."""
    base = _BAD_FILE_CHARS.sub("_", title or "").strip(" .")[:80] or "design"
    return base + EXTENSION


def with_extension(path):
    return path if path.lower().endswith(EXTENSION) else path + EXTENSION


def writer_text(addin_version, fusion_version):
    text = f"Paramability Fusion export {addin_version}"
    if fusion_version:
        text += f", Fusion {fusion_version}"
    return text[:200]


def addin_version(manifest_path):
    """Version from the add-in .manifest file; "unknown" when it cannot be read."""
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return str(json.load(f).get("version") or "unknown")
    except Exception:
        return "unknown"


def saved_message(size_count, file_name):
    if size_count > 1:
        return f"Saved {size_count} sizes to {file_name}."
    return f"Saved {file_name}."
