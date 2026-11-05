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


class DocxAnalysisSource(Base):
    """Scoped DOCX analysis record; integrity validation belongs to the service."""

    __tablename__ = "docx_analysis_sources"
    __table_args__ = (
        PrimaryKeyConstraint("document_id", "source_sha256", name="pk_docx_analysis_sources"),
        ForeignKeyConstraint(["document_id"], ["docx_documents.id"], name="fk_das_document"),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_das_hash"),
        CheckConstraint("octet_length(source_data) BETWEEN 1 AND 33554432", name="ck_das_size"),
        CheckConstraint("isfinite(created_at)", name="ck_das_created"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True
    )
    source_sha256: Mapped[str] = mapped_column(Text(), nullable=False, primary_key=True)
    source_data: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )


class DocxAnalysisRun(Base):
    """Scoped DOCX analysis record; integrity validation belongs to the service."""

    __tablename__ = "docx_analysis_runs"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_docx_analysis_runs"),
        UniqueConstraint("document_id", "id", name="uq_dar_document_id"),
        UniqueConstraint("document_id", "client_request_id", name="uq_dar_request"),
        UniqueConstraint("document_id", "accepted_order", name="uq_dar_order"),
        UniqueConstraint("document_id", "id", "status", name="uq_dar_publication"),
        UniqueConstraint("document_id", "id", "attempt_id", name="uq_dar_attempt_binding"),
        ForeignKeyConstraint(
            ["document_id", "source_sha256"],
            ["docx_analysis_sources.document_id", "docx_analysis_sources.source_sha256"],
            name="fk_dar_source",
        ),
        ForeignKeyConstraint(["accepted_project_id"], ["projects.id"], name="fk_dar_project"),
        ForeignKeyConstraint(["accepted_owner_id"], ["users.id"], name="fk_dar_owner"),
        ForeignKeyConstraint(
            ["document_id", "retry_of_run_id"],
            ["docx_analysis_runs.document_id", "docx_analysis_runs.id"],
            name="fk_dar_retry",
        ),
        CheckConstraint("storage_revision > 0 AND accepted_order > 0", name="ck_dar_counters"),
        CheckConstraint("format_version = 1", name="ck_dar_version"),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dar_source_hash"),
        CheckConstraint("command_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dar_command_hash"),
        CheckConstraint("snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dar_snapshot_hash"),
        CheckConstraint("execution_spec_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dar_execution_hash"),
        CheckConstraint("result_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dar_result_hash"),
        CheckConstraint(
            "octet_length(command_data) BETWEEN 1 AND 16384", name="ck_dar_command_size"
        ),
        CheckConstraint(
            "octet_length(snapshot_data) BETWEEN 1 AND 33554432", name="ck_dar_snapshot_size"
        ),
        CheckConstraint(
            "octet_length(execution_spec) BETWEEN 1 AND 4096", name="ck_dar_execution_size"
        ),
        CheckConstraint("profile ~ '^[a-z0-9][a-z0-9/_.-]{0,127}$'", name="ck_dar_profile"),
        CheckConstraint("policy_version ~ '^[a-z0-9][a-z0-9/_.-]{0,127}$'", name="ck_dar_policy"),
        CheckConstraint(
            "execution_kind IN ('fixture','local_model')", name="ck_dar_execution_kind"
        ),
        CheckConstraint(
            (
                " (start_kind = 'saved' AND retry_of_run_id IS NULL) OR (start_kind = 'retry' "
                "AND retry_of_run_id IS NOT NULL AND retry_of_run_id <> id) "
            ),
            name="ck_dar_start",
        ),
        CheckConstraint(
            (
                " status IN "
                "('queued','running','cancel_requested','succeeded','failed','cancelled','timed_o"
                "ut') "
            ),
            name="ck_dar_status",
        ),
        CheckConstraint(
            (
                " (status = 'queued' AND stage = 'queued') OR (status = 'running' AND stage IN "
                "('preparing_document','loading_model','analyzing','validating_result','finishing"
                "')) OR (status IN "
                "('cancel_requested','succeeded','failed','cancelled','timed_out') AND stage = "
                "status) "
            ),
            name="ck_dar_stage",
        ),
        CheckConstraint(
            (
                " isfinite(created_at) AND isfinite(deadline_at) AND isfinite(updated_at) AND "
                "deadline_at = created_at + INTERVAL '300 seconds' AND updated_at >= created_at "
                "AND (started_at IS NULL OR (isfinite(started_at) AND started_at >= created_at "
                "AND started_at < deadline_at)) AND (heartbeat_at IS NULL OR "
                "(isfinite(heartbeat_at) AND heartbeat_at >= started_at AND heartbeat_at < "
                "deadline_at)) AND (lease_expires_at IS NULL OR (isfinite(lease_expires_at) AND "
                "lease_expires_at > heartbeat_at AND lease_expires_at <= heartbeat_at + INTERVAL "
                "'15 seconds' AND lease_expires_at <= deadline_at)) AND (cancel_requested_at IS "
                "NULL OR (isfinite(cancel_requested_at) AND cancel_requested_at >= created_at)) "
                "AND (finished_at IS NULL OR (isfinite(finished_at) AND finished_at >= "
                "created_at)) "
            ),
            name="ck_dar_times",
        ),
        CheckConstraint(
            (
                " (attempt_id IS NULL AND started_at IS NULL AND heartbeat_at IS NULL AND "
                "lease_expires_at IS NULL) OR (attempt_id IS NOT NULL AND started_at IS NOT NULL "
                "AND heartbeat_at IS NOT NULL) "
            ),
            name="ck_dar_attempt_shape",
        ),
        CheckConstraint(
            (
                " (status = 'queued' AND fence = 0 AND attempt_id IS NULL AND finished_at IS "
                "NULL AND cancel_requested_at IS NULL AND result_sha256 IS NULL AND error_code "
                "IS NULL) OR (status = 'running' AND fence = 1 AND attempt_id IS NOT NULL AND "
                "lease_expires_at IS NOT NULL AND finished_at IS NULL AND cancel_requested_at IS "
                "NULL AND result_sha256 IS NULL AND error_code IS NULL) OR (status = "
                "'cancel_requested' AND fence = 2 AND attempt_id IS NOT NULL AND "
                "lease_expires_at IS NOT NULL AND finished_at IS NULL AND cancel_requested_at IS "
                "NOT NULL AND result_sha256 IS NULL AND error_code IS NULL) OR (status = "
                "'succeeded' AND fence = 2 AND attempt_id IS NOT NULL AND lease_expires_at IS "
                "NULL AND finished_at IS NOT NULL AND finished_at < deadline_at AND "
                "cancel_requested_at IS NULL AND result_sha256 IS NOT NULL AND error_code IS "
                "NULL) OR (status IN ('failed','cancelled','timed_out') AND ((attempt_id IS NULL "
                "AND fence = 1) OR (attempt_id IS NOT NULL AND fence = 2)) AND lease_expires_at "
                "IS NULL AND finished_at IS NOT NULL AND result_sha256 IS NULL AND error_code IS "
                "NOT NULL) "
            ),
            name="ck_dar_lifecycle",
        ),
        CheckConstraint(
            (
                " error_code IS NULL OR error_code IN "
                "('interrupted','ownership_changed','unsupported_analysis_content','empty_documen"
                "t', 'analysis_limit_exceeded','model_unavailable','model_input_limit_exceeded', "
                "'invalid_result','adapter_error','source_corrupt','cancelled','deadline_exceeded"
                "') "
            ),
            name="ck_dar_failure",
        ),
        CheckConstraint(
            (
                " (status NOT IN ('failed','cancelled','timed_out')) OR (status = 'failed' AND "
                "error_code NOT IN ('cancelled','deadline_exceeded')) OR (status = 'cancelled' "
                "AND error_code = 'cancelled' AND cancel_requested_at IS NOT NULL) OR (status = "
                "'timed_out' AND error_code = 'deadline_exceeded' AND (finished_at >= "
                "deadline_at OR timeout_basis = 'continuous')) "
            ),
            name="ck_dar_terminal_reason",
        ),
        CheckConstraint(
            "timeout_basis = 'wall' OR (timeout_basis = 'continuous' AND status = 'timed_out')",
            name="ck_dar_timeout_basis",
        ),
        ForeignKeyConstraint(
            ["document_id", "id", "attempt_id"],
            [
                "docx_analysis_attempts.document_id",
                "docx_analysis_attempts.run_id",
                "docx_analysis_attempts.id",
            ],
            name="fk_dar_attempt",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["document_id", "id", "result_sha256"],
            [
                "docx_analysis_results.document_id",
                "docx_analysis_results.run_id",
                "docx_analysis_results.result_sha256",
            ],
            name="fk_dar_result",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index(
            "uq_dar_active_document",
            "document_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running','cancel_requested')"),
        ),
        Index(
            "ix_dar_queue",
            "created_at",
            "id",
            unique=False,
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "ix_dar_deadline",
            "deadline_at",
            "id",
            unique=False,
            postgresql_where=text("status IN ('queued','running','cancel_requested')"),
        ),
        Index(
            "ix_dar_lease",
            "lease_expires_at",
            "id",
            unique=False,
            postgresql_where=text("status IN ('running','cancel_requested')"),
        ),
        Index(
            "ix_dar_latest_success",
            "document_id",
            text("accepted_order DESC"),
            unique=False,
            postgresql_where=text("status = 'succeeded'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_sha256: Mapped[str] = mapped_column(Text(), nullable=False)
    storage_revision: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    accepted_order: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    accepted_project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    accepted_owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    start_kind: Mapped[str] = mapped_column(Text(), nullable=False)
    retry_of_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    command_data: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    command_sha256: Mapped[str] = mapped_column(Text(), nullable=False)
    format_version: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    profile: Mapped[str] = mapped_column(Text(), nullable=False)
    policy_version: Mapped[str] = mapped_column(Text(), nullable=False)
    snapshot_data: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(Text(), nullable=False)
    execution_kind: Mapped[str] = mapped_column(Text(), nullable=False)
    execution_spec: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    execution_spec_sha256: Mapped[str] = mapped_column(Text(), nullable=False)
    status: Mapped[str] = mapped_column(Text(), nullable=False)
    stage: Mapped[str] = mapped_column(Text(), nullable=False)
    fence: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    result_sha256: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text(), nullable=True)
    timeout_basis: Mapped[str] = mapped_column(
        Text(), nullable=False, server_default=text("'wall'")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocxAnalysisAttempt(Base):
    """Scoped DOCX analysis record; integrity validation belongs to the service."""

    __tablename__ = "docx_analysis_attempts"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_docx_analysis_attempts"),
        UniqueConstraint("run_id", name="uq_daa_run"),
        UniqueConstraint("document_id", "run_id", "id", name="uq_daa_scope"),
        ForeignKeyConstraint(
            ["document_id", "run_id", "id"],
            [
                "docx_analysis_runs.document_id",
                "docx_analysis_runs.id",
                "docx_analysis_runs.attempt_id",
            ],
            name="fk_daa_run",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        CheckConstraint("claim_fence = 1", name="ck_daa_fence"),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="ck_daa_request_hash"),
        CheckConstraint(
            "octet_length(request_data) BETWEEN 1 AND 8388608", name="ck_daa_request_size"
        ),
        CheckConstraint("isfinite(created_at)", name="ck_daa_created"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    claim_fence: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    worker_instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_data: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    request_sha256: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocxAnalysisResult(Base):
    """Scoped DOCX analysis record; integrity validation belongs to the service."""

    __tablename__ = "docx_analysis_results"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", name="pk_docx_analysis_results"),
        UniqueConstraint("document_id", "run_id", "result_sha256", name="uq_dax_digest"),
        ForeignKeyConstraint(
            ["document_id", "run_id", "attempt_id"],
            [
                "docx_analysis_attempts.document_id",
                "docx_analysis_attempts.run_id",
                "docx_analysis_attempts.id",
            ],
            name="fk_dax_attempt",
        ),
        ForeignKeyConstraint(
            ["document_id", "run_id", "run_status"],
            [
                "docx_analysis_runs.document_id",
                "docx_analysis_runs.id",
                "docx_analysis_runs.status",
            ],
            name="fk_dax_success",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        CheckConstraint("run_status = 'succeeded'", name="ck_dax_success"),
        CheckConstraint("reply_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dax_reply_hash"),
        CheckConstraint("result_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dax_result_hash"),
        CheckConstraint("octet_length(reply_data) BETWEEN 1 AND 4194304", name="ck_dax_reply_size"),
        CheckConstraint(
            "octet_length(result_data) BETWEEN 1 AND 8388608", name="ck_dax_result_size"
        ),
        CheckConstraint(
            "findings_count BETWEEN 0 AND 10000 AND questions_count BETWEEN 0 AND 10000",
            name="ck_dax_counts",
        ),
        CheckConstraint(
            "NOT no_findings OR (findings_count = 0 AND questions_count = 0)",
            name="ck_dax_no_findings",
        ),
        CheckConstraint("isfinite(created_at)", name="ck_dax_created"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_status: Mapped[str] = mapped_column(Text(), nullable=False)
    reply_data: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    reply_sha256: Mapped[str] = mapped_column(Text(), nullable=False)
    result_data: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    result_sha256: Mapped[str] = mapped_column(Text(), nullable=False)
    findings_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    questions_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    no_findings: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocxAnalysisSupervisor(Base):
    __tablename__ = "docx_analysis_supervisor"
    __table_args__ = (
        PrimaryKeyConstraint("slot_key", name="pk_docx_analysis_supervisor"),
        CheckConstraint("slot_key = 1", name="ck_dasv_singleton"),
        CheckConstraint("revision > 0", name="ck_dasv_revision"),
        CheckConstraint(
            "(phase = 'unprovisioned' AND installation_id IS NULL AND owner_epoch IS NULL "
            "AND launch_id IS NULL AND document_id IS NULL AND run_id IS NULL "
            "AND attempt_id IS NULL AND worker_instance_id IS NULL AND claim_fence IS NULL) OR "
            "(phase = 'clean' AND installation_id IS NOT NULL "
            "AND launch_id IS NULL AND document_id IS NULL AND run_id IS NULL "
            "AND attempt_id IS NULL AND worker_instance_id IS NULL AND claim_fence IS NULL) OR "
            "(phase IN ('armed', 'drained') AND installation_id IS NOT NULL "
            "AND owner_epoch IS NOT NULL AND launch_id IS NOT NULL AND document_id IS NOT NULL "
            "AND run_id IS NOT NULL AND attempt_id IS NOT NULL AND worker_instance_id IS NOT NULL "
            "AND claim_fence IS NOT NULL AND claim_fence = 1)",
            name="ck_dasv_shape",
        ),
    )

    slot_key: Mapped[int] = mapped_column(SmallInteger, autoincrement=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    phase: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unprovisioned'"))
    installation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    owner_epoch: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    launch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    worker_instance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    claim_fence: Mapped[int | None] = mapped_column(SmallInteger)


class DocxReviewPreferences(Base):
    """Presentation state only; absent row is the service's virtual revision zero."""

    __tablename__ = "docx_review_preferences"
    __table_args__ = (
        PrimaryKeyConstraint("document_id", name="pk_docx_review_preferences"),
        ForeignKeyConstraint(["document_id"], ["docx_documents.id"], name="fk_drp_document"),
        CheckConstraint("revision > 0", name="ck_drp_revision"),
        CheckConstraint(
            "disabled_types IN ('[]'::jsonb, '[\"contradiction\"]'::jsonb, "
            "'[\"duplicate\"]'::jsonb, '[\"formulation\"]'::jsonb, "
            '\'["contradiction","duplicate"]\'::jsonb, '
            '\'["contradiction","formulation"]\'::jsonb, '
            '\'["duplicate","formulation"]\'::jsonb, '
            '\'["contradiction","duplicate","formulation"]\'::jsonb)',
            name="ck_drp_filters",
        ),
        CheckConstraint(
            "isfinite(created_at) AND isfinite(updated_at) AND updated_at >= created_at",
            name="ck_drp_times",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True
    )
    revision: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    disabled_types: Mapped[list[str]] = mapped_column(
        JSONB(), nullable=False, server_default=text("'[]'::jsonb")
    )
    show_questions: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default=text("true")
    )
    show_hidden: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )


class DocxReviewDismissal(Base):
    """Active exact-source hide with an immutable result origin; service verifies its key."""

    __tablename__ = "docx_review_dismissals"
    __table_args__ = (
        PrimaryKeyConstraint("document_id", "dismissal_key", name="pk_docx_review_dismissals"),
        ForeignKeyConstraint(
            ["document_id"], ["docx_review_preferences.document_id"], name="fk_drd_preferences"
        ),
        ForeignKeyConstraint(
            ["document_id", "source_run_id", "source_result_sha256"],
            [
                "docx_analysis_results.document_id",
                "docx_analysis_results.run_id",
                "docx_analysis_results.result_sha256",
            ],
            name="fk_drd_result",
        ),
        CheckConstraint("dismissal_key ~ '^dh-[0-9a-f]{64}$'", name="ck_drd_key"),
        CheckConstraint("source_result_sha256 ~ '^[0-9a-f]{64}$'", name="ck_drd_result_hash"),
        CheckConstraint("source_finding_id ~ '^df-[0-9a-f]{64}$'", name="ck_drd_finding_id"),
        CheckConstraint("hidden_at_revision > 0", name="ck_drd_revision"),
        CheckConstraint("isfinite(created_at)", name="ck_drd_created"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True
    )
    dismissal_key: Mapped[str] = mapped_column(Text(), nullable=False, primary_key=True)
    source_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_result_sha256: Mapped[str] = mapped_column(Text(), nullable=False)
    source_finding_id: Mapped[str] = mapped_column(Text(), nullable=False)
    hidden_at_revision: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )


class DocxReviewReceipt(Base):
    """Small idempotent mutation acknowledgement; not a copy of the entire review."""

    __tablename__ = "docx_review_receipts"
    __table_args__ = (
        PrimaryKeyConstraint("document_id", "command_id", name="pk_docx_review_receipts"),
        ForeignKeyConstraint(
            ["document_id"], ["docx_review_preferences.document_id"], name="fk_drr_preferences"
        ),
        UniqueConstraint("document_id", "revision", name="uq_drr_revision"),
        CheckConstraint(
            "expected_revision >= 0 AND revision > 0 AND revision - 1 = expected_revision",
            name="ck_drr_counters",
        ),
        CheckConstraint("kind IN ('preferences','hide','unhide')", name="ck_drr_kind"),
        CheckConstraint("command_sha256 ~ '^[0-9a-f]{64}$'", name="ck_drr_command_hash"),
        CheckConstraint("response_sha256 ~ '^[0-9a-f]{64}$'", name="ck_drr_response_hash"),
        CheckConstraint(
            "octet_length(command_data) BETWEEN 1 AND 16384", name="ck_drr_command_size"
        ),
        CheckConstraint(
            "octet_length(response_data) BETWEEN 1 AND 2048", name="ck_drr_response_size"
        ),
        CheckConstraint("isfinite(created_at)", name="ck_drr_created"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True
    )
    command_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, primary_key=True
    )
    expected_revision: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    kind: Mapped[str] = mapped_column(Text(), nullable=False)
    command_data: Mapped[bytes] = mapped_column(BYTEA(), nullable=False)
    command_sha256: Mapped[str] = mapped_column(Text(), nullable=False)
    response_data: Mapped[bytes] = mapped_column(BYTEA(), nullable=False)
    response_sha256: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
