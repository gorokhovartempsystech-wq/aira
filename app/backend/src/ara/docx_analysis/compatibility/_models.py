"""Immutable compatibility decisions; these do not prove content completeness."""

from dataclasses import dataclass, field, fields

from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-compatibility/base-word-selection-v1"


class CompatibilityCatalogError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid compatibility-catalog input or limits.",
        "source_mismatch": "Compatibility-catalog source hash does not match.",
        "compatibility_limit_exceeded": "Compatibility catalog exceeds a technical limit.",
    }

    def __init__(self, code):
        self.code = code if type(code) is str and code in self._MESSAGES else "invalid_input"
        super().__init__(self._MESSAGES[self.code])


def budget(count, maximum):
    if count > maximum:
        raise CompatibilityCatalogError("compatibility_limit_exceeded")


@dataclass(frozen=True, slots=True)
class CompatibilityLimits:
    max_xml_nodes: int = 100000
    max_xml_depth: int = 128
    max_xml_characters: int = 8388608
    max_parts: int = 128
    max_mc_items: int = 10000
    max_namespace_declarations: int = 10000
    max_actions: int = 10000
    max_manifest_bytes: int = 33554432

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name, None)
            if type(value) is not int or not 1 <= value <= f.default:
                raise CompatibilityCatalogError("invalid_input")


@dataclass(frozen=True, slots=True)
class CompatibilityAction:
    kind: str
    anchor: SourceAnchor = field(repr=False)
    selected_anchor: SourceAnchor | None = field(repr=False)
    attribute_names: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class CompatibilityPart:
    part_name: str = field(repr=False)
    root_anchor: SourceAnchor = field(repr=False)
    actions: tuple[CompatibilityAction, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    code: str
    anchor: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class CompatibilityCatalog:
    source_sha256: str
    profile: str
    status: str
    main_part: str = field(repr=False)
    parts: tuple[CompatibilityPart, ...] = field(repr=False)
    issues: tuple[CompatibilityIssue, ...] = field(repr=False)
    catalog_sha256: str


class Refused(Exception):
    def __init__(self, code, anchor):
        self.issue = CompatibilityIssue(code, anchor)
        super().__init__(code)


def require(condition, anchor, code="invalid_compatibility_markup"):
    if not condition:
        raise Refused(code, anchor)
