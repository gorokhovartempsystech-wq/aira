"""Initial storage schema. Access enforcement belongs to the application layer."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ara.db import Base


class IdentityAndTimestamp:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class User(IdentityAndTimestamp, Base):
    __tablename__ = "users"


class Project(IdentityAndTimestamp, Base):
    __tablename__ = "projects"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_projects_owner"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)


class Document(IdentityAndTimestamp, Base):
    __tablename__ = "documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["id", "current_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_documents_current_version",
            use_alter=True,
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_documents_project"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentVersion(IdentityAndTimestamp, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "id", name="uq_document_versions_document_id_id"),
        ForeignKeyConstraint(
            ["document_id", "parent_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_document_versions_parent",
        ),
        CheckConstraint("parent_version_id <> id", name="ck_document_versions_not_self_parent"),
        CheckConstraint("jsonb_typeof(blocks) = 'array'", name="ck_document_versions_blocks_array"),
        CheckConstraint(
            "jsonb_typeof(provenance) = 'object'", name="ck_document_versions_provenance_object"
        ),
        CheckConstraint(
            "jsonb_typeof(import_omissions) = 'array'",
            name="ck_document_versions_import_omissions_array",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", name="fk_document_versions_document"), nullable=False
    )
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    blocks: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    import_omissions: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class ContextRevision(IdentityAndTimestamp, Base):
    __tablename__ = "context_revisions"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(items) = 'array'", name="ck_context_revisions_items_array"),
        UniqueConstraint("document_id", "owner_id", "id", name="uq_context_revisions_scope_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", name="fk_context_revisions_document"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_context_revisions_owner"), nullable=False, index=True
    )
    items: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)


class AnalysisRun(IdentityAndTimestamp, Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_analysis_runs_id_owner"),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_analysis_runs_owner_key"),
        ForeignKeyConstraint(
            ["document_id", "base_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_analysis_runs_base_version",
        ),
        ForeignKeyConstraint(
            ["document_id", "owner_id", "context_revision_id"],
            ["context_revisions.document_id", "context_revisions.owner_id", "context_revisions.id"],
            name="fk_analysis_runs_context",
        ),
        CheckConstraint("mode IN ('lint', 'merge')", name="ck_analysis_runs_mode"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_analysis_runs_status"
        ),
        CheckConstraint("execution_mode = 'fixture'", name="ck_analysis_runs_execution_mode"),
        CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 128", name="ck_analysis_runs_key_length"
        ),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_analysis_runs_fingerprint"
        ),
        CheckConstraint(
            "jsonb_typeof(request_payload) = 'object'", name="ck_analysis_runs_request_object"
        ),
        CheckConstraint("attempt_count >= 0", name="ck_analysis_runs_attempt_count"),
        CheckConstraint(
            "max_attempts IS NULL OR max_attempts BETWEEN 1 AND 10",
            name="ck_analysis_runs_max_attempts",
        ),
        CheckConstraint(
            "attempt_count = 0 OR (max_attempts IS NOT NULL AND deadline_at IS NOT NULL AND "
            "attempt_count <= max_attempts)",
            name="ck_analysis_runs_attempt_budget",
        ),
        CheckConstraint(
            "(max_attempts IS NULL) = (deadline_at IS NULL)", name="ck_analysis_runs_policy"
        ),
        CheckConstraint(
            "(status = 'running' AND active_attempt_id IS NOT NULL AND lease_expires_at IS "
            "NOT NULL) OR (status <> 'running' AND active_attempt_id IS NULL AND "
            "lease_expires_at IS NULL)",
            name="ck_analysis_runs_active_attempt",
        ),
        CheckConstraint(
            "(status IN ('succeeded', 'failed')) = (completed_at IS NOT NULL)",
            name="ck_analysis_runs_completed",
        ),
        CheckConstraint(
            "(status = 'failed' AND error_code IS NOT NULL AND error_code IN "
            "('deadline_exceeded', 'attempts_exhausted', 'access_revoked', "
            "'invalid_request', 'invalid_result')) OR (status <> 'failed' AND error_code IS "
            "NULL)",
            name="ck_analysis_runs_error",
        ),
        CheckConstraint(
            "(status = 'succeeded' AND result_payload IS NOT NULL AND incomplete_review IS "
            "NOT NULL) OR (status <> 'succeeded' AND result_payload IS NULL AND "
            "incomplete_review IS NULL)",
            name="ck_analysis_runs_result",
        ),
        CheckConstraint(
            "result_payload IS NULL OR jsonb_typeof(result_payload) = 'object'",
            name="ck_analysis_runs_result_object",
        ),
        ForeignKeyConstraint(
            ["id", "active_attempt_id"],
            ["analysis_attempts.run_id", "analysis_attempts.id"],
            name="fk_analysis_runs_active_attempt",
            use_alter=True,
        ),
        Index("ix_analysis_runs_status_available_at", "status", "available_at"),
        Index("ix_analysis_runs_status_lease_expires_at", "status", "lease_expires_at"),
        Index("ix_analysis_runs_status_created_at", "status", "created_at"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_analysis_runs_owner"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", name="fk_analysis_runs_document"), nullable=False, index=True
    )
    base_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    context_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    execution_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'fixture'")
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    has_import_omissions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    active_attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    incomplete_review: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ReviewRevision(IdentityAndTimestamp, Base):
    __tablename__ = "review_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["analysis_runs.id", "analysis_runs.owner_id"],
            name="fk_review_revisions_run_owner",
        ),
        UniqueConstraint("run_id", "revision_number", name="uq_review_revisions_number"),
        UniqueConstraint("run_id", "owner_id", "id", name="uq_review_revisions_scope_id"),
        UniqueConstraint(
            "run_id", "owner_id", "parent_revision_id", name="uq_review_revisions_child"
        ),
        ForeignKeyConstraint(
            ["run_id", "owner_id", "parent_revision_id"],
            ["review_revisions.run_id", "review_revisions.owner_id", "review_revisions.id"],
            name="fk_review_revisions_parent",
        ),
        CheckConstraint("revision_number > 0", name="ck_review_revisions_number"),
        CheckConstraint(
            "result_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_review_revisions_fingerprint"
        ),
        CheckConstraint(
            "jsonb_typeof(decisions) = 'array'", name="ck_review_revisions_decisions_array"
        ),
        CheckConstraint("parent_revision_id <> id", name="ck_review_revisions_not_self_parent"),
        CheckConstraint(
            "(revision_number = 1) = (parent_revision_id IS NULL)",
            name="ck_review_revisions_root_number",
        ),
        Index(
            "uq_review_revisions_root",
            "run_id",
            unique=True,
            postgresql_where=text("parent_revision_id IS NULL"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_review_revisions_owner"), nullable=False, index=True
    )
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    decisions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)


class AnalysisAttempt(Base):
    __tablename__ = "analysis_attempts"
    __table_args__ = (
        UniqueConstraint("run_id", "attempt_number", name="uq_analysis_attempts_number"),
        UniqueConstraint("run_id", "id", name="uq_analysis_attempts_run_id_id"),
        CheckConstraint("attempt_number > 0", name="ck_analysis_attempts_number"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'expired')",
            name="ck_analysis_attempts_status",
        ),
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="ck_analysis_attempts_finished"
        ),
        CheckConstraint(
            "(status IN ('running', 'succeeded') AND error_code IS NULL) OR (status IN "
            "('failed', 'expired') AND error_code IS NOT NULL AND error_code IN "
            "('adapter_error', 'adapter_timeout', 'invalid_result', 'invalid_request', "
            "'access_revoked', 'lease_expired', 'deadline_exceeded'))",
            name="ck_analysis_attempts_error",
        ),
        CheckConstraint(
            "retry_delay_seconds >= 0 AND retry_delay_seconds <= 300",
            name="ck_analysis_attempts_retry_delay",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'", name="ck_analysis_attempts_metadata_object"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", name="fk_analysis_attempts_run"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", name="fk_analysis_attempts_project"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_delay_seconds: Mapped[float] = mapped_column(Double, nullable=False)
    execution_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)


class DocumentDraft(Base):
    __tablename__ = "document_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "base_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_document_drafts_base_version",
        ),
        CheckConstraint("revision > 0", name="ck_document_drafts_revision"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", name="fk_document_drafts_document"),
        primary_key=True,
        nullable=False,
    )
    base_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )


class DocxDocument(Base):
    """Exact imported package and its current draft, scoped by the owning project."""

    __tablename__ = "docx_documents"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_docx_documents"),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200", name="ck_docx_documents_title_length"
        ),
        CheckConstraint("octet_length(original_data) > 0", name="ck_docx_documents_original_data"),
        CheckConstraint("octet_length(current_data) > 0", name="ck_docx_documents_current_data"),
        CheckConstraint(
            "original_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_documents_original_sha256"
        ),
        CheckConstraint(
            "current_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_documents_current_sha256"
        ),
        CheckConstraint("storage_revision > 0", name="ck_docx_documents_storage_revision"),
        Index("ix_docx_documents_project_created_id", "project_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", name="fk_docx_documents_project"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    original_data: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    original_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    current_data: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    current_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    storage_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )


class DocxEditReceipt(Base):
    """Durable metadata of an acknowledged edit, without storing request text."""

    __tablename__ = "docx_edit_receipts"
    __table_args__ = (
        PrimaryKeyConstraint("document_id", "operation_id", name="pk_docx_edit_receipts"),
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_edit_receipts_request_sha256"
        ),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200", name="ck_docx_edit_receipts_title_length"
        ),
        CheckConstraint("storage_revision > 1", name="ck_docx_edit_receipts_storage_revision"),
        CheckConstraint(
            "current_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_edit_receipts_current_sha256"
        ),
        CheckConstraint("current_size_bytes > 0", name="ck_docx_edit_receipts_current_size_bytes"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("docx_documents.id", name="fk_docx_edit_receipts_document"),
        primary_key=True,
        nullable=False,
    )
    operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    request_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    storage_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    current_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    current_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    document_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )


class DocxEditDraft(Base):
    """One recoverable working copy, separate from the saved Word package."""

    __tablename__ = "docx_edit_drafts"
    __table_args__ = (
        PrimaryKeyConstraint("document_id", name="pk_docx_edit_drafts"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_docx_edit_drafts_payload"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("docx_documents.id", name="fk_docx_edit_drafts_document"),
        primary_key=True,
        nullable=False,
    )
    token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )


class DocxEditorCheckpoint(Base):
    """One versioned full-package working copy; empty slots retain their CAS fence."""

    __tablename__ = "docx_editor_checkpoints"
    __table_args__ = (
        PrimaryKeyConstraint("document_id", name="pk_docx_editor_checkpoints"),
        CheckConstraint("checkpoint_revision > 0", name="ck_docx_editor_cp_revision"),
        CheckConstraint("format_version = 1", name="ck_docx_editor_cp_version"),
        CheckConstraint("phase IN ('empty','working','pending')", name="ck_docx_editor_cp_phase"),
        CheckConstraint("base_storage_revision > 0", name="ck_docx_editor_cp_base_revision"),
        CheckConstraint("base_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_editor_cp_base_hash"),
        CheckConstraint("working_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_editor_cp_work_hash"),
        CheckConstraint(
            "octet_length(working_data) BETWEEN 1 AND 33554432",
            name="ck_docx_editor_cp_work_size",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object' AND octet_length(metadata::text) <= 65536",
            name="ck_docx_editor_cp_metadata",
        ),
        CheckConstraint(
            "(last_request_id IS NULL AND last_request_sha256 IS NULL) OR "
            "(last_request_id IS NOT NULL AND last_request_sha256 IS NOT NULL "
            "AND last_request_sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_docx_editor_cp_request",
        ),
        CheckConstraint(
            "(phase = 'empty' AND base_storage_revision IS NULL AND base_sha256 IS NULL "
            "AND working_data IS NULL AND working_sha256 IS NULL AND metadata IS NULL) OR "
            "(phase IN ('working','pending') AND base_storage_revision IS NOT NULL "
            "AND base_sha256 IS NOT NULL AND working_data IS NOT NULL "
            "AND working_sha256 IS NOT NULL AND metadata IS NOT NULL "
            "AND metadata ? 'pending' AND "
            "((phase = 'working' AND metadata->'pending' = 'null'::jsonb) OR "
            "(phase = 'pending' AND jsonb_typeof(metadata->'pending') = 'object')))",
            name="ck_docx_editor_cp_shape",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("docx_documents.id", name="fk_docx_editor_checkpoints_document"),
        primary_key=True,
        nullable=False,
    )
    checkpoint_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    format_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    base_storage_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    base_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    working_data: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    working_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkpoint_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    last_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_request_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
