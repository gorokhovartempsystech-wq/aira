"""Atomic source-relative paragraph insertion/deletion without I/O or persistence."""

from .. import DocxLimits
from ..projection import ProjectionLimits, project_docx
from ._models import DeleteParagraph, InsertParagraph, StructureError, StructureLimits
from ._package import read_main, repack
from ._xml import check_target, new_paragraph, scan, word_name

__all__ = [
    "InsertParagraph",
    "DeleteParagraph",
    "StructureLimits",
    "StructureError",
    "export_structure",
]


def export_structure(
    data: bytes,
    commands: tuple[InsertParagraph | DeleteParagraph, ...],
    *,
    limits: DocxLimits | None = None,
    projection_limits: ProjectionLimits | None = None,
    structure_limits: StructureLimits | None = None,
) -> bytes:
    """Apply one validated batch against the exact original paragraph anchors."""
    if type(commands) is not tuple:
        raise StructureError("invalid_input")
    if structure_limits is None:
        structure_limits = StructureLimits()
    if type(structure_limits) is not StructureLimits:
        raise StructureError("invalid_input")
    structure_limits.__post_init__()
    if len(commands) > structure_limits.max_commands:
        raise StructureError("structure_limit_exceeded")
    new_count = text_count = 0
    for command in commands:
        if type(command) not in (InsertParagraph, DeleteParagraph):
            raise StructureError("invalid_input")
        command.__post_init__()
        if type(command) is InsertParagraph:
            new_count += len(command.texts)
            text_count += sum(map(len, command.texts))
    if (
        new_count > structure_limits.max_new_paragraphs
        or text_count > structure_limits.max_text_chars
    ):
        raise StructureError("structure_limit_exceeded")
    projection = project_docx(data, limits=limits, projection_limits=projection_limits)
    if not commands:
        return data
    package_limits = limits or DocxLimits()
    original = read_main(data, projection.source, package_limits)
    nodes, codec, global_blocked = scan(original)
    if global_blocked:
        raise StructureError("unsupported_structure")
    paragraphs = {p.anchor.path: p for p in projection.blocks if p.kind == "paragraph"}
    patches, seen, removed, by_path = [], set(), set(), {}
    for command in commands:
        anchor = command.anchor
        if anchor.source_sha256 != projection.source.sha256:
            raise StructureError("stale_source")
        if anchor.part_name != projection.source.main_part or anchor.path not in paragraphs:
            raise StructureError("invalid_anchor")
        node, paragraph = nodes[anchor.path], paragraphs[anchor.path]
        parent = nodes.get(anchor.path[:-1])
        if parent is None or word_name(parent.name) != "body":
            raise StructureError("invalid_anchor")
        if command.expected_text != paragraph.text:
            raise StructureError("text_mismatch")
        if anchor.path in seen:
            raise StructureError("conflicting_commands")
        seen.add(anchor.path)
        check_target(node, nodes, paragraph)
        by_path[anchor.path] = command
        if type(command) is DeleteParagraph:
            patches.append((node.start, node.end, b""))
            removed.add(anchor.path)
        else:
            at = node.start if command.position == "before" else node.end
            namespace = node.name.rpartition("}")[0]
            markup = "".join(new_paragraph(text, namespace) for text in command.texts)
            patches.append((at, at, markup.encode(codec)))
    if len(removed) == len(paragraphs):
        raise StructureError("unsupported_structure")
    patches.sort(key=lambda patch: (patch[0], patch[1]))
    for a, b in zip(patches, patches[1:]):
        # Nonempty adjacent deletions are fine. An insertion touching a delete
        # endpoint or another insertion has ambiguous source ownership.
        if a[1] > b[0] or (a[1] == b[0] and (a[0] == a[1] or b[0] == b[1])):
            raise StructureError("conflicting_commands")
    expected = []
    for block in projection.blocks:
        command = by_path.get(block.anchor.path)
        if type(command) is InsertParagraph and command.position == "before":
            expected.extend(("paragraph", text) for text in command.texts)
        if type(command) is not DeleteParagraph:
            expected.append((block.kind, block.text if block.kind == "paragraph" else None))
        if type(command) is InsertParagraph and command.position == "after":
            expected.extend(("paragraph", text) for text in command.texts)
    changed, at = [], 0
    for start, end, payload in patches:
        changed.extend((original[at:start], payload))
        at = end
    changed.append(original[at:])
    result = repack(data, projection.source, b"".join(changed), package_limits)
    actual = project_docx(result, limits=limits, projection_limits=projection_limits)
    if [(b.kind, b.text if b.kind == "paragraph" else None) for b in actual.blocks] != expected:
        raise StructureError("unsupported_structure")
    return result
