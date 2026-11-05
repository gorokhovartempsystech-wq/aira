"""Add persistent presentation preferences, exact dismissals and small receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0013_docx_review_preferences"
down_revision = "0012_docx_continuous_timeout"
branch_labels = None
depends_on = None

P, D, R = "docx_review_preferences", "docx_review_dismissals", "docx_review_receipts"
FILTERS = (
    "disabled_types IN ('[]'::jsonb, '[\"contradiction\"]'::jsonb, "
    "'[\"duplicate\"]'::jsonb, '[\"formulation\"]'::jsonb, "
    '\'["contradiction","duplicate"]\'::jsonb, '
    '\'["contradiction","formulation"]\'::jsonb, '
    '\'["duplicate","formulation"]\'::jsonb, '
    '\'["contradiction","duplicate","formulation"]\'::jsonb)'
)


def stamp(name):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    )


def upgrade():
    op.create_table(
        P,
        sa.Column("document_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "disabled_types", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("show_questions", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("show_hidden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        stamp("created_at"),
        stamp("updated_at"),
        sa.PrimaryKeyConstraint("document_id", name="pk_docx_review_preferences"),
        sa.ForeignKeyConstraint(["document_id"], ["docx_documents.id"], name="fk_drp_document"),
        sa.CheckConstraint("revision > 0", name="ck_drp_revision"),
        sa.CheckConstraint(FILTERS, name="ck_drp_filters"),
        sa.CheckConstraint(
            "isfinite(created_at) AND isfinite(updated_at) AND updated_at >= created_at",
            name="ck_drp_times",
        ),
    )
    op.create_table(
        D,
        sa.Column("document_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("dismissal_key", sa.Text(), nullable=False),
        sa.Column("source_run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("source_result_sha256", sa.Text(), nullable=False),
        sa.Column("source_finding_id", sa.Text(), nullable=False),
        sa.Column("hidden_at_revision", sa.BigInteger(), nullable=False),
        stamp("created_at"),
        sa.PrimaryKeyConstraint("document_id", "dismissal_key", name="pk_docx_review_dismissals"),
        sa.ForeignKeyConstraint(["document_id"], [P + ".document_id"], name="fk_drd_preferences"),
        sa.ForeignKeyConstraint(
            ["document_id", "source_run_id", "source_result_sha256"],
            [
                "docx_analysis_results.document_id",
                "docx_analysis_results.run_id",
                "docx_analysis_results.result_sha256",
            ],
            name="fk_drd_result",
        ),
        sa.CheckConstraint("dismissal_key ~ '^dh-[0-9a-f]{64}$'", name="ck_drd_key"),
        sa.CheckConstraint("source_result_sha256 ~ '^[0-9a-f]{64}$'", name="ck_drd_result_hash"),
        sa.CheckConstraint("source_finding_id ~ '^df-[0-9a-f]{64}$'", name="ck_drd_finding_id"),
        sa.CheckConstraint("hidden_at_revision > 0", name="ck_drd_revision"),
        sa.CheckConstraint("isfinite(created_at)", name="ck_drd_created"),
    )
    op.create_table(
        R,
        sa.Column("document_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("command_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("expected_revision", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("command_data", pg.BYTEA(), nullable=False),
        sa.Column("command_sha256", sa.Text(), nullable=False),
        sa.Column("response_data", pg.BYTEA(), nullable=False),
        sa.Column("response_sha256", sa.Text(), nullable=False),
        stamp("created_at"),
        sa.PrimaryKeyConstraint("document_id", "command_id", name="pk_docx_review_receipts"),
        sa.ForeignKeyConstraint(["document_id"], [P + ".document_id"], name="fk_drr_preferences"),
        sa.UniqueConstraint("document_id", "revision", name="uq_drr_revision"),
        sa.CheckConstraint(
            "expected_revision >= 0 AND revision > 0 AND revision - 1 = expected_revision",
            name="ck_drr_counters",
        ),
        sa.CheckConstraint("kind IN ('preferences','hide','unhide')", name="ck_drr_kind"),
        sa.CheckConstraint("command_sha256 ~ '^[0-9a-f]{64}$'", name="ck_drr_command_hash"),
        sa.CheckConstraint("response_sha256 ~ '^[0-9a-f]{64}$'", name="ck_drr_response_hash"),
        sa.CheckConstraint(
            "octet_length(command_data) BETWEEN 1 AND 16384", name="ck_drr_command_size"
        ),
        sa.CheckConstraint(
            "octet_length(response_data) BETWEEN 1 AND 2048", name="ck_drr_response_size"
        ),
        sa.CheckConstraint("isfinite(created_at)", name="ck_drr_created"),
    )


def downgrade():
    conn = op.get_bind()
    conn.exec_driver_sql(f"LOCK TABLE {P}, {D}, {R} IN ACCESS EXCLUSIVE MODE")
    for table in (P, D, R):
        if conn.exec_driver_sql(f"SELECT EXISTS (SELECT 1 FROM {table})").scalar_one():
            raise RuntimeError("Cannot downgrade DOCX review preferences")
    for table in (R, D, P):
        op.drop_table(table)
