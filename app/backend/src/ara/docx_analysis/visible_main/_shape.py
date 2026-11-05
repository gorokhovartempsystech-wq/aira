"""Bound exact DTO schemas before serialization or equality with trusted output."""

import re
from dataclasses import fields
from types import UnionType
from typing import get_args, get_origin, get_type_hints
from uuid import UUID

from ara.docx_analysis.visibility import (
    ResolvedStyle,
    StyleContext,
    StyleIssue,
    VisibilityProperties,
    VisibilityValue,
)
from ara.docx_analysis.visibility.rules import RunVisibility
from ara.docx_package.projection import SourceAnchor

from ._build import valid_identity
from ._canonical import digest
from ._models import (
    POLICY,
    PROFILE,
    VisibleCoverage,
    VisibleFragment,
    VisibleLimits,
    VisibleParagraphContext,
    VisiblePiece,
    VisibleRunContext,
    VisibleSnapshot,
    VisibleViewError,
)

RECORDS = (
    SourceAnchor,
    ResolvedStyle,
    StyleContext,
    StyleIssue,
    VisibilityProperties,
    VisibilityValue,
    RunVisibility,
    VisibleCoverage,
    VisibleFragment,
    VisibleParagraphContext,
    VisiblePiece,
    VisibleRunContext,
    VisibleSnapshot,
)
SCHEMAS = {t: get_type_hints(t) for t in RECORDS}
HASH = re.compile(r"[0-9a-f]{64}")
ENUMS = {
    (VisibleSnapshot, "profile"): {PROFILE},
    (VisibleSnapshot, "policy_version"): {POLICY},
    (StyleContext, "profile"): {"docx-visibility/styles-context-v1"},
    (StyleContext, "status"): {"ready", "absent", "blocked"},
    (ResolvedStyle, "style_type"): {"paragraph", "character", "table", "numbering"},
    (ResolvedStyle, "status"): {"resolved", "blocked", "opaque"},
    (RunVisibility, "status"): {"visible", "hidden", "blocked"},
    (VisiblePiece, "kind"): {"text", "tab", "break"},
    (VisibleCoverage, "status"): {"included", "excluded", "metadata", "empty", "blocked"},
}


def require(value):
    if not value:
        raise VisibleViewError("invalid_snapshot")


class Shape:
    def __init__(
        self, limits, *, profile=PROFILE, style_profile="docx-visibility/styles-context-v1"
    ):
        self.limits = limits
        self.profile = profile
        self.style_profile = style_profile
        self.counts = {}
        self.caps = dict(
            paragraphs=limits.max_paragraphs,
            runs=limits.max_runs,
            fragments=limits.max_paragraphs,
            pieces=limits.max_pieces,
            coverage=limits.max_coverage_items,
            styles=limits.styles.max_styles,
            issues=limits.styles.max_issues,
            path=limits.max_xml_depth,
        )

    def value(self, value, expected, name="", owner=None):
        origin = get_origin(expected)
        if origin is UnionType:
            options = get_args(expected)
            if value is None:
                require(type(None) in options)
                return
            expected = next(t for t in options if t is not type(None))
            origin = get_origin(expected)
        if origin is tuple:
            require(type(value) is tuple)
            maximum = self.caps[name]
            require(len(value) <= maximum)
            if name != "path":
                self.counts[name] = self.counts.get(name, 0) + len(value)
                require(self.counts[name] <= maximum)
            for child in value:
                self.value(child, get_args(expected)[0], name, owner)
        elif expected in SCHEMAS:
            require(type(value) is expected)
            for f in fields(expected):
                self.value(getattr(value, f.name), SCHEMAS[expected][f.name], f.name, expected)
        elif expected is UUID:
            require(type(value) is UUID and type(value.int) is int and 0 <= value.int < 2**128)
        elif expected is str:
            require(type(value) is str)
            maximum = self.limits.max_xml_characters
            if name in ("analysis_text", "text"):
                maximum = self.limits.max_text_characters
            elif name in ("main_part", "part_name", "styles_part"):
                maximum = 65535
                require(
                    bool(value)
                    and "\\" not in value
                    and all(p not in ("", ".", "..") for p in value.split("/"))
                )
            elif name.endswith("style_id") or name in (
                "style_id",
                "based_on",
                "default_paragraph_style",
                "default_character_style",
            ):
                maximum = 253
                require(bool(value))
            elif name.endswith("sha256"):
                require(HASH.fullmatch(value) is not None)
                maximum = 64
            elif name == "fragment_id":
                require(re.fullmatch(r"vf-[0-9a-f]{64}", value) is not None)
                maximum = 67
            else:
                maximum = 128
            require(len(value) <= maximum)
            enum = ENUMS.get((owner, name))
            if owner is VisibleSnapshot and name == "profile":
                enum = {self.profile}
            if owner is StyleContext and name == "profile":
                enum = {self.style_profile}
            if enum is not None:
                require(value in enum)
        elif expected is int:
            maximum = (
                (2**63 - 1)
                if name == "storage_revision"
                else self.limits.max_xml_nodes - 1
                if name == "path"
                else self.limits.max_text_characters
            )
            require(type(value) is int and 0 <= value <= maximum)
        elif expected is bool:
            require(type(value) is bool)
        else:
            require(False)


def validate(snapshot, limits):
    return _validate(snapshot, limits, profile=PROFILE)


def _validate(snapshot, limits, *, profile):
    try:
        # A smaller per-call budget does not turn a valid prior snapshot into
        # malformed data. The authoritative rebuild applies the caller's caps.
        Shape(VisibleLimits(), profile=profile).value(snapshot, VisibleSnapshot)
        require(
            valid_identity(snapshot.document_id, snapshot.storage_revision, snapshot.source_sha256)
        )
        # Streaming size check before authoritative rebuild; never asdict foreign objects.
        digest(snapshot, limits.max_manifest_bytes, omit_hash=True)
    except VisibleViewError:
        raise
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
        raise VisibleViewError("invalid_snapshot") from None
