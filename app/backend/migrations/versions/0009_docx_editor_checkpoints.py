"""Store full DOCX checkpoints without dropping unsaved work on downgrade."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_docx_editor_checkpoints"
down_revision = "0008_docx_edit_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "docx_editor_checkpoints",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_revision", sa.BigInteger(), nullable=False),
        sa.Column("format_version", sa.SmallInteger(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("base_storage_revision", sa.BigInteger(), nullable=True),
        sa.Column("base_sha256", sa.Text(), nullable=True),
        sa.Column("working_data", postgresql.BYTEA(), nullable=True),
        sa.Column("working_sha256", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("last_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_request_sha256", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.PrimaryKeyConstraint("document_id", name="pk_docx_editor_checkpoints"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["docx_documents.id"], name="fk_docx_editor_checkpoints_document"
        ),
        sa.CheckConstraint("checkpoint_revision > 0", name="ck_docx_editor_cp_revision"),
        sa.CheckConstraint("format_version = 1", name="ck_docx_editor_cp_version"),
        sa.CheckConstraint(
            "phase IN ('empty','working','pending')", name="ck_docx_editor_cp_phase"
        ),
        sa.CheckConstraint("base_storage_revision > 0", name="ck_docx_editor_cp_base_revision"),
        sa.CheckConstraint("base_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_editor_cp_base_hash"),
        sa.CheckConstraint("working_sha256 ~ '^[0-9a-f]{64}$'", name="ck_docx_editor_cp_work_hash"),
        sa.CheckConstraint(
            "octet_length(working_data) BETWEEN 1 AND 33554432", name="ck_docx_editor_cp_work_size"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object' AND octet_length(metadata::text) <= 65536",
            name="ck_docx_editor_cp_metadata",
        ),
        sa.CheckConstraint(
            "(last_request_id IS NULL AND last_request_sha256 IS NULL) OR "
            "(last_request_id IS NOT NULL AND last_request_sha256 IS NOT NULL "
            "AND last_request_sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_docx_editor_cp_request",
        ),
        sa.CheckConstraint(
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


def downgrade():
    # Lock before inspecting rows: a concurrent checkpoint must not appear
    # between a successful emptiness check and DROP TABLE.
    op.execute("LOCK TABLE docx_editor_checkpoints IN ACCESS EXCLUSIVE MODE")
    dirty = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM docx_editor_checkpoints WHERE phase <> 'empty')")
    )
    if dirty:
        raise RuntimeError("Cannot downgrade while DOCX working checkpoints exist")
    op.drop_table("docx_editor_checkpoints")
