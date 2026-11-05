"""Detached storage records; constructors are never capabilities."""

import re
from dataclasses import dataclass, field, fields
from uuid import UUID

from ara.docx_analysis.review import ReviewLimits, ReviewProvenance
from ara.docx_analysis.review._models import ReviewError
from ara.docx_analysis.visible_main import VisibleSnapshot


class StorageCodecError(ValueError):
    MESSAGES = {
        "invalid_input": "Invalid analysis storage input or limits.",
        "corrupt_record": "Stored analysis record is invalid.",
        "codec_limit_exceeded": "Analysis storage exceeds a technical limit.",
        "unsupported_version": "Analysis storage version is not supported.",
    }

    def __init__(self, code):
        self.code = code
        self.message = self.MESSAGES[code]
        super().__init__(self.message)


def require(condition, code="invalid_input"):
    if not condition:
        raise StorageCodecError(code)


def uuid(value):
    return (
        type(value) is UUID and type(getattr(value, "int", None)) is int and 0 <= value.int < 2**128
    )


def counter(value, minimum=1):
    return type(value) is int and minimum <= value < 2**63


def digest(value):
    return (
        type(value) is str and len(value) == 64 and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


@dataclass(frozen=True, slots=True)
class SavedCheckCommand:
    document_id: UUID
    registry_id: UUID
    session_id: UUID
    save_command_id: UUID
    command_sequence: int
    session_revision: int
    storage_revision: int
    source_sha256: str

    def __post_init__(self):
        require(
            all(
                uuid(getattr(self, n, None))
                for n in ("document_id", "registry_id", "session_id", "save_command_id")
            )
        )
        require(
            counter(getattr(self, "command_sequence", None))
            and counter(getattr(self, "session_revision", None), 0)
            and counter(getattr(self, "storage_revision", None))
            and digest(getattr(self, "source_sha256", None))
        )


@dataclass(frozen=True, slots=True)
class RetryCheckCommand:
    document_id: UUID
    retry_of_run_id: UUID

    def __post_init__(self):
        require(
            uuid(getattr(self, "document_id", None))
            and uuid(getattr(self, "retry_of_run_id", None))
        )


@dataclass(frozen=True, slots=True)
class ExecutionSpec:
    execution_kind: str
    engine_version: str
    models_version: str = field(repr=False)
    model_sha256: str
    adapter_sha256: str

    def __post_init__(self):
        try:
            ReviewProvenance(UUID(int=0), *(getattr(self, f.name, None) for f in fields(self)))
        except ReviewError:
            raise StorageCodecError("invalid_input") from None


@dataclass(frozen=True, slots=True)
class CodecLimits:
    max_source_bytes: int = 33554432
    max_manifest_bytes: int = 33554432
    max_command_bytes: int = 16384
    max_execution_bytes: int = 4096
    max_fragments: int = 512
    max_text_characters: int = 1000000
    review: ReviewLimits = field(default_factory=ReviewLimits)

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name, None)
            if f.name == "review":
                require(type(value) is ReviewLimits)
                try:
                    value.__post_init__()
                except ReviewError:
                    raise StorageCodecError("invalid_input") from None
            else:
                require(type(value) is int and 1 <= value <= f.default)


def checked(limits):
    limits = CodecLimits() if limits is None else limits
    require(type(limits) is CodecLimits)
    limits.__post_init__()
    return limits


@dataclass(frozen=True, slots=True)
class EncodedValue:
    data: bytes = field(repr=False)
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceBundle:
    document_id: UUID
    storage_revision: int
    source_data: bytes = field(repr=False)
    source_sha256: str
    profile: str
    policy_version: str
    snapshot_data: bytes = field(repr=False)
    snapshot_sha256: str
    command_data: bytes = field(repr=False)
    command_sha256: str
    execution_spec: bytes = field(repr=False)
    execution_spec_sha256: str
    execution_kind: str
    format_version: int = 1


@dataclass(frozen=True, slots=True)
class RestoredSource:
    snapshot: VisibleSnapshot = field(repr=False)
    command: SavedCheckCommand | RetryCheckCommand = field(repr=False)
    execution: ExecutionSpec = field(repr=False)


@dataclass(frozen=True, slots=True)
class AttemptBundle:
    attempt_id: UUID
    request_data: bytes = field(repr=False)
    request_sha256: str


@dataclass(frozen=True, slots=True)
class ResultBundle:
    reply_data: bytes = field(repr=False)
    reply_sha256: str
    result_data: bytes = field(repr=False)
    result_sha256: str
    findings_count: int
    questions_count: int
    no_findings: bool
