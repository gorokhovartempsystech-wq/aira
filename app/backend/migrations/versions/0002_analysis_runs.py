"""Persist immutable analysis inputs and owner-scoped enqueue operations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_analysis_runs"
down_revision = "0001_initial_documents"
branch_labels = None
depends_on = None


def identity_columns():
    return (
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def upgrade():
    op.create_table(
        "context_revisions",
        *identity_columns(),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_context_revisions_document"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_context_revisions_owner"),
        sa.UniqueConstraint("document_id", "owner_id", "id", name="uq_context_revisions_scope_id"),
        sa.CheckConstraint(
            "jsonb_typeof(items) = 'array'", name="ck_context_revisions_items_array"
        ),
    )
    for column in ("document_id", "owner_id"):
        op.create_index(f"ix_context_revisions_{column}", "context_revisions", [column])
    op.create_table(
        "analysis_runs",
        *identity_columns(),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("execution_mode", sa.Text(), nullable=False, server_default=sa.text("'fixture'")),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "has_import_omissions", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_analysis_runs_owner"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_analysis_runs_document"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "base_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_analysis_runs_base_version",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "owner_id", "context_revision_id"],
            ["context_revisions.document_id", "context_revisions.owner_id", "context_revisions.id"],
            name="fk_analysis_runs_context",
        ),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_analysis_runs_owner_key"),
        sa.CheckConstraint("mode IN ('lint', 'merge')", name="ck_analysis_runs_mode"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_analysis_runs_status"
        ),
        sa.CheckConstraint("execution_mode = 'fixture'", name="ck_analysis_runs_execution_mode"),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 128", name="ck_analysis_runs_key_length"
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_analysis_runs_fingerprint"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(request_payload) = 'object'", name="ck_analysis_runs_request_object"
        ),
    )
    for column in ("document_id", "owner_id", "context_revision_id"):
        op.create_index(f"ix_analysis_runs_{column}", "analysis_runs", [column])
    op.create_index("ix_analysis_runs_status_created_at", "analysis_runs", ["status", "created_at"])


def downgrade():
    op.drop_table("analysis_runs")
    op.drop_table("context_revisions")
