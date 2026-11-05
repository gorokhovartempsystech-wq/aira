"""Classify every OPC part; classification does not prove text coverage."""

import re
from dataclasses import dataclass, field, fields
from hashlib import sha256

from ara.docx_package import DocxError, DocxLimits, open_docx

_WORD_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml."
_RELS_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
_STORIES = {
    _WORD_TYPE + name + "+xml": name for name in ("header", "footer", "footnotes", "endnotes")
}
_STORIES[_WORD_TYPE + "document.glossary+xml"] = "glossary"
_AUXILIARY = frozenset(
    _WORD_TYPE + name + "+xml"
    for name in ("styles", "numbering", "settings", "webSettings", "fontTable")
) | {
    "application/vnd.openxmlformats-officedocument.theme+xml",
    "application/vnd.openxmlformats-package.core-properties+xml",
    "application/vnd.openxmlformats-package.custom-properties+xml",
    "application/vnd.openxmlformats-officedocument.extended-properties+xml",
}
_IMAGES = frozenset(
    (
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/bmp",
        "image/tiff",
        "image/x-emf",
        "image/x-wmf",
        "image/svg+xml",
    )
)


class InventoryError(ValueError):
    """Static diagnostics without source names, content or external targets."""

    _MESSAGES = {
        "invalid_input": "Invalid DOCX inventory input or limits.",
        "source_mismatch": "DOCX inventory source hash does not match.",
        "inventory_limit_exceeded": "DOCX inventory exceeds a technical limit.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class InventoryLimits:
    max_parts: int = 4096
    max_relationships: int = 10000

    def __post_init__(self) -> None:
        if any(
            type(getattr(self, f.name)) is not int or getattr(self, f.name) <= 0
            for f in fields(self)
        ):
            raise InventoryError("invalid_input")


@dataclass(frozen=True, slots=True)
class AnalysisPolicy:
    version: str = field(default="docx-analysis-policy/final-no-comments-v1", init=False)
    revisions: str = field(default="final", init=False)
    comments: str = field(default="preserve_exclude", init=False)


@dataclass(frozen=True, slots=True)
class InventoryPart:
    name: str = field(repr=False)
    content_type: str | None = field(repr=False)
    size_bytes: int
    sha256: str
    category: str
    disposition: str


@dataclass(frozen=True, slots=True)
class InventoryRelationship:
    source_part: str = field(repr=False)
    relationship_id: str = field(repr=False)
    relationship_type: str = field(repr=False)
    target_mode: str
    resolved_part: str | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class DocxInventory:
    source_sha256: str
    size_bytes: int
    main_part: str = field(repr=False)
    policy: AnalysisPolicy
    parts: tuple[InventoryPart, ...] = field(repr=False)
    relationships: tuple[InventoryRelationship, ...] = field(repr=False)


def _classify(name: str, content_type: str | None, main_part: str) -> tuple[str, str]:
    if name == main_part:
        return "main_body", "requires_reader"
    if (
        name.casefold() == "[content_types].xml"
        and content_type is None
        or content_type == _RELS_TYPE
    ):
        return "package_metadata", "metadata"
    if content_type in _STORIES:
        return _STORIES[content_type], "requires_reader"
    if content_type == _WORD_TYPE + "comments+xml":
        return "comments", "preserve_excluded"
    if content_type in _AUXILIARY:
        return "auxiliary", "metadata"
    if content_type in _IMAGES:
        return "image", "requires_media_accounting"
    return "unknown", "requires_reader"


def inventory_docx(
    data: bytes,
    *,
    source_sha256: str,
    limits: InventoryLimits | None = None,
) -> DocxInventory:
    """Validate exact bytes; return detached metadata without reading remote targets."""
    if (
        type(data) is not bytes
        or type(source_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise InventoryError("invalid_input")
    if limits is None:
        limits = InventoryLimits()
    if type(limits) is not InventoryLimits:
        raise InventoryError("invalid_input")
    limits.__post_init__()
    if len(data) > DocxLimits().max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise InventoryError("source_mismatch")
    source = open_docx(data)
    if (
        len(source.entries) > limits.max_parts
        or len(source.relationships) > limits.max_relationships
    ):
        raise InventoryError("inventory_limit_exceeded")
    parts = tuple(
        InventoryPart(
            e.name,
            e.content_type,
            e.size_bytes,
            e.sha256,
            *_classify(e.name, e.content_type, source.main_part),
        )
        for e in source.entries
    )
    links = tuple(
        InventoryRelationship(
            r.source_part, r.relationship_id, r.relationship_type, r.target_mode, r.resolved_part
        )
        for r in source.relationships
    )
    return DocxInventory(
        source.sha256, source.size_bytes, source.main_part, AnalysisPolicy(), parts, links
    )
