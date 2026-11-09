"""Persist opt-in local model review results, bound to exact DOCX revision."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_local_model_reviews"
down_revision = "0009_docx_editor_checkpoints"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "local_model_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("docx_documents.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
    )


def downgrade():
    op.execute("LOCK TABLE local_model_reviews IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM local_model_reviews)")):
        raise RuntimeError("Cannot remove stored review results")
    op.drop_table("local_model_reviews")
