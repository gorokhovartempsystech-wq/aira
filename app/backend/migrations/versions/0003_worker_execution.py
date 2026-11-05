"""Persist fenced worker attempts and validated fixture results."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0003_worker_execution"
down_revision = "0002_analysis_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "analysis_runs",
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.add_column("analysis_runs", sa.Column("max_attempts", sa.Integer, nullable=True))
    op.add_column(
        "analysis_runs", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "analysis_runs", sa.Column("active_attempt_id", UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "analysis_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "analysis_runs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("analysis_runs", sa.Column("error_code", sa.Text, nullable=True))
    op.add_column(
        "analysis_runs", sa.Column("result_payload", JSONB(none_as_null=True), nullable=True)
    )
    op.add_column("analysis_runs", sa.Column("incomplete_review", sa.Boolean, nullable=True))
    op.create_check_constraint(
        "ck_analysis_runs_attempt_count", "analysis_runs", "attempt_count >= 0"
    )
    op.create_check_constraint(
        "ck_analysis_runs_max_attempts",
        "analysis_runs",
        "max_attempts IS NULL OR max_attempts BETWEEN 1 AND 10",
    )
    op.create_check_constraint(
        "ck_analysis_runs_attempt_budget",
        "analysis_runs",
        "attempt_count = 0 OR (max_attempts IS NOT NULL AND deadline_at IS NOT NULL AND "
        "attempt_count <= max_attempts)",
    )
    op.create_check_constraint(
        "ck_analysis_runs_policy", "analysis_runs", "(max_attempts IS NULL) = (deadline_at IS NULL)"
    )
    op.create_check_constraint(
        "ck_analysis_runs_active_attempt",
        "analysis_runs",
        "(status = 'running' AND active_attempt_id IS NOT NULL AND lease_expires_at IS "
        "NOT NULL) OR (status <> 'running' AND active_attempt_id IS NULL AND "
        "lease_expires_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_analysis_runs_completed",
        "analysis_runs",
        "(status IN ('succeeded', 'failed')) = (completed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_analysis_runs_error",
        "analysis_runs",
        "(status = 'failed' AND error_code IS NOT NULL AND error_code IN "
        "('deadline_exceeded', 'attempts_exhausted', 'access_revoked', "
        "'invalid_request', 'invalid_result')) OR (status <> 'failed' AND error_code IS "
        "NULL)",
    )
    op.create_check_constraint(
        "ck_analysis_runs_result",
        "analysis_runs",
        "(status = 'succeeded' AND result_payload IS NOT NULL AND incomplete_review IS "
        "NOT NULL) OR (status <> 'succeeded' AND result_payload IS NULL AND "
        "incomplete_review IS NULL)",
    )
    op.create_check_constraint(
        "ck_analysis_runs_result_object",
        "analysis_runs",
        "result_payload IS NULL OR jsonb_typeof(result_payload) = 'object'",
    )
    op.create_index(
        "ix_analysis_runs_status_available_at", "analysis_runs", ["status", "available_at"]
    )
    op.create_index(
        "ix_analysis_runs_status_lease_expires_at", "analysis_runs", ["status", "lease_expires_at"]
    )
    op.create_table(
        "analysis_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer, nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error_code", sa.Text, nullable=True),
        sa.Column("retry_delay_seconds", sa.Double, nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], name="fk_analysis_attempts_run"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_analysis_attempts_project"
        ),
        sa.UniqueConstraint("run_id", "attempt_number", name="uq_analysis_attempts_number"),
        sa.UniqueConstraint("run_id", "id", name="uq_analysis_attempts_run_id_id"),
        sa.CheckConstraint("attempt_number > 0", name="ck_analysis_attempts_number"),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'expired')",
            name="ck_analysis_attempts_status",
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="ck_analysis_attempts_finished"
        ),
        sa.CheckConstraint(
            "(status IN ('running', 'succeeded') AND error_code IS NULL) OR (status IN "
            "('failed', 'expired') AND error_code IS NOT NULL AND error_code IN "
            "('adapter_error', 'adapter_timeout', 'invalid_result', 'invalid_request', "
            "'access_revoked', 'lease_expired', 'deadline_exceeded'))",
            name="ck_analysis_attempts_error",
        ),
        sa.CheckConstraint(
            "retry_delay_seconds >= 0 AND retry_delay_seconds <= 300",
            name="ck_analysis_attempts_retry_delay",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'", name="ck_analysis_attempts_metadata_object"
        ),
    )
    op.create_index("ix_analysis_attempts_run_id", "analysis_attempts", ["run_id"])
    op.create_foreign_key(
        "fk_analysis_runs_active_attempt",
        "analysis_runs",
        "analysis_attempts",
        ["id", "active_attempt_id"],
        ["run_id", "id"],
    )


def downgrade():
    op.drop_constraint("fk_analysis_runs_active_attempt", "analysis_runs", type_="foreignkey")
    op.drop_table("analysis_attempts")
    op.drop_index("ix_analysis_runs_status_available_at", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_status_lease_expires_at", table_name="analysis_runs")
    op.drop_constraint("ck_analysis_runs_attempt_count", "analysis_runs", type_="check")
    op.drop_constraint("ck_analysis_runs_max_attempts", "analysis_runs", type_="check")
    op.drop_constraint("ck_analysis_runs_attempt_budget", "analysis_runs", type_="check")
    op.drop_constraint("ck_analysis_runs_policy", "analysis_runs", type_="check")
    op.drop_constraint("ck_analysis_runs_active_attempt", "analysis_runs", type_="check")
    op.drop_constraint("ck_analysis_runs_completed", "analysis_runs", type_="check")
    op.drop_constraint("ck_analysis_runs_error", "analysis_runs", type_="check")
    op.drop_constraint("ck_analysis_runs_result", "analysis_runs", type_="check")
    op.drop_constraint("ck_analysis_runs_result_object", "analysis_runs", type_="check")
    op.drop_column("analysis_runs", "incomplete_review")
    op.drop_column("analysis_runs", "result_payload")
    op.drop_column("analysis_runs", "error_code")
    op.drop_column("analysis_runs", "completed_at")
    op.drop_column("analysis_runs", "lease_expires_at")
    op.drop_column("analysis_runs", "active_attempt_id")
    op.drop_column("analysis_runs", "available_at")
    op.drop_column("analysis_runs", "deadline_at")
    op.drop_column("analysis_runs", "max_attempts")
    op.drop_column("analysis_runs", "attempt_count")
