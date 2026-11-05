"""Detached resolution records; construction alone never proves stored evidence."""

from dataclasses import dataclass, field, fields
from uuid import UUID

from ara.documents.storage import DocumentError
from ara.docx_analysis.storage_codec import AttemptBundle, ResultBundle, SourceBundle
from ara.docx_review_preferences._models import Origin, PreferencesState, require


def bounded(condition):
    if not condition:
        raise DocumentError(
            413, "preferences_resolution_limit", "Saved visibility exceeds a technical limit"
        )


@dataclass(frozen=True, slots=True)
class ResolutionLimits:
    max_origins: int = 64
    max_record_bytes: int = 268435456
    max_text_characters: int = 8388608

    def __post_init__(self):
        require(
            all(
                type(getattr(self, f.name, None)) is int and 1 <= getattr(self, f.name) <= f.default
                for f in fields(self)
            )
        )


def checked_limits(limits):
    value = ResolutionLimits() if limits is None else limits
    require(type(value) is ResolutionLimits)
    value.__post_init__()
    return value


def buffers(origin):
    require(type(origin) is Origin, "storage_error")
    require(
        type(origin.source) is SourceBundle
        and type(origin.attempt) is AttemptBundle
        and type(origin.result) is ResultBundle,
        "storage_error",
    )
    values = (
        origin.source.source_data,
        origin.source.snapshot_data,
        origin.source.command_data,
        origin.source.execution_spec,
        origin.attempt.request_data,
        origin.result.reply_data,
        origin.result.result_data,
    )
    require(all(type(v) is bytes for v in values), "storage_error")
    return values


def weight(origin):
    return sum(len(v) for v in buffers(origin))


@dataclass(frozen=True, slots=True)
class DismissalRef:
    key: str
    run_id: UUID
    result_sha256: str
    finding_id: str
    hidden_at_revision: int


@dataclass(frozen=True, slots=True)
class FindingAlias:
    finding_id: str
    key: str
    origin_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolutionInput:
    state: PreferencesState = field(repr=False)
    target: Origin = field(repr=False)
    origins: tuple[Origin, ...] = field(repr=False)
    decisions: tuple[DismissalRef, ...] = field(repr=False)
    limits: ResolutionLimits


@dataclass(frozen=True, slots=True)
class Resolution:
    state: PreferencesState = field(repr=False)
    target: Origin = field(repr=False)
    origins: tuple[Origin, ...] = field(repr=False)
    decisions: tuple[DismissalRef, ...] = field(repr=False)
    limits: ResolutionLimits
    finding_keys: tuple
    hidden_keys: tuple[str, ...]
    aliases: tuple[FindingAlias, ...]
