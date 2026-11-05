"""Keep one recoverable working copy without changing saved DOCX bytes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_docx_edit_drafts"
down_revision = "0007_docx_edit_receipts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "docx_edit_drafts",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.PrimaryKeyConstraint("document_id", name="pk_docx_edit_drafts"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["docx_documents.id"], name="fk_docx_edit_drafts_document"
        ),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_docx_edit_drafts_payload"),
    )


def downgrade():
    op.drop_table("docx_edit_drafts")
