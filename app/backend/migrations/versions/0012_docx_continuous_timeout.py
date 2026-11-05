"""Preserve the time domain of terminal deadlines without fabricating wall time."""

import sqlalchemy as sa
from alembic import op

revision = "0012_docx_continuous_timeout"
down_revision = "0011_docx_analysis_supervisor"
branch_labels = None
depends_on = None

TABLE = "docx_analysis_runs"
REASON = (
    "(status NOT IN ('failed','cancelled','timed_out')) OR "
    "(status = 'failed' AND error_code NOT IN ('cancelled','deadline_exceeded')) OR "
    "(status = 'cancelled' AND error_code = 'cancelled' AND cancel_requested_at IS NOT NULL) OR "
    "(status = 'timed_out' AND error_code = 'deadline_exceeded' AND {deadline})"
)


def upgrade():
    op.add_column(
        TABLE,
        sa.Column("timeout_basis", sa.Text(), nullable=False, server_default=sa.text("'wall'")),
    )
    op.create_check_constraint(
        "ck_dar_timeout_basis",
        TABLE,
        "timeout_basis = 'wall' OR (timeout_basis = 'continuous' AND status = 'timed_out')",
    )
    op.drop_constraint("ck_dar_terminal_reason", TABLE, type_="check")
    op.create_check_constraint(
        "ck_dar_terminal_reason",
        TABLE,
        REASON.format(deadline="(finished_at >= deadline_at OR timeout_basis = 'continuous')"),
    )


def downgrade():
    conn = op.get_bind()
    conn.exec_driver_sql("LOCK TABLE docx_analysis_runs IN ACCESS EXCLUSIVE MODE")
    if conn.exec_driver_sql(
        "SELECT EXISTS (SELECT 1 FROM docx_analysis_runs WHERE timeout_basis <> 'wall')"
    ).scalar_one():
        raise RuntimeError("Cannot downgrade continuous timeout history")
    op.drop_constraint("ck_dar_terminal_reason", TABLE, type_="check")
    op.create_check_constraint(
        "ck_dar_terminal_reason",
        TABLE,
        REASON.format(deadline="finished_at >= deadline_at"),
    )
    op.drop_constraint("ck_dar_timeout_basis", TABLE, type_="check")
    op.drop_column(TABLE, "timeout_basis")
