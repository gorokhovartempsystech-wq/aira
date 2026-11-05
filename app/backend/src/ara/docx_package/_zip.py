"""Bounded reads of ZIP payloads, including verification of actual stream sizes."""

import io
import stat
import struct
import zipfile
import zlib
from collections.abc import Iterator

from ._models import DocxError, DocxLimits
from ._names import part_key

_CHUNK = 65536
_LOCAL = struct.Struct("<4s5H3I2H")
_END = struct.Struct("<4s4H2IH")
_END64 = struct.Struct("<4sQ2H2I4Q")
_LOCATOR64 = struct.Struct("<4sIQI")


def _check_directory(data: bytes, end: int, max_entries: int) -> None:
    """Check end-record agreement and the exact central-directory extent/count."""
    _, disk, cd_disk, disk_count, count, size, start, _ = _END.unpack_from(data, end)
    directory_end = end
    locator_at = end - _LOCATOR64.size
    has_zip64 = locator_at >= 0 and data[locator_at : locator_at + 4] == b"PK\x06\x07"
    if has_zip64:
        _, record_disk, record_at, disks = _LOCATOR64.unpack_from(data, locator_at)
        if record_disk != 0 or disks != 1:
            raise DocxError("unsupported_package")
        record = _END64.unpack_from(data, record_at)
        signature, length, _, _, disk64, cd_disk64, disk_count64, count64, size64, start64 = record
        if signature != b"PK\x06\x06" or length < 44 or record_at + length + 12 != locator_at:
            raise DocxError("invalid_package")
        for original, extended, sentinel in (
            (disk, disk64, 0xFFFF),
            (cd_disk, cd_disk64, 0xFFFF),
            (disk_count, disk_count64, 0xFFFF),
            (count, count64, 0xFFFF),
            (size, size64, 0xFFFFFFFF),
            (start, start64, 0xFFFFFFFF),
        ):
            if original not in (extended, sentinel):
                raise DocxError("invalid_package")
        disk, cd_disk, disk_count, count, size, start = (
            disk64,
            cd_disk64,
            disk_count64,
            count64,
            size64,
            start64,
        )
        directory_end = record_at
    if disk or cd_disk:
        raise DocxError("unsupported_package")
    if disk_count != count or start + size != directory_end:
        raise DocxError("invalid_package")
    if count > max_entries:
        raise DocxError("package_limit_exceeded")
    at = start
    actual_count = 0
    while at < directory_end:
        if at + 46 > directory_end or data[at : at + 4] != b"PK\x01\x02":
            raise DocxError("invalid_package")
        name_size, extra_size, comment_size, entry_disk = struct.unpack_from("<4H", data, at + 28)
        if entry_disk:
            raise DocxError("unsupported_package")
        at += 46 + name_size + extra_size + comment_size
        actual_count += 1
        if actual_count > count:
            raise DocxError("invalid_package")
    if at != directory_end or actual_count != count:
        raise DocxError("invalid_package")


def parsing_end(data: bytes, limits: DocxLimits) -> int:
    """Locate a coherent end record, even when comments contain ZIP signatures.

    ZipFile ignores end-record counts and truncated comments, and searches for
    the last signature even if it is inside a comment. Validate these ourselves.
    The returned prefix ends just before the validated archive comment; using
    that view for ZipFile avoids its signature ambiguity. Export keeps all bytes.
    """
    lower = max(0, len(data) - _END.size - 65535)
    search_end = len(data)
    candidates: list[int] = []
    unsupported = False
    limit_exceeded = False
    while True:
        at = data.rfind(b"PK\x05\x06", lower, search_end)
        if at < 0:
            break
        search_end = at
        if at + _END.size > len(data):
            continue
        comment_size = struct.unpack_from("<H", data, at + 20)[0]
        if at + _END.size + comment_size != len(data):
            continue
        try:
            _check_directory(data, at, limits.max_entries)
        except DocxError as error:
            unsupported |= error.code == "unsupported_package"
            limit_exceeded |= error.code == "package_limit_exceeded"
        except (struct.error, OverflowError):
            pass
        else:
            candidates.append(at + _END.size)
    if len(candidates) != 1:
        if not candidates and limit_exceeded:
            raise DocxError("package_limit_exceeded")
        code = "unsupported_package" if not candidates and unsupported else "invalid_package"
        raise DocxError(code)
    return candidates[0]


def inventory(archive: zipfile.ZipFile, limits: DocxLimits) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > limits.max_entries:
        raise DocxError("package_limit_exceeded")
    seen: set[str] = set()
    files: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in infos:
        if info.orig_filename != info.filename:
            raise DocxError("invalid_package")
        name = info.filename[:-1] if info.is_dir() else info.filename
        key = part_key(name)
        if key in seen:
            raise DocxError("invalid_package")
        seen.add(key)
        if (
            info.flag_bits & (1 | 64)
            or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            or stat.S_ISLNK(info.external_attr >> 16)
        ):
            raise DocxError("unsupported_package")
        if info.is_dir():
            if info.file_size:
                raise DocxError("invalid_package")
            continue
        if info.file_size > limits.max_part_bytes:
            raise DocxError("package_limit_exceeded")
        total += info.file_size
        if total > limits.max_total_uncompressed_bytes:
            raise DocxError("package_limit_exceeded")
        files[key] = info
    return files


