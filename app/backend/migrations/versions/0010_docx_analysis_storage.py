"""Add isolated DOCX analysis storage and refuse destructive downgrade."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_docx_analysis_storage"
down_revision = "0009_docx_editor_checkpoints"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "docx_analysis_sources",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("source_data", postgresql.BYTEA(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.PrimaryKeyConstraint("document_id", "source_sha256", name="pk_docx_analysis_sources"),
        sa.ForeignKeyConstraint(["document_id"], ["docx_documents.id"], name="fk_das_document"),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_das_hash"),
        sa.CheckConstraint("octet_length(source_data) BETWEEN 1 AND 33554432", name="ck_das_size"),
        sa.CheckConstraint("isfinite(created_at)", name="ck_das_created"),
    )
    op.create_table(
        "docx_analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("storage_revision", sa.BigInteger(), nullable=False),
        sa.Column("accepted_order", sa.BigInteger(), nullable=False),
        sa.Column("accepted_project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accepted_owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_kind", sa.Text(), nullable=False),
        sa.Column("retry_of_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("command_data", postgresql.BYTEA(), nullable=False),
        sa.Column("command_sha256", sa.Text(), nullable=False),
        sa.Column("format_version", sa.SmallInteger(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("snapshot_data", postgresql.BYTEA(), nullable=False),
        sa.Column("snapshot_sha256", sa.Text(), nullable=False),
        sa.Column("execution_kind", sa.Text(), nullable=False),
        sa.Column("execution_spec", postgresql.BYTEA(), nullable=False),
        sa.Column("execution_spec_sha256", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("fence", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_sha256", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_docx_analysis_runs"),
        sa.UniqueConstraint("document_id", "id", name="uq_dar_document_id"),
        sa.UniqueConstraint("document_id", "client_request_id", name="uq_dar_request"),
        sa.UniqueConstraint("document_id", "accepted_order", name="uq_dar_order"),
        sa.UniqueConstraint("document_id", "id", "status", name="uq_dar_publication"),
        sa.UniqueConstraint("document_id", "id", "attempt_id", name="uq_dar_attempt_binding"),
        sa.ForeignKeyConstraint(
            ["document_id", "source_sha256"],
            ["docx_analysis_sources.document_id", "docx_analysis_sources.source_sha256"],
            name="fk_dar_source",
        ),
        sa.ForeignKeyConstraint(["accepted_project_id"], ["projects.id"], name="fk_dar_project"),
        sa.ForeignKeyConstraint(["accepted_owner_id"], ["users.id"], name="fk_dar_owner"),
        sa.ForeignKeyConstraint(
            ["document_id", "retry_of_run_id"],
            ["docx_analysis_runs.document_id", "docx_analysis_runs.id"],
            name="fk_dar_retry",
        ),
        sa.CheckConstraint("storage_revision > 0 AND accepted_order > 0", name="ck_dar_counters"),
        sa.CheckConstraint("format_version = 1", name="ck_dar_version"),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dar_source_hash"),
        sa.CheckConstraint("command_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dar_command_hash"),
        sa.CheckConstraint("snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dar_snapshot_hash"),
        sa.CheckConstraint(
            "execution_spec_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dar_execution_hash"
        ),
        sa.CheckConstraint("result_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dar_result_hash"),
        sa.CheckConstraint(
            "octet_length(command_data) BETWEEN 1 AND 16384", name="ck_dar_command_size"
        ),
        sa.CheckConstraint(
            "octet_length(snapshot_data) BETWEEN 1 AND 33554432", name="ck_dar_snapshot_size"
        ),
        sa.CheckConstraint(
            "octet_length(execution_spec) BETWEEN 1 AND 4096", name="ck_dar_execution_size"
        ),
        sa.CheckConstraint("profile ~ '^[a-z0-9][a-z0-9/_.-]{0,127}$'", name="ck_dar_profile"),
        sa.CheckConstraint(
            "policy_version ~ '^[a-z0-9][a-z0-9/_.-]{0,127}$'", name="ck_dar_policy"
        ),
        sa.CheckConstraint(
            "execution_kind IN ('fixture','local_model')", name="ck_dar_execution_kind"
        ),
        sa.CheckConstraint(
            (
                " (start_kind = 'saved' AND retry_of_run_id IS NULL) OR (start_kind = 'retry' "
                "AND retry_of_run_id IS NOT NULL AND retry_of_run_id <> id) "
            ),
            name="ck_dar_start",
        ),
        sa.CheckConstraint(
            (
                " status IN "
                "('queued','running','cancel_requested','succeeded','failed','cancelled','timed_o"
                "ut') "
            ),
            name="ck_dar_status",
        ),
        sa.CheckConstraint(
            (
                " (status = 'queued' AND stage = 'queued') OR (status = 'running' AND stage IN "
                "('preparing_document','loading_model','analyzing','validating_result','finishing"
                "')) OR (status IN "
                "('cancel_requested','succeeded','failed','cancelled','timed_out') AND stage = "
                "status) "
            ),
            name="ck_dar_stage",
        ),
        sa.CheckConstraint(
            (
                " isfinite(created_at) AND isfinite(deadline_at) AND isfinite(updated_at) AND "
                "deadline_at = created_at + INTERVAL '300 seconds' AND updated_at >= created_at "
                "AND (started_at IS NULL OR (isfinite(started_at) AND started_at >= created_at "
                "AND started_at < deadline_at)) AND (heartbeat_at IS NULL OR "
                "(isfinite(heartbeat_at) AND heartbeat_at >= started_at AND heartbeat_at < "
                "deadline_at)) AND (lease_expires_at IS NULL OR (isfinite(lease_expires_at) AND "
                "lease_expires_at > heartbeat_at AND lease_expires_at <= heartbeat_at + INTERVAL "
                "'15 seconds' AND lease_expires_at <= deadline_at)) AND (cancel_requested_at IS "
                "NULL OR (isfinite(cancel_requested_at) AND cancel_requested_at >= created_at)) "
                "AND (finished_at IS NULL OR (isfinite(finished_at) AND finished_at >= "
                "created_at)) "
            ),
            name="ck_dar_times",
        ),
        sa.CheckConstraint(
            (
                " (attempt_id IS NULL AND started_at IS NULL AND heartbeat_at IS NULL AND "
                "lease_expires_at IS NULL) OR (attempt_id IS NOT NULL AND started_at IS NOT NULL "
                "AND heartbeat_at IS NOT NULL) "
            ),
            name="ck_dar_attempt_shape",
        ),
        sa.CheckConstraint(
            (
                " (status = 'queued' AND fence = 0 AND attempt_id IS NULL AND finished_at IS "
                "NULL AND cancel_requested_at IS NULL AND result_sha256 IS NULL AND error_code "
                "IS NULL) OR (status = 'running' AND fence = 1 AND attempt_id IS NOT NULL AND "
                "lease_expires_at IS NOT NULL AND finished_at IS NULL AND cancel_requested_at IS "
                "NULL AND result_sha256 IS NULL AND error_code IS NULL) OR (status = "
                "'cancel_requested' AND fence = 2 AND attempt_id IS NOT NULL AND "
                "lease_expires_at IS NOT NULL AND finished_at IS NULL AND cancel_requested_at IS "
                "NOT NULL AND result_sha256 IS NULL AND error_code IS NULL) OR (status = "
                "'succeeded' AND fence = 2 AND attempt_id IS NOT NULL AND lease_expires_at IS "
                "NULL AND finished_at IS NOT NULL AND finished_at < deadline_at AND "
                "cancel_requested_at IS NULL AND result_sha256 IS NOT NULL AND error_code IS "
                "NULL) OR (status IN ('failed','cancelled','timed_out') AND ((attempt_id IS NULL "
                "AND fence = 1) OR (attempt_id IS NOT NULL AND fence = 2)) AND lease_expires_at "
                "IS NULL AND finished_at IS NOT NULL AND result_sha256 IS NULL AND error_code IS "
                "NOT NULL) "
            ),
            name="ck_dar_lifecycle",
        ),
        sa.CheckConstraint(
            (
                " error_code IS NULL OR error_code IN "
                "('interrupted','ownership_changed','unsupported_analysis_content','empty_documen"
                "t', 'analysis_limit_exceeded','model_unavailable','model_input_limit_exceeded', "
                "'invalid_result','adapter_error','source_corrupt','cancelled','deadline_exceeded"
                "') "
            ),
            name="ck_dar_failure",
        ),
        sa.CheckConstraint(
            (
                " (status NOT IN ('failed','cancelled','timed_out')) OR (status = 'failed' AND "
                "error_code NOT IN ('cancelled','deadline_exceeded')) OR (status = 'cancelled' "
                "AND error_code = 'cancelled' AND cancel_requested_at IS NOT NULL) OR (status = "
                "'timed_out' AND error_code = 'deadline_exceeded' AND finished_at >= "
                "deadline_at) "
            ),
            name="ck_dar_terminal_reason",
        ),
    )
    op.create_table(
        "docx_analysis_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_fence", sa.BigInteger(), nullable=False),
        sa.Column("worker_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_data", postgresql.BYTEA(), nullable=False),
        sa.Column("request_sha256", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_docx_analysis_attempts"),
        sa.UniqueConstraint("run_id", name="uq_daa_run"),
        sa.UniqueConstraint("document_id", "run_id", "id", name="uq_daa_scope"),
        sa.CheckConstraint("claim_fence = 1", name="ck_daa_fence"),
        sa.CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="ck_daa_request_hash"),
        sa.CheckConstraint(
            "octet_length(request_data) BETWEEN 1 AND 8388608", name="ck_daa_request_size"
        ),
        sa.CheckConstraint("isfinite(created_at)", name="ck_daa_created"),
    )
    op.create_table(
        "docx_analysis_results",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_status", sa.Text(), nullable=False),
        sa.Column("reply_data", postgresql.BYTEA(), nullable=False),
        sa.Column("reply_sha256", sa.Text(), nullable=False),
        sa.Column("result_data", postgresql.BYTEA(), nullable=False),
        sa.Column("result_sha256", sa.Text(), nullable=False),
        sa.Column("findings_count", sa.Integer(), nullable=False),
        sa.Column("questions_count", sa.Integer(), nullable=False),
        sa.Column("no_findings", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name="pk_docx_analysis_results"),
        sa.UniqueConstraint("document_id", "run_id", "result_sha256", name="uq_dax_digest"),
        sa.ForeignKeyConstraint(
            ["document_id", "run_id", "attempt_id"],
            [
                "docx_analysis_attempts.document_id",
                "docx_analysis_attempts.run_id",
                "docx_analysis_attempts.id",
            ],
            name="fk_dax_attempt",
        ),
        sa.CheckConstraint("run_status = 'succeeded'", name="ck_dax_success"),
        sa.CheckConstraint("reply_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dax_reply_hash"),
        sa.CheckConstraint("result_sha256 ~ '^[0-9a-f]{64}$'", name="ck_dax_result_hash"),
        sa.CheckConstraint(
            "octet_length(reply_data) BETWEEN 1 AND 4194304", name="ck_dax_reply_size"
        ),
        sa.CheckConstraint(
            "octet_length(result_data) BETWEEN 1 AND 8388608", name="ck_dax_result_size"
        ),
        sa.CheckConstraint(
            "findings_count BETWEEN 0 AND 10000 AND questions_count BETWEEN 0 AND 10000",
            name="ck_dax_counts",
        ),
        sa.CheckConstraint(
            "NOT no_findings OR (findings_count = 0 AND questions_count = 0)",
            name="ck_dax_no_findings",
        ),
        sa.CheckConstraint("isfinite(created_at)", name="ck_dax_created"),
    )
    op.create_foreign_key(
        "fk_dar_attempt",
        "docx_analysis_runs",
        "docx_analysis_attempts",
        ["document_id", "id", "attempt_id"],
        ["document_id", "run_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_dar_result",
        "docx_analysis_runs",
        "docx_analysis_results",
        ["document_id", "id", "result_sha256"],
        ["document_id", "run_id", "result_sha256"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_daa_run",
        "docx_analysis_attempts",
        "docx_analysis_runs",
        ["document_id", "run_id", "id"],
        ["document_id", "id", "attempt_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_dax_success",
        "docx_analysis_results",
        "docx_analysis_runs",
        ["document_id", "run_id", "run_status"],
        ["document_id", "id", "status"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "uq_dar_active_document",
        "docx_analysis_runs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running','cancel_requested')"),
    )
    op.create_index(
        "ix_dar_queue",
        "docx_analysis_runs",
        ["created_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "ix_dar_deadline",
        "docx_analysis_runs",
        ["deadline_at", "id"],
        unique=False,
        postgresql_where=sa.text("status IN ('queued','running','cancel_requested')"),
    )
    op.create_index(
        "ix_dar_lease",
        "docx_analysis_runs",
        ["lease_expires_at", "id"],
        unique=False,
        postgresql_where=sa.text("status IN ('running','cancel_requested')"),
    )
    op.create_index(
        "ix_dar_latest_success",
        "docx_analysis_runs",
        ["document_id", sa.text("accepted_order DESC")],
        unique=False,
        postgresql_where=sa.text("status = 'succeeded'"),
    )


def downgrade():
    # Lock before inspecting: never drop an invisible uncommitted record.
    op.execute(
        (
            "LOCK TABLE docx_analysis_runs, docx_analysis_attempts, docx_analysis_results, "
            "docx_analysis_sources IN ACCESS EXCLUSIVE MODE"
        )
    )
    dirty = op.get_bind().scalar(
        sa.text(
            (
                "SELECT EXISTS (SELECT 1 FROM docx_analysis_sources) OR EXISTS (SELECT 1 FROM "
                "docx_analysis_runs) OR EXISTS (SELECT 1 FROM docx_analysis_attempts) OR EXISTS "
                "(SELECT 1 FROM docx_analysis_results)"
            )
        )
    )
    if dirty:
        raise RuntimeError("Cannot downgrade while DOCX analysis records exist")
    op.drop_constraint("fk_dar_attempt", "docx_analysis_runs", type_="foreignkey")
    op.drop_constraint("fk_dar_result", "docx_analysis_runs", type_="foreignkey")
    op.drop_constraint("fk_daa_run", "docx_analysis_attempts", type_="foreignkey")
    op.drop_constraint("fk_dax_success", "docx_analysis_results", type_="foreignkey")
    op.drop_table("docx_analysis_results")
    op.drop_table("docx_analysis_attempts")
    op.drop_table("docx_analysis_runs")
    op.drop_table("docx_analysis_sources")
