"""Write a .paramability zip."""
import json
import os
import tempfile
import zipfile

from .caps import check_package_caps


def write_package(out_path, manifest, files):
    """Write manifest.json first, then each entry of files ({entry path: bytes or a file path to read}).

    Raises PackageCapError first when the package is above the sizes Paramability opens.
    The zip goes to a temp file beside the target, then replaces it, so a failed export never leaves half a file.
    """
    check_package_caps(files)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=out_dir)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
            for path, source in files.items():
                if path == "manifest.json":
                    raise ValueError("manifest.json is written by the writer.")
                if isinstance(source, (bytes, bytearray)):
                    zf.writestr(path, bytes(source))
                else:
                    zf.write(source, path)
        os.replace(tmp_path, out_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
