"""Size limits the Paramability app enforces when it opens a package.

Source: the app's recipe-package reader (reader caps, section 1.4 of the package contract). The schema JSON in
lib/schema/ carries text limits only, so these byte limits live here. Update them together with the app.
"""
import os

MAX_TOTAL_BYTES = 1024 ** 3
MAX_STEP_BYTES = 256 * 1024 ** 2
MAX_ENTRIES = 64


class PackageCapError(Exception):
    """A package would be too large for Paramability to open. The message is a plain sentence."""


def _mb(size):
    return f"{size / (1024 * 1024):.0f} MB"


def check_step_size(label, size):
    if size > MAX_STEP_BYTES:
        raise PackageCapError(
            f"{label} makes a STEP file of {_mb(size)}. Paramability opens up to {_mb(MAX_STEP_BYTES)} per size. "
            "Remove fine detail from the part, or export fewer sizes.")


def check_total_size(total):
    if total > MAX_TOTAL_BYTES:
        raise PackageCapError(
            f"The sizes add up to {_mb(total)}. Paramability opens packages up to {_mb(MAX_TOTAL_BYTES)}. "
            "Export fewer sizes or remove fine detail from the part.")


def _size_of(source):
    return len(source) if isinstance(source, (bytes, bytearray)) else os.path.getsize(source)


def check_package_caps(files):
    """files: {entry path: bytes or file path}. Raises PackageCapError before anything is written."""
    if len(files) + 1 > MAX_ENTRIES:
        raise PackageCapError(f"A package holds at most {MAX_ENTRIES} files.")
    total = 0
    for path, source in files.items():
        size = _size_of(source)
        check_step_size(f"\"{path}\"", size)
        total += size
    check_total_size(total)