def _local_sizes(extra: bytes, size: int, compressed: int) -> tuple[int, int]:
    """Resolve the optional ZIP64 local size fields, without assuming their order."""
    offset = 0
    while offset < len(extra):
        tag, length = struct.unpack_from("<HH", extra, offset)
        offset += 4
        if offset + length > len(extra):
            raise DocxError("invalid_package")
        if tag == 1:
            payload = extra[offset : offset + length]
            at = 0
            if size == 0xFFFFFFFF:
                size = struct.unpack_from("<Q", payload, at)[0]
                at += 8
            if compressed == 0xFFFFFFFF:
                compressed = struct.unpack_from("<Q", payload, at)[0]
            return size, compressed
        offset += length
    if 0xFFFFFFFF in (size, compressed):
        raise DocxError("invalid_package")
    return size, compressed


def _descriptor(data: bytes, offset: int, info: zipfile.ZipInfo, zip64: bool) -> None:
    layout = struct.Struct("<IQQ" if zip64 else "<III")
    expected = (info.CRC, info.compress_size, info.file_size)
    # A signature is optional, and a CRC can itself equal the signature value.
    offsets = [offset]
    if data[offset : offset + 4] == b"PK\x07\x08":
        offsets.append(offset + 4)
    for at in offsets:
        if at + layout.size <= len(data) and layout.unpack_from(data, at) == expected:
            return
    raise DocxError("invalid_package")


def chunks(
    data: bytes,
    buffer: io.BytesIO,
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    limit: int,
) -> Iterator[bytes]:
    """Check local/central agreement, then hash/parse in bounded output chunks.

    ZipExtFile intentionally stops at the central directory's declared size. A
    forged size and prefix CRC can therefore hide additional decompressed data.
    Use ZipFile.open for local-name/overlap validation, but consume the original
    compressed range ourselves so EOF, real size and CRC are all verified.
    """
    header = _LOCAL.unpack_from(data, info.header_offset)
    signature, _, flags, method, _, _, crc, compressed, size, name_len, extra_len = header
    if signature != b"PK\x03\x04" or flags != info.flag_bits or method != info.compress_type:
        raise DocxError("invalid_package")
    zip64 = size == 0xFFFFFFFF or compressed == 0xFFFFFFFF
    extra_at = info.header_offset + _LOCAL.size + name_len
    extra = data[extra_at : extra_at + extra_len]
    if len(extra) != extra_len:
        raise DocxError("invalid_package")
    size, compressed = _local_sizes(extra, size, compressed)
    if flags & 8:
        if crc not in (0, info.CRC) or size not in (0, info.file_size):
            raise DocxError("invalid_package")
        if compressed not in (0, info.compress_size):
            raise DocxError("invalid_package")
    elif (crc, size, compressed) != (info.CRC, info.file_size, info.compress_size):
        raise DocxError("invalid_package")
    with archive.open(info):
        start = buffer.tell()
    end = start + info.compress_size
    if end > len(data):
        raise DocxError("invalid_package")
    if flags & 8:
        _descriptor(data, end, info, zip64)

    decoder = zlib.decompressobj(-15) if method == zipfile.ZIP_DEFLATED else None
    actual = 0
    checksum = 0
    at = start
    pending = b""
    while at < end or pending or (decoder is not None and not decoder.eof):
        if not pending:
            pending = data[at : min(end, at + _CHUNK)]
            at += len(pending)
        allowance = min(_CHUNK, limit - actual + 1)
        if decoder is None:
            output, pending = pending[:allowance], pending[allowance:]
        else:
            output = decoder.decompress(pending, allowance)
            pending = decoder.unconsumed_tail
            if decoder.unused_data:
                raise DocxError("invalid_package")
            # max_length can leave output buffered after the last input byte.
            # Drain it with bounded empty-input calls; no progress means a
            # truncated stream, even when the declared size and CRC match.
            if not output and not pending and at == end and not decoder.eof:
                raise DocxError("invalid_package")
        actual += len(output)
        if actual > limit:
            raise DocxError("package_limit_exceeded")
        if actual > info.file_size:
            raise DocxError("invalid_package")
        checksum = zlib.crc32(output, checksum)
        if output:
            yield output
    if decoder is not None and not decoder.eof:
        raise DocxError("invalid_package")
    if actual != info.file_size or checksum != info.CRC:
        raise DocxError("invalid_package")
