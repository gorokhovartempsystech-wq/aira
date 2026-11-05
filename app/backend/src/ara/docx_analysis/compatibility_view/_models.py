"""Read-only logical navigation; every retained node still names original XML."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from ara.docx_analysis.compatibility import (
    CompatibilityCatalog,
    CompatibilityCatalogError,
    CompatibilityIssue,
)
from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-compatibility/original-logical-view-v1"


@dataclass(frozen=True, slots=True, eq=False)
class ViewNode:
    anchor: SourceAnchor = field(repr=False)
    tag: str = field(repr=False)
    attrib: Mapping[str, str] = field(repr=False)
    text: str | None = field(repr=False)
    tail: str | None = field(repr=False)
    children: tuple["ViewNode", ...] = field(repr=False)

    def get(self, name, default=None):
        return self.attrib.get(name, default)

    def __len__(self):
        return len(self.children)

    def __getitem__(self, index):
        return self.children[index]

    def __iter__(self):
        return iter(self.children)


@dataclass(frozen=True, slots=True)
class ViewPart:
    part_name: str = field(repr=False)
    root: ViewNode = field(repr=False)
    nodes: Mapping[tuple[int, ...], ViewNode] = field(repr=False)


@dataclass(frozen=True, slots=True)
class CompatibilityView:
    source_sha256: str
    profile: str
    status: str
    catalog: CompatibilityCatalog = field(repr=False)
    parts: tuple[ViewPart, ...] = field(repr=False)
    issues: tuple[CompatibilityIssue, ...] = field(repr=False)

    def node(self, anchor):
        if type(anchor) is not SourceAnchor:
            raise CompatibilityCatalogError("invalid_input")
        sha = getattr(anchor, "source_sha256", None)
        part = getattr(anchor, "part_name", None)
        path = getattr(anchor, "path", None)
        if (
            type(sha) is not str
            or re.fullmatch(r"[0-9a-f]{64}", sha) is None
            or type(part) is not str
            or not part
            or type(path) is not tuple
            or len(path) > 128
            or any(type(i) is not int or i < 0 for i in path)
        ):
            raise CompatibilityCatalogError("invalid_input")
        if sha != self.source_sha256:
            raise CompatibilityCatalogError("source_mismatch")
        for candidate in self.parts:
            if candidate.part_name == part:
                return candidate.nodes.get(path)
        return None
