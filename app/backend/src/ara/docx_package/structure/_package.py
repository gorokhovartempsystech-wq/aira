"""Preserve ZIP structure and share the pre-existing protection gates."""

import copy
import io
import struct
import zipfile

from .. import DocxError
from .._zip import chunks, parsing_end
from ..editing._export import _check_settings, _nonstructural_extra, _settings_candidate
from ..editing._models import EditError
from ._models import StructureError


def read_main(data, source, limits):
    end = parsing_end(data, limits)
    with io.BytesIO(data[:end]) as buffer, zipfile.ZipFile(buffer) as archive:
        return b"".join(
            chunks(data, buffer, archive, archive.getinfo(source.main_part), limits.max_part_bytes)
        )


def repack(data, source, main, limits):
    return repack_parts(data, source, {source.main_part: main}, limits)


def repack_parts(data, source, replacements, limits, *, additions=None):
    entries = {entry.name: entry for entry in source.entries}
    additions = {} if additions is None else additions
    if type(additions) is not dict or any(
        type(name) is not str
        or not name
        or name in entries
        or any(part in ("", ".", "..") for part in name.split("/"))
        or any(c in name for c in "\\\x00:?#%")
        or type(payload) is not bytes
        for name, payload in additions.items()
    ):
        raise DocxError("invalid_input")
    if type(replacements) is not dict or any(
        name not in entries or type(payload) is not bytes for name, payload in replacements.items()
    ):
        raise DocxError("invalid_input")
    try:
        settings = _settings_candidate(source)
        end = parsing_end(data, limits)
        with io.BytesIO(data[:end]) as buffer, zipfile.ZipFile(buffer) as archive:
            if any(i.filename.lower().startswith("_xmlsignatures/") for i in archive.infolist()):
                raise StructureError("unsupported_structure")

            def read(info):
                return b"".join(chunks(data, buffer, archive, info, limits.max_part_bytes))

            if settings is not None:
                _check_settings(read(archive.getinfo(settings)))
            total = sum(entry.size_bytes for entry in source.entries)
            total += sum(
                len(payload) - entries[name].size_bytes for name, payload in replacements.items()
            )
            total += sum(len(payload) for payload in additions.values())
            if (
                any(
                    len(payload) > min(limits.max_xml_bytes, limits.max_part_bytes)
                    for payload in replacements.values()
                )
                or total > limits.max_total_uncompressed_bytes
                or len(entries) + len(additions) > limits.max_entries
                or any(
                    len(payload)
                    > (
                        min(limits.max_xml_bytes, limits.max_part_bytes)
                        if name.endswith((".xml", ".rels"))
                        else limits.max_part_bytes
                    )
                    for name, payload in additions.items()
                )
            ):
                raise DocxError("package_limit_exceeded")
            with io.BytesIO() as output:
                with zipfile.ZipFile(output, "w") as destination:
                    destination.comment = data[end:]
                    for original in archive.infolist():
                        info = copy.copy(original)
                        central_extra = _nonstructural_extra(original.extra)
                        name_size, extra_size = struct.unpack_from(
                            "<HH", data, original.header_offset + 26
                        )
                        extra_at = original.header_offset + 30 + name_size
                        info.extra = _nonstructural_extra(data[extra_at : extra_at + extra_size])
                        destination.writestr(
                            info,
                            replacements[info.filename]
                            if info.filename in replacements
                            else read(original),
                        )
                        info.extra = central_extra
                        info.external_attr = original.external_attr
                        if output.tell() > limits.max_archive_bytes:
                            raise DocxError("package_limit_exceeded")
                    for name, payload in additions.items():
                        info = zipfile.ZipInfo(name)
                        info.compress_type = zipfile.ZIP_DEFLATED
                        destination.writestr(info, payload)
                        if output.tell() > limits.max_archive_bytes:
                            raise DocxError("package_limit_exceeded")
                if output.tell() > limits.max_archive_bytes:
                    raise DocxError("package_limit_exceeded")
                return output.getvalue()
    except EditError:
        raise StructureError("unsupported_structure") from None
