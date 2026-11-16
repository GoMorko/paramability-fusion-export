"""The cereal binary archive as Orca writes it: native little endian, no padding, no class versions.

Widths: bool 1 byte, int and enum 4 bytes (signed), uint32 4 bytes, float 4, double 8. A string, a vector and a
map start with a size tag (uint64, the count of bytes or items). A vector of numbers is the size tag and then the
numbers back to back; a map is the size tag and then key, value, key, value. A fixed array of numbers has no size
tag. An Eigen 2D or 3D vector is its 2 or 3 doubles.
"""
import struct

_U8 = struct.Struct("<B")
_I32 = struct.Struct("<i")
_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")
_F32 = struct.Struct("<f")
_F64 = struct.Struct("<d")

# Strings are bytes in the archive. Bytes that are not UTF-8 survive a read and a write unchanged.
_TEXT = ("utf-8", "surrogateescape")


class RecipeFormatError(ValueError):
    """The bytes do not hold what the format says they should."""


class ShortRead(RecipeFormatError):
    """The bytes ran out in the middle of a value."""


def text_bytes(text):
    return text.encode(*_TEXT)


class Writer:
    """Collects archive bytes."""

    def __init__(self):
        self._buf = bytearray()

    def getvalue(self):
        return bytes(self._buf)

    def raw(self, data):
        self._buf += data

    def bool(self, value):
        self._buf += _U8.pack(1 if value else 0)

    def i32(self, value):
        self._buf += _I32.pack(int(value))

    def u32(self, value):
        self._buf += _U32.pack(int(value))

    def size(self, count):
        self._buf += _U64.pack(int(count))

    def f32(self, value):
        self._buf += _F32.pack(float(value))

    def f64(self, value):
        self._buf += _F64.pack(float(value))

    def string(self, text):
        data = text if isinstance(text, (bytes, bytearray)) else text_bytes(text)
        self.size(len(data))
        self._buf += data

    def vec2(self, v):
        self.f64(v[0])
        self.f64(v[1])

    def vec3(self, v):
        self.f64(v[0])
        self.f64(v[1])
        self.f64(v[2])

    def int_list(self, values):
        self.size(len(values))
        for v in values:
            self.i32(v)

    def vec2_list(self, points):
        self.size(len(points))
        for p in points:
            self.vec2(p)

    def items(self, values, write_one):
        self.size(len(values))
        for v in values:
            write_one(self, v)

    def string_map(self, mapping):
        """A std::map<string, string>: keys in byte order, as std::map keeps them."""
        pairs = sorted(((text_bytes(k), text_bytes(v)) for k, v in mapping.items()), key=lambda kv: kv[0])
        self.size(len(pairs))
        for k, v in pairs:
            self.string(k)
            self.string(v)


class Reader:
    """Reads archive values from bytes, front to back."""

    def __init__(self, data):
        self._data = bytes(data)
        self._pos = 0

    @property
    def pos(self):
        return self._pos

    def remaining(self):
        return len(self._data) - self._pos

    def at_end(self):
        return self._pos >= len(self._data)

    def rest(self):
        out = self._data[self._pos:]
        self._pos = len(self._data)
        return out

    def seek(self, pos):
        self._pos = pos

    def raw(self, count):
        if count < 0 or count > self.remaining():
            raise ShortRead("needs %d bytes at %d, %d left" % (count, self._pos, self.remaining()))
        out = self._data[self._pos:self._pos + count]
        self._pos += count
        return out

    def _unpack(self, fmt):
        return fmt.unpack(self.raw(fmt.size))[0]

    def bool(self):
        return self._unpack(_U8) != 0

    def i32(self):
        return self._unpack(_I32)

    def u32(self):
        return self._unpack(_U32)

    def size(self):
        count = self._unpack(_U64)
        # Every item takes at least one byte, so a count above what is left is a broken stream.
        if count > self.remaining():
            raise ShortRead("size tag %d at %d is above the %d bytes left" % (count, self._pos - 8, self.remaining()))
        return count

    def f32(self):
        return self._unpack(_F32)

    def f64(self):
        return self._unpack(_F64)

    def string(self):
        return self.raw(self.size()).decode(*_TEXT)

    def vec2(self):
        return (self.f64(), self.f64())

    def vec3(self):
        return (self.f64(), self.f64(), self.f64())

    def int_list(self):
        return [self.i32() for _ in range(self.size())]

    def vec2_list(self):
        return [self.vec2() for _ in range(self.size())]

    def items(self, read_one):
        return [read_one(self) for _ in range(self.size())]

    def string_map(self):
        out = {}
        for _ in range(self.size()):
            key = self.string()
            out[key] = self.string()
        return out
