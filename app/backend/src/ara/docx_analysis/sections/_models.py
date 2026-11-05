"""Immutable reference metadata, explicitly not a visible-text capability."""

from dataclasses import dataclass, field, fields

from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-sections/current-header-footer-definitions-v1"


class SectionCatalogError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid section-catalog input or limits.",
        "source_mismatch": "Section-catalog source hash does not match.",
        "section_limit_exceeded": "Section catalog exceeds a technical limit.",
    }

    def __init__(self, code):
        self.code = code if type(code) is str and code in self._MESSAGES else "invalid_input"
        super().__init__(self._MESSAGES[self.code])


def budget(count, maximum):
    if count > maximum:
        raise SectionCatalogError("section_limit_exceeded")


@dataclass(frozen=True, slots=True)
class SectionLimits:
    max_xml_nodes: int = 100000
    max_xml_depth: int = 128
    max_xml_characters: int = 8388608
    max_sections: int = 4096
    max_references: int = 24576
    max_histories: int = 20000
    max_manifest_bytes: int = 33554432

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name, None)
            if type(value) is not int or not 1 <= value <= f.default:
                raise SectionCatalogError("invalid_input")


@dataclass(frozen=True, slots=True)
class SectionReference:
    kind: str
    variant: str
    anchor: SourceAnchor = field(repr=False)
    part_name: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class SectionBinding:
    kind: str
    variant: str
    part_name: str | None = field(repr=False)
    definition_anchor: SourceAnchor | None = field(repr=False)
    origin_section: int | None


@dataclass(frozen=True, slots=True)
class Section:
    index: int
    anchor: SourceAnchor | None = field(repr=False)
    paragraph_anchor: SourceAnchor | None = field(repr=False)
    first_page: bool
    references: tuple[SectionReference, ...] = field(repr=False)
    bindings: tuple[SectionBinding, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class SectionStory:
    kind: str
    part_name: str = field(repr=False)
    root_anchor: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class SectionHistory:
    kind: str
    anchor: SourceAnchor = field(repr=False)
    owner_anchor: SourceAnchor = field(repr=False)
    previous_anchor: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class SectionIssue:
    code: str
    anchor: SourceAnchor | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class SectionCatalog:
    source_sha256: str
    profile: str
    status: str
    main_part: str = field(repr=False)
    settings_part: str | None = field(repr=False)
    even_and_odd: bool | None
    sections: tuple[Section, ...] = field(repr=False)
    stories: tuple[SectionStory, ...] = field(repr=False)
    histories: tuple[SectionHistory, ...] = field(repr=False)
    issues: tuple[SectionIssue, ...] = field(repr=False)
    catalog_sha256: str


class Refused(Exception):
    def __init__(self, code, anchor=None):
        self.issue = SectionIssue(code, anchor)
        super().__init__(code)


def require(condition, code, anchor=None):
    if not condition:
        raise Refused(code, anchor)
