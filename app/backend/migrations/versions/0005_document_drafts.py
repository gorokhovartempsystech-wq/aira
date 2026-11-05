"""One current local draft per document, separate from immutable versions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_document_drafts"
down_revision = "0004_review_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "document_drafts",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_document_drafts_document"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "base_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            name="fk_document_drafts_base_version",
        ),
        sa.CheckConstraint("revision > 0", name="ck_document_drafts_revision"),
    )


def downgrade():
    op.drop_table("document_drafts")
