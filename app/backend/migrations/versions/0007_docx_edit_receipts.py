"""Atomically retain edit receipts for retries after lost acknowledgements."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_docx_edit_receipts"
down_revision = "0006_docx_documents"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "docx_edit_receipts",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_sha256", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("storage_revision", sa.BigInteger(), nullable=False),
        sa.Column("current_sha256", sa.Text(), nullable=False),
        sa.Column("current_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("document_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.PrimaryKeyConstraint("document_id", "operation_id", name="pk_docx_edit_receipts"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["docx_documents.id"], name="fk_docx_edit_receipts_document"
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_edit_receipts_request_sha256"
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200", name="ck_docx_edit_receipts_title_length"
        ),
        sa.CheckConstraint("storage_revision > 1", name="ck_docx_edit_receipts_storage_revision"),
        sa.CheckConstraint(
            "current_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_edit_receipts_current_sha256"
        ),
        sa.CheckConstraint(
            "current_size_bytes > 0", name="ck_docx_edit_receipts_current_size_bytes"
        ),
    )


def downgrade():
    op.drop_table("docx_edit_receipts")
