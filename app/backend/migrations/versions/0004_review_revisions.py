"""Append-only review snapshots linked to their run, owner and parent."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_review_revisions"
down_revision = "0003_worker_execution"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_analysis_runs_id_owner", "analysis_runs", ["id", "owner_id"])
    op.create_table(
        "review_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("result_fingerprint", sa.Text(), nullable=False),
        sa.Column("decisions", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_review_revisions_owner"),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["analysis_runs.id", "analysis_runs.owner_id"],
            name="fk_review_revisions_run_owner",
        ),
        sa.UniqueConstraint("run_id", "revision_number", name="uq_review_revisions_number"),
        sa.UniqueConstraint("run_id", "owner_id", "id", name="uq_review_revisions_scope_id"),
        sa.UniqueConstraint(
            "run_id", "owner_id", "parent_revision_id", name="uq_review_revisions_child"
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id", "parent_revision_id"],
            ["review_revisions.run_id", "review_revisions.owner_id", "review_revisions.id"],
            name="fk_review_revisions_parent",
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_review_revisions_number"),
        sa.CheckConstraint(
            "result_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_review_revisions_fingerprint"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(decisions) = 'array'", name="ck_review_revisions_decisions_array"
        ),
        sa.CheckConstraint("parent_revision_id <> id", name="ck_review_revisions_not_self_parent"),
        sa.CheckConstraint(
            "(revision_number = 1) = (parent_revision_id IS NULL)",
            name="ck_review_revisions_root_number",
        ),
    )
    op.create_index("ix_review_revisions_owner_id", "review_revisions", ["owner_id"])
    op.create_index(
        "uq_review_revisions_root",
        "review_revisions",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("parent_revision_id IS NULL"),
    )


def downgrade():
    op.drop_table("review_revisions")
    op.drop_constraint("uq_analysis_runs_id_owner", "analysis_runs", type_="unique")
