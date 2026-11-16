"""File and display names."""
import json
import re

EXTENSION = ".paramability"
ORCA_EXTENSION = ".3mf"
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
    bodies sit in several components, or one of them sits in the root or in a component that is not known (None)."""
    names = {design_title(n) if n else None for n in component_names}
    return names.pop() if len(names) == 1 and None not in names else design_title(document_name)


def component_names(bodies):
    """Names of the components that hold `bodies`. A body of the root component gives None: the root takes the name
    of the document, or a placeholder such as "(Unsaved)" before the first save. A body whose component cannot be
    read gives None too."""
    names = []
    for body in bodies:
        try:
            component = body.parentComponent
            root = component.parentDesign.rootComponent
            names.append(None if component == root else component.name)
        except Exception:
            names.append(None)
    return names


def package_file_name(title, extension=EXTENSION):
    """Safe default file name with the package extension (or `extension`)."""
    base = _BAD_FILE_CHARS.sub("_", title or "").strip(" .")[:80] or "design"
    return base + extension


def with_extension(path, extension=EXTENSION):
    return path if path.lower().endswith(extension) else path + extension


_WRITER_PREFIX = "Paramability Fusion export "


def writer_text(addin_version, fusion_version):
    text = f"{_WRITER_PREFIX}{addin_version}"
    if fusion_version:
        text += f", Fusion {fusion_version}"
    return text[:200]


def addin_of_writer(writer):
    """The add-in version a `writer_text` names, or "" for any other text."""
    if not isinstance(writer, str) or not writer.startswith(_WRITER_PREFIX):
        return ""
    return writer[len(_WRITER_PREFIX):].split(",")[0].strip()


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
