"""A 3MF that OrcaSlicer 2.5 opens as a project with a Design tab recipe.

Orca keeps the recipe only when it opens the file as a project, and it does that only when the file carries
project settings it can load; without them it imports the meshes alone and drops the recipe. Two ways to give
them:
- `settings=None` (the default): the file is marked "published", Orca's own way to share a project. The person
  keeps the printer, process and filament presets they have selected, and the file adds none of its own. The
  published payload holds one inert line, because Orca needs a non empty one, and lists no key to apply. Orca
  opens a published file without a file name, so Save asks where to save it.
- `settings={...}`: `Metadata/project_settings.config` with those values, as Orca writes it. Orca then loads
  them as the project's presets, so they should be a full set saved by Orca, not a few keys.

The Design tab rebuilds the body from the recipe when it opens. The mesh objects are what the plate shows and
slices; Orca does not link them to the recipe, and committing the Design body adds a new plate object beside them.
A published file needs at least one mesh object: Orca 2.5.1 started with a published file that holds only a
recipe takes the project for empty and starts a new one, which drops the recipe.
"""
import json
import os
import tempfile
import zipfile
from xml.sax.saxutils import escape, quoteattr

RECIPE_ENTRY = "Metadata/orca_cad.bin"
MODEL_ENTRY = "3D/3dmodel.model"
SETTINGS_ENTRY = "Metadata/project_settings.config"
MODEL_SETTINGS_ENTRY = "Metadata/model_settings.config"

# The Orca version the file says it was made with. Orca warns about a file of a newer minor version.
DEFAULT_APP_VERSION = "2.5.0"

_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
    ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
    ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
    '</Types>\n'
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
    ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
    '</Relationships>\n'
)

# The published payload: one key Orca knows, so the payload is not empty. No key is listed as published, so
# nothing of it is applied to the person's presets.
_PUBLISHED_PAYLOAD = "; Design tab recipe; no settings published\nlayer_height = 0.2\n"


class MeshObject:
    """A plate object: one triangle mesh in object millimetres, placed by `transform`.

    `transform` is the 3MF item matrix: 9 numbers of the rotation (row by row) then the translation.
    """

    def __init__(self, name, vertices, triangles, transform=_IDENTITY):
        if len(transform) != 12:
            raise ValueError("a 3MF transform has 12 numbers")
        self.name = name
        self.vertices = [tuple(float(c) for c in v) for v in vertices]
        self.triangles = [tuple(int(i) for i in t) for t in triangles]
        self.transform = tuple(float(c) for c in transform)
        count = len(self.vertices)
        for t in self.triangles:
            if len(t) != 3 or min(t) < 0 or max(t) >= count:
                raise ValueError("triangle %r is not three vertex indices below %d" % (t, count))

    @classmethod
    def placed(cls, name, vertices, triangles, offset):
        """A mesh moved by `offset` (x, y, z)."""
        return cls(name, vertices, triangles, _IDENTITY[:9] + tuple(offset))


def _num(value):
    text = repr(float(value))
    return text[:-2] if text.endswith(".0") else text


def model_xml(objects, app_version=DEFAULT_APP_VERSION, published=True):
    """`3D/3dmodel.model`: the metadata Orca reads to know its own files, the meshes and the build."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">',
        ' <metadata name="Application">OrcaSlicer-%s</metadata>' % escape(app_version),
        ' <metadata name="OrcaSlicer">%s</metadata>' % escape(app_version),
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>',
    ]
    if published:
        lines += [
            ' <metadata name="orca_published">1</metadata>',
            ' <metadata name="orca_published_keys">[]</metadata>',
            ' <metadata name="orca_published_config">%s</metadata>' % escape(_PUBLISHED_PAYLOAD),
        ]
    lines.append(' <resources>')
    for index, obj in enumerate(objects):
        lines.append('  <object id="%d" name=%s type="model">' % (index + 1, quoteattr(obj.name)))
        lines.append('   <mesh>')
        lines.append('    <vertices>')
        lines += ['     <vertex x="%s" y="%s" z="%s"/>' % tuple(_num(c) for c in v) for v in obj.vertices]
        lines.append('    </vertices>')
        lines.append('    <triangles>')
        lines += ['     <triangle v1="%d" v2="%d" v3="%d"/>' % t for t in obj.triangles]
        lines.append('    </triangles>')
        lines.append('   </mesh>')
        lines.append('  </object>')
    lines.append(' </resources>')
    lines.append(' <build>')
    for index, obj in enumerate(objects):
        lines.append('  <item objectid="%d" transform="%s" printable="1"/>'
                     % (index + 1, " ".join(_num(c) for c in obj.transform)))
    lines.append(' </build>')
    lines.append('</model>')
    return "\n".join(lines) + "\n"


def model_settings_xml(objects):
    """`Metadata/model_settings.config`: the object and part names Orca shows in its object list."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<config>']
    for index, obj in enumerate(objects):
        name = quoteattr(obj.name)
        lines += [
            '  <object id="%d">' % (index + 1),
            '    <metadata key="name" value=%s/>' % name,
            '    <metadata key="extruder" value="1"/>',
            '    <part id="%d" subtype="normal_part">' % (index + 1),
            '      <metadata key="name" value=%s/>' % name,
            '    </part>',
            '  </object>',
        ]
    lines.append('</config>')
    return "\n".join(lines) + "\n"


def write_3mf(out_path, recipe_bytes, objects=(), settings=None, app_version=DEFAULT_APP_VERSION, extra=None):
    """Write the 3MF: meshes, the recipe bytes and the project settings (see the module note for `settings`).
    `extra` maps more entry names to bytes (a report for people and tools; Orca does not read them).

    The zip goes to a temp file beside the target, then replaces it, so a failure never leaves half a file.
    """
    objects = list(objects)
    if settings is None and not objects:
        raise ValueError("a published Orca project needs at least one mesh object")
    entries = [
        ("[Content_Types].xml", _CONTENT_TYPES.encode("utf-8")),
        ("_rels/.rels", _RELS.encode("utf-8")),
        (MODEL_ENTRY, model_xml(objects, app_version, published=settings is None).encode("utf-8")),
    ]
    if objects:
        entries.append((MODEL_SETTINGS_ENTRY, model_settings_xml(objects).encode("utf-8")))
    if settings is not None:
        entries.append((SETTINGS_ENTRY, json.dumps(settings, indent=4, ensure_ascii=False).encode("utf-8")))
    entries.append((RECIPE_ENTRY, bytes(recipe_bytes)))
    for name, data in (extra or {}).items():
        if name in {n for n, _ in entries}:
            raise ValueError("%s is an entry of the 3MF itself" % name)
        entries.append((name, bytes(data)))

    out_dir = os.path.dirname(os.path.abspath(out_path))
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=out_dir)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in entries:
                zf.writestr(name, data)
        os.replace(tmp_path, out_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def read_recipe_bytes(path):
    """The recipe entry of a 3MF (also its older name), or None when it has none."""
    with zipfile.ZipFile(path) as zf:
        names = {n.lower(): n for n in zf.namelist()}
        for entry in (RECIPE_ENTRY, "Metadata/SnapOrca_cad.bin"):
            if entry.lower() in names:
                return zf.read(names[entry.lower()])
    return None
