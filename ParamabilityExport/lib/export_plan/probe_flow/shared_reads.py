"""One copy of each part of a probe read that reads the same in several states."""
import hashlib
import json


class SharedReads:
    """One copy of each part of a probe read that reads the same in several states. Most tries read most sketches
    exactly as E0 or as an earlier try did; the states keep every read, so a long probe would otherwise hold the same
    sketch many times over. `share(read)` puts the copy already kept in place of each equal sketch, face, point, line
    and reference of `read`, and returns `read`."""

    KEYS = ("sketches", "faces", "points", "lines", "refs")

    def __init__(self):
        self._kept = {}  # (key, name, digest) to the copy kept
        self._last = {}  # (key, name) to the copy kept or given last: most reads equal it, so it is compared first

    def share(self, read):
        if not isinstance(read, dict):
            return read
        for key in self.KEYS:
            part = read.get(key)
            if not isinstance(part, dict):
                continue
            for name, value in part.items():
                last = self._last.get((key, name))
                if last is not None and (last is value or last == value):
                    part[name] = last
                    continue
                try:
                    text = json.dumps(value, sort_keys=True, separators=(",", ":"))
                except (TypeError, ValueError):
                    continue
                kept = self._kept.setdefault((key, name, hashlib.sha1(text.encode("utf-8")).digest()), value)
                if kept is not value and kept == value:
                    part[name] = kept
                self._last[(key, name)] = part[name]
        return read
