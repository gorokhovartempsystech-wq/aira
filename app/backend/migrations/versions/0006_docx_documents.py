"""Store exact original DOCX packages and their current scoped drafts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_docx_documents"
down_revision = "0005_document_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "docx_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("original_data", postgresql.BYTEA(), nullable=False),
        sa.Column("original_sha256", sa.Text(), nullable=False),
        sa.Column("current_data", postgresql.BYTEA(), nullable=False),
        sa.Column("current_sha256", sa.Text(), nullable=False),
        sa.Column("storage_revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_docx_documents"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_docx_documents_project"),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200", name="ck_docx_documents_title_length"
        ),
        sa.CheckConstraint(
            "octet_length(original_data) > 0", name="ck_docx_documents_original_data"
        ),
        sa.CheckConstraint("octet_length(current_data) > 0", name="ck_docx_documents_current_data"),
        sa.CheckConstraint(
            "original_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_documents_original_sha256"
        ),
        sa.CheckConstraint(
            "current_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_documents_current_sha256"
        ),
        sa.CheckConstraint("storage_revision > 0", name="ck_docx_documents_storage_revision"),
    )
    op.create_index(
        "ix_docx_documents_project_created_id",
        "docx_documents",
        ["project_id", "created_at", "id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_docx_documents_project_created_id", table_name="docx_documents")
    op.drop_table("docx_documents")
