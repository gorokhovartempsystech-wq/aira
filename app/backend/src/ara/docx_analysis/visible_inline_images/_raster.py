"""Bounded raster framing proofs, without pixel decoding or metadata extraction."""

import re
import struct
import zlib

from ara.docx_analysis.visible_main._models import budget
from ara.docx_analysis.visible_main._reader import Refusal


def require(value):
    if not value:
        raise Refusal("invalid_raster_image")


class Counter:
    def __init__(self, limits):
        self.count, self.maximum = 0, min(100000, limits.max_pieces)

    def step(self):
        self.count += 1
        budget(self.count, self.maximum)


def png(data, counter):
    require(data[:8] == b"\x89PNG\r\n\x1a\n")
    at, header, palette, phase, total = 8, None, False, 0, 0
    while at < len(data):
        counter.step()
        require(at + 12 <= len(data))
        size = int.from_bytes(data[at : at + 4], "big")
        kind = data[at + 4 : at + 8]
        require(size <= 0x7FFFFFFF and at + size + 12 <= len(data))
        require(re.fullmatch(b"[A-Za-z]{2}[A-Z][A-Za-z]", kind) is not None)
        value = memoryview(data)[at + 8 : at + 8 + size]
        crc = int.from_bytes(data[at + 8 + size : at + 12 + size], "big")
        require(zlib.crc32(value, zlib.crc32(kind)) == crc)
        if header is None:
            require(kind == b"IHDR" and size == 13)
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", value
            )
            require(0 < width <= 0x7FFFFFFF and 0 < height <= 0x7FFFFFFF)
            require(
                depth
                in {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}.get(
                    color, ()
                )
            )
            require(compression == filtering == 0 and interlace in (0, 1))
            header = depth, color
        elif kind == b"PLTE":
            require(not palette and phase == 0 and header[1] not in (0, 4))
            require(0 < size <= 768 and size % 3 == 0)
            require(header[1] != 3 or size // 3 <= 2 ** header[0])
            palette = True
        elif kind == b"IDAT":
            require(phase != 2 and (header[1] != 3 or palette))
            phase, total = 1, total + size
        elif kind == b"IEND":
            require(size == 0 and total > 0 and at + 12 == len(data))
            return
        else:
            require(kind[0] & 32 and kind not in (b"acTL", b"fcTL", b"fdAT"))
            if phase == 1:
                phase = 2
        at += size + 12
    require(False)


def quantization(value):
    at = 0
    require(bool(value))
    while at < len(value):
        info = value[at]
        precision, identity = info >> 4, info & 15
        require(precision in (0, 1) and identity <= 3)
        width = 1 + precision
        end = at + 1 + 64 * width
        require(end <= len(value))
        require(all(int.from_bytes(value[i : i + width], "big") for i in range(at + 1, end, width)))
        at = end


def huffman(value):
    at = 0
    require(bool(value))
    while at < len(value):
        require(at + 17 <= len(value) and value[at] >> 4 in (0, 1) and value[at] & 15 <= 3)
        counts = value[at + 1 : at + 17]
        total = sum(counts)
        require(0 < total <= 256 and at + 17 + total <= len(value))
        slots = 1
        for count in counts:
            slots = 2 * slots - count
            require(slots >= 0)
        at += 17 + total


def frame(value, marker):
    require(len(value) >= 9 and value[0] == 8)
    height, width = int.from_bytes(value[1:3], "big"), int.from_bytes(value[3:5], "big")
    count = value[5]
    require(height > 0 and width > 0 and 1 <= count <= 4 and len(value) == 6 + 3 * count)
    identities = set()
    for i in range(count):
        key, sampling, table = value[6 + 3 * i : 9 + 3 * i]
        require(
            key not in identities
            and 1 <= sampling >> 4 <= 4
            and 1 <= sampling & 15 <= 4
            and table <= 3
        )
        identities.add(key)
    return marker, identities


def scan(value, definition):
    require(definition is not None and len(value) >= 6)
    kind, identities = definition
    count = value[0]
    require(1 <= count <= 4 and len(value) == 4 + 2 * count)
    seen = set()
    for i in range(count):
        key, tables = value[1 + 2 * i : 3 + 2 * i]
        require(key in identities and key not in seen and tables >> 4 <= 3 and tables & 15 <= 3)
        seen.add(key)
    start, end, approximation = value[-3:]
    if kind == 0xC0:
        require((start, end, approximation) == (0, 63, 0))
    else:
        high, low = approximation >> 4, approximation & 15
        require(0 <= start <= end <= 63 and high <= 13 and low <= 13)
        require(high == 0 or high == low + 1)
        require(end == 0 if start == 0 else count == 1)


def entropy(data, at, counter, restart):
    start, count = at, 0
    while at < len(data):
        if data[at] != 0xFF:
            count += 1
            at += 1
            continue
        marker_at = at
        while at < len(data) and data[at] == 0xFF:
            at += 1
        require(at < len(data))
        code = data[at]
        if code == 0:
            require(at == marker_at + 1)
            count += 1
            at += 1
        elif 0xD0 <= code <= 0xD7:
            counter.step()
            require(restart > 0)
            at += 1
        else:
            require(count > 0 and marker_at > start)
            return marker_at
    require(False)


def jpeg(data, counter):
    require(data[:2] == b"\xff\xd8")
    at, definition, scans, restart = 2, None, 0, 0
    while at < len(data):
        counter.step()
        require(data[at] == 0xFF)
        while at < len(data) and data[at] == 0xFF:
            at += 1
        require(at < len(data))
        marker = data[at]
        at += 1
        if marker == 0xD9:
            require(scans > 0 and at == len(data))
            return
        require(marker in (0xC0, 0xC2, 0xC4, 0xDB, 0xDD, 0xDA, 0xFE) or 0xE0 <= marker <= 0xEF)
        require(at + 2 <= len(data))
        size = int.from_bytes(data[at : at + 2], "big")
        require(size >= 2 and at + size <= len(data))
        value = memoryview(data)[at + 2 : at + size]
        at += size
        if marker in (0xC0, 0xC2):
            require(definition is None and scans == 0)
            definition = frame(value, marker)
        elif marker == 0xDB:
            quantization(value)
        elif marker == 0xC4:
            huffman(value)
        elif marker == 0xDD:
            require(len(value) == 2)
            restart = int.from_bytes(value, "big")
        elif marker == 0xDA:
            scan(value, definition)
            scans += 1
            at = entropy(data, at, counter, restart)
    require(False)
