"""Persist native file associations and pending exact save payloads."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0014_docx_file_states"
down_revision = "0013_docx_review_preferences"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "docx_file_states",
        sa.Column("document_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("state", pg.JSONB(), nullable=False),
        sa.Column("payload", pg.BYTEA(), nullable=True),
        sa.PrimaryKeyConstraint("document_id"),
        sa.ForeignKeyConstraint(["document_id"], ["docx_documents.id"]),
        sa.CheckConstraint("version > 0", name="ck_dfs_version"),
        sa.CheckConstraint("jsonb_typeof(state) = 'object'", name="ck_dfs_state"),
        sa.CheckConstraint("octet_length(state::text) <= 32768", name="ck_dfs_state_size"),
        sa.CheckConstraint(
            "payload IS NULL OR octet_length(payload) BETWEEN 1 AND 33554432",
            name="ck_dfs_payload",
        ),
    )


def downgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("LOCK TABLE docx_file_states IN ACCESS EXCLUSIVE MODE")
    if conn.exec_driver_sql("SELECT EXISTS (SELECT 1 FROM docx_file_states)").scalar_one():
        raise RuntimeError("Cannot remove stored file associations")
    op.drop_table("docx_file_states")
