"""Atomic in-memory export using existing package and projection validators."""

import copy
import io
import struct
import zipfile

from .. import DocxError, DocxLimits, DocxSource
from .._xml import WORD_NAMESPACES, XmlValidator, expanded
from .._zip import chunks, parsing_end
from ..projection import ProjectionLimits, project_docx
from ._lexical import replace_text
from ._models import EditError, EditLimits, TextEdit

_SETTINGS_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
_SETTINGS_RELATIONSHIPS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/settings",
)


def _text_spans(projection):
    stack = list(projection.blocks)
    result = {}
    while stack:
        block = stack.pop()
        if block.kind == "paragraph":
            for span in block.spans:
                if span.kind == "text":
                    result[span.anchor.path] = span.text
        elif block.kind == "table":
            stack.extend(child for row in block.rows for cell in row.cells for child in cell.blocks)
    return result


def _settings_candidate(source: DocxSource) -> str | None:
    candidates = set()
    types = {entry.name: entry.content_type for entry in source.entries}
    for entry in source.entries:
        if entry.name.lower().startswith("_xmlsignatures/") or (
            entry.content_type and "digital-signature" in entry.content_type.lower()
        ):
            raise EditError("unsupported_edit")
        if entry.content_type == _SETTINGS_TYPE:
            candidates.add(entry.name)
    for rel in source.relationships:
        if "/digital-signature/" in rel.relationship_type.lower():
            raise EditError("unsupported_edit")
        if rel.source_part == source.main_part and rel.relationship_type in _SETTINGS_RELATIONSHIPS:
            if rel.target_mode != "Internal":
                raise EditError("unsupported_edit")
            candidates.add(rel.resolved_part)
    if len(candidates) > 1:
        raise EditError("unsupported_edit")
    if not candidates:
        return None
    candidate = candidates.pop()
    if types.get(candidate) != _SETTINGS_TYPE:
        raise EditError("unsupported_edit")
    return candidate


def _check_settings(payload: bytes) -> None:
    tracking = 0

    def start(name, attributes, depth):
        nonlocal tracking
        if depth == 0 and name not in (
            expanded(namespace, "settings") for namespace in WORD_NAMESPACES
        ):
            raise EditError("unsupported_edit")
        for namespace in WORD_NAMESPACES:
            if name == expanded(namespace, "documentProtection"):
                raise EditError("unsupported_edit")
            if name == expanded(namespace, "trackRevisions"):
                tracking += 1
                if tracking > 1 or attributes.get(expanded(namespace, "val")) not in (
                    "0",
                    "false",
                    "off",
                ):
                    raise EditError("unsupported_edit")

    parser = XmlValidator(start)
    parser.feed(payload, final=True)


def _nonstructural_extra(extra: bytes) -> bytes:
    result = []
    at = 0
    while at < len(extra):
        if len(extra) - at < 4:
            raise DocxError("invalid_package")
        tag, size = struct.unpack_from("<HH", extra, at)
        end = at + 4 + size
        if end > len(extra):
            raise DocxError("invalid_package")
        if tag != 1:
            result.append(extra[at:end])
        at = end
    return b"".join(result)


def _repack(data, source, replacements, limits):
    settings = _settings_candidate(source)
    end = parsing_end(data, limits)
    with io.BytesIO(data[:end]) as buffer, zipfile.ZipFile(buffer) as archive:
        # Include directories too: the public inventory intentionally omits them.
        if any(info.filename.lower().startswith("_xmlsignatures/") for info in archive.infolist()):
            raise EditError("unsupported_edit")

        def read(info):
            return b"".join(chunks(data, buffer, archive, info, limits.max_part_bytes))

        if settings is not None:
            _check_settings(read(archive.getinfo(settings)))
        main = replace_text(
            read(archive.getinfo(source.main_part)),
            replacements,
            min(limits.max_xml_bytes, limits.max_part_bytes),
        )
        total = sum(entry.size_bytes for entry in source.entries)
        total += len(main) - archive.getinfo(source.main_part).file_size
        if total > limits.max_total_uncompressed_bytes:
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
                    # Local and central extra fields are independent. Write
                    # the original local fields, then restore the directory's
                    # fields before ZipFile serializes it on close.
                    info.extra = _nonstructural_extra(data[extra_at : extra_at + extra_size])
                    payload = main if info.filename == source.main_part else read(original)
                    destination.writestr(info, payload)
                    info.extra = central_extra
                    # ZipFile supplies default permissions when this value is
                    # zero. Restore the original before it writes the directory.
                    info.external_attr = original.external_attr
                    if output.tell() > limits.max_archive_bytes:
                        raise DocxError("package_limit_exceeded")
            return output.getvalue()


def export_docx(
    data: bytes,
    edits: tuple[TextEdit, ...],
    *,
    limits: DocxLimits | None = None,
    projection_limits: ProjectionLimits | None = None,
    edit_limits: EditLimits | None = None,
) -> bytes:
    """Replace anchored text atomically, preserving the source's lexical XML.

    No-op returns the exact validated input. Real edits invalidate old anchors;
    callers must project the returned package before making further edits.
    """
    projection = project_docx(data, limits=limits, projection_limits=projection_limits)
    if edit_limits is None:
        edit_limits = EditLimits()
    if type(edit_limits) is not EditLimits or type(edits) is not tuple:
        raise EditError("invalid_input")
    edit_limits.__post_init__()
    if len(edits) > edit_limits.max_edits:
        raise EditError("edit_limit_exceeded")
    total = 0
    for edit in edits:
        if type(edit) is not TextEdit:
            raise EditError("invalid_input")
        edit.__post_init__()
        total += len(edit.replacement_text)
    if total > edit_limits.max_total_replacement_chars:
        raise EditError("edit_limit_exceeded")
    spans = _text_spans(projection)
    replacements = {}
    seen = set()
    for edit in edits:
        anchor = edit.anchor
        if anchor.source_sha256 != projection.source.sha256:
            raise EditError("stale_source")
        if anchor.part_name != projection.source.main_part or anchor.path not in spans:
            raise EditError("invalid_anchor")
        if anchor.path in seen:
            raise EditError("duplicate_edit")
        seen.add(anchor.path)
        if edit.expected_text != spans[anchor.path]:
            raise EditError("text_mismatch")
        if edit.replacement_text != edit.expected_text:
            if any(char in edit.replacement_text for char in "\t\r\n"):
                raise EditError("unsupported_edit")
            replacements[anchor.path] = edit.replacement_text
    if not replacements:
        return data
    result = _repack(data, projection.source, replacements, limits or DocxLimits())
    projected = project_docx(result, limits=limits, projection_limits=projection_limits)
    actual = _text_spans(projected)
    if any(actual.get(path) != value for path, value in replacements.items()):
        raise EditError("unsupported_edit")
    return result
