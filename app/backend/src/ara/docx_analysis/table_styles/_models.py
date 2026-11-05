"""Detached source evidence, not a rendering result or caller capability."""

from dataclasses import dataclass, field, fields

from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-table-styles/neutral-current-v1"


class TableStyleError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid table-style input or limits.",
        "source_mismatch": "Table-style source hash does not match.",
        "table_style_limit_exceeded": "Table-style proof exceeds a technical limit.",
    }

    def __init__(self, code):
        self.code = code if type(code) is str and code in self._MESSAGES else "invalid_input"
        super().__init__(self._MESSAGES[self.code])


def budget(count, maximum):
    if count > maximum:
        raise TableStyleError("table_style_limit_exceeded")


@dataclass(frozen=True, slots=True)
class TableStyleLimits:
    max_xml_nodes: int = 100000
    max_xml_depth: int = 128
    max_xml_characters: int = 8388608
    max_styles: int = 4096
    max_regions: int = 16384
    max_chain_depth: int = 128
    max_chain_links: int = 65536
    max_issues: int = 10000
    max_manifest_bytes: int = 33554432

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name, None)
            if type(value) is not int or not 1 <= value <= item.default:
                raise TableStyleError("invalid_input")


@dataclass(frozen=True, slots=True)
class TableStyleRegion:
    kind: str
    anchor: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class TableStyleIssue:
    code: str
    anchor: SourceAnchor | None = field(repr=False)
    style_id: str | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class TableStyleDefinition:
    style_id: str = field(repr=False)
    anchor: SourceAnchor = field(repr=False)
    based_on: str | None = field(repr=False)
    is_default: bool
    status: str
    regions: tuple[TableStyleRegion, ...] = field(repr=False)
    metadata: tuple[SourceAnchor, ...] = field(repr=False)
    chain: tuple[SourceAnchor, ...] = field(repr=False)
    issues: tuple[TableStyleIssue, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class TableStyleCatalog:
    source_sha256: str
    profile: str
    status: str
    styles_part: str | None = field(repr=False)
    style_context_sha256: str
    default_table_style: str | None = field(repr=False)
    styles: tuple[TableStyleDefinition, ...] = field(repr=False)
    issues: tuple[TableStyleIssue, ...] = field(repr=False)
    catalog_sha256: str
