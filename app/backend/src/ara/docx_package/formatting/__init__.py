"""Atomic paragraph style/list changes preserving run XML and style definitions."""

from .. import DocxLimits
from ..projection import ProjectionLimits, project_docx
from ..structure import StructureError
from ..structure._package import read_main, repack_parts
from ..structure._xml import check_target, scan, word_name
from ._models import FormatLimits, FormattingError, ParagraphFormat
from ._parts import check_list, check_style, load_part, next_ids
from ._patch import new_list, numbering_patch, patch_bytes, ppr_patch

__all__ = ["ParagraphFormat", "FormatLimits", "FormattingError", "export_formats"]


def export_formats(
    data: bytes,
    formats: tuple[ParagraphFormat, ...],
    *,
    limits: DocxLimits | None = None,
    projection_limits: ProjectionLimits | None = None,
    format_limits: FormatLimits | None = None,
) -> bytes:
    if type(formats) is not tuple:
        raise FormattingError("invalid_input")
    if format_limits is None:
        format_limits = FormatLimits()
    if type(format_limits) is not FormatLimits:
        raise FormattingError("invalid_input")
    format_limits.__post_init__()
    if len(formats) > format_limits.max_formats:
        raise FormattingError("format_limit_exceeded")
    for value in formats:
        if type(value) is not ParagraphFormat:
            raise FormattingError("invalid_input")
        value.__post_init__()
    view = project_docx(data, limits=limits, projection_limits=projection_limits)
    if not formats:
        return data
    package_limits = limits or DocxLimits()
    try:
        return _apply(data, formats, view, package_limits, projection_limits, format_limits)
    except StructureError:
        raise FormattingError("unsupported_format") from None


def _apply(data, formats, view, limits, projection_limits, bounds):
    raw = read_main(data, view.source, limits)
    nodes, codec, global_blocked = scan(raw)
    paragraphs = {b.anchor.path: (i, b) for i, b in enumerate(view.blocks) if b.kind == "paragraph"}
    prepared, seen, auxiliary = [], set(), {}

    def part(kind):
        if kind not in auxiliary:
            auxiliary[kind] = load_part(data, view.source, kind, limits, bounds)
        return auxiliary[kind]

    for command in formats:
        a = command.anchor
        if a.source_sha256 != view.source.sha256:
            raise FormattingError("stale_source")
        if a.part_name != view.source.main_part or a.path not in paragraphs:
            raise FormattingError("invalid_anchor")
        index, paragraph = paragraphs[a.path]
        if a.path in seen:
            raise FormattingError("conflicting_formats")
        seen.add(a.path)
        if command.expected_text != paragraph.text:
            raise FormattingError("text_mismatch")
        if command.style_id is not None:
            check_style(part("styles"), command.style_id)
        if command.list_kind != "none":
            numbering = part("numbering")
            if command.list_id is not None:
                check_list(numbering, command.list_id, command.list_kind)
        same = paragraph.style_id == command.style_id and (
            (command.list_kind == "none" and paragraph.numbering_id is None)
            or (
                command.list_id is not None
                and paragraph.numbering_id == command.list_id
                and paragraph.numbering_level in (None, "0")
            )
        )
        prepared.append((index, paragraph, command, same))
    if all(item[3] for item in prepared):
        return data
    if global_blocked:
        raise FormattingError("unsupported_format")
    edits, definitions, expected = [], [], {}
    previous, active_group, ids = None, None, None
    for index, paragraph, command, same in sorted(prepared, key=lambda item: item[0]):
        identity = command.list_id
        if command.list_kind != "none" and identity is None:
            if previous != (index - 1, command.list_kind):
                if ids is None:
                    ids = next_ids(part("numbering"))
                abstract, number = ids
                definitions.append(
                    new_list(part("numbering").namespace, abstract, number, command.list_kind)
                )
                active_group = str(number)
                ids = [abstract + 1, number + 1]
            identity = active_group
            previous = index, command.list_kind
        else:
            previous, active_group = None, None
        expected[paragraph.anchor.path] = command.style_id, identity
        if same:
            continue
        node = nodes[paragraph.anchor.path]
        if word_name(nodes[node.path[:-1]].name) != "body":
            raise FormattingError("invalid_anchor")
        check_target(node, nodes, paragraph)
        edits.append(ppr_patch(raw, nodes, node, command.style_id, identity, codec))
    maximum = min(limits.max_xml_bytes, limits.max_part_bytes)
    replacements = {view.source.main_part: patch_bytes(raw, edits, maximum)}
    if definitions:
        numbering = part("numbering")
        replacements[numbering.name] = numbering_patch(numbering, definitions, maximum)
    result = repack_parts(data, view.source, replacements, limits)
    actual = project_docx(result, limits=limits, projection_limits=projection_limits)

    def shape(blocks):
        return [(b.kind, b.text if b.kind == "paragraph" else None) for b in blocks]

    if shape(actual.blocks) != shape(view.blocks):
        raise FormattingError("unsupported_format")
    for paragraph in actual.blocks:
        if paragraph.anchor.path in expected:
            style, identity = expected[paragraph.anchor.path]
            if (
                paragraph.style_id != style
                or paragraph.numbering_id != identity
                or (identity is not None and paragraph.numbering_level not in (None, "0"))
            ):
                raise FormattingError("unsupported_format")
    return result
