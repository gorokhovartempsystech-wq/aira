-- D03-17B2 design, 2026-11-01. Normative target DDL, NOT an installed migration.
-- Apply only to a disposable V9 database for design validation.
-- B2A will implement this with Alembic and matching ORM metadata.

CREATE TABLE docx_analysis_sources (
    document_id UUID NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_data BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_docx_analysis_sources PRIMARY KEY (document_id, source_sha256),
    CONSTRAINT fk_das_document FOREIGN KEY (document_id) REFERENCES docx_documents(id),
    CONSTRAINT ck_das_hash CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_das_size CHECK (octet_length(source_data) BETWEEN 1 AND 33554432),
    CONSTRAINT ck_das_created CHECK (isfinite(created_at))
);

CREATE TABLE docx_analysis_runs (
    id UUID NOT NULL,
    document_id UUID NOT NULL,
    source_sha256 TEXT NOT NULL,
    storage_revision BIGINT NOT NULL,
    accepted_order BIGINT NOT NULL,
    accepted_project_id UUID NOT NULL,
    accepted_owner_id UUID NOT NULL,
    client_request_id UUID NOT NULL,
    start_kind TEXT NOT NULL,
    retry_of_run_id UUID,
    command_data BYTEA NOT NULL,
    command_sha256 TEXT NOT NULL,
    format_version SMALLINT NOT NULL,
    profile TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    snapshot_data BYTEA NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    execution_kind TEXT NOT NULL,
    execution_spec BYTEA NOT NULL,
    execution_spec_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    fence BIGINT NOT NULL,
    attempt_id UUID,
    result_sha256 TEXT,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    deadline_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_docx_analysis_runs PRIMARY KEY (id),
    CONSTRAINT uq_dar_document_id UNIQUE (document_id, id),
    CONSTRAINT uq_dar_request UNIQUE (document_id, client_request_id),
    CONSTRAINT uq_dar_order UNIQUE (document_id, accepted_order),
    CONSTRAINT uq_dar_publication UNIQUE (document_id, id, status),
    CONSTRAINT uq_dar_attempt_binding UNIQUE (document_id, id, attempt_id),
    CONSTRAINT fk_dar_source FOREIGN KEY (document_id, source_sha256)
        REFERENCES docx_analysis_sources(document_id, source_sha256),
    CONSTRAINT fk_dar_project FOREIGN KEY (accepted_project_id) REFERENCES projects(id),
    CONSTRAINT fk_dar_owner FOREIGN KEY (accepted_owner_id) REFERENCES users(id),
    CONSTRAINT fk_dar_retry FOREIGN KEY (document_id, retry_of_run_id)
        REFERENCES docx_analysis_runs(document_id, id),
    CONSTRAINT ck_dar_counters CHECK (storage_revision > 0 AND accepted_order > 0),
    CONSTRAINT ck_dar_version CHECK (format_version = 1),
    CONSTRAINT ck_dar_source_hash CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_dar_command_hash CHECK (command_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_dar_snapshot_hash CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_dar_execution_hash CHECK (execution_spec_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_dar_result_hash CHECK (result_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_dar_command_size CHECK (octet_length(command_data) BETWEEN 1 AND 16384),
    CONSTRAINT ck_dar_snapshot_size CHECK (octet_length(snapshot_data) BETWEEN 1 AND 33554432),
    CONSTRAINT ck_dar_execution_size CHECK (octet_length(execution_spec) BETWEEN 1 AND 4096),
    CONSTRAINT ck_dar_profile CHECK (profile ~ '^[a-z0-9][a-z0-9/_.-]{0,127}$'),
    CONSTRAINT ck_dar_policy CHECK (policy_version ~ '^[a-z0-9][a-z0-9/_.-]{0,127}$'),
    CONSTRAINT ck_dar_execution_kind CHECK (execution_kind IN ('fixture','local_model')),
    CONSTRAINT ck_dar_start CHECK (
        (start_kind = 'saved' AND retry_of_run_id IS NULL) OR
        (start_kind = 'retry' AND retry_of_run_id IS NOT NULL AND retry_of_run_id <> id)
    ),
    CONSTRAINT ck_dar_status CHECK (
        status IN ('queued','running','cancel_requested','succeeded','failed','cancelled','timed_out')
    ),
    CONSTRAINT ck_dar_stage CHECK (
        (status = 'queued' AND stage = 'queued') OR
        (status = 'running' AND stage IN
            ('preparing_document','loading_model','analyzing','validating_result','finishing')) OR
        (status IN ('cancel_requested','succeeded','failed','cancelled','timed_out') AND stage = status)
    ),
    CONSTRAINT ck_dar_times CHECK (
        isfinite(created_at) AND isfinite(deadline_at) AND isfinite(updated_at) AND
        deadline_at = created_at + INTERVAL '300 seconds' AND updated_at >= created_at AND
        (started_at IS NULL OR (isfinite(started_at) AND started_at >= created_at AND started_at < deadline_at)) AND
        (heartbeat_at IS NULL OR (isfinite(heartbeat_at) AND heartbeat_at >= started_at AND heartbeat_at < deadline_at)) AND
        (lease_expires_at IS NULL OR (isfinite(lease_expires_at) AND
            lease_expires_at > heartbeat_at AND lease_expires_at <= heartbeat_at + INTERVAL '15 seconds' AND
            lease_expires_at <= deadline_at)) AND
        (cancel_requested_at IS NULL OR (isfinite(cancel_requested_at) AND cancel_requested_at >= created_at)) AND
        (finished_at IS NULL OR (isfinite(finished_at) AND finished_at >= created_at))
    ),
    CONSTRAINT ck_dar_attempt_shape CHECK (
        (attempt_id IS NULL AND started_at IS NULL AND heartbeat_at IS NULL AND lease_expires_at IS NULL) OR
        (attempt_id IS NOT NULL AND started_at IS NOT NULL AND heartbeat_at IS NOT NULL)
    ),
    CONSTRAINT ck_dar_lifecycle CHECK (
        (status = 'queued' AND fence = 0 AND attempt_id IS NULL AND finished_at IS NULL AND
            cancel_requested_at IS NULL AND result_sha256 IS NULL AND error_code IS NULL) OR
        (status = 'running' AND fence = 1 AND attempt_id IS NOT NULL AND lease_expires_at IS NOT NULL AND
            finished_at IS NULL AND cancel_requested_at IS NULL AND result_sha256 IS NULL AND error_code IS NULL) OR
        (status = 'cancel_requested' AND fence = 2 AND attempt_id IS NOT NULL AND lease_expires_at IS NOT NULL AND
            finished_at IS NULL AND cancel_requested_at IS NOT NULL AND result_sha256 IS NULL AND error_code IS NULL) OR
        (status = 'succeeded' AND fence = 2 AND attempt_id IS NOT NULL AND lease_expires_at IS NULL AND
            finished_at IS NOT NULL AND finished_at < deadline_at AND cancel_requested_at IS NULL AND
            result_sha256 IS NOT NULL AND error_code IS NULL) OR
        (status IN ('failed','cancelled','timed_out') AND
            ((attempt_id IS NULL AND fence = 1) OR (attempt_id IS NOT NULL AND fence = 2)) AND
            lease_expires_at IS NULL AND finished_at IS NOT NULL AND result_sha256 IS NULL AND error_code IS NOT NULL)
    ),
    CONSTRAINT ck_dar_failure CHECK (
        error_code IS NULL OR error_code IN
            ('interrupted','ownership_changed','unsupported_analysis_content','empty_document',
             'analysis_limit_exceeded','model_unavailable','model_input_limit_exceeded',
             'invalid_result','adapter_error','source_corrupt','cancelled','deadline_exceeded')
    ),
    CONSTRAINT ck_dar_terminal_reason CHECK (
        (status NOT IN ('failed','cancelled','timed_out')) OR
        (status = 'failed' AND error_code NOT IN ('cancelled','deadline_exceeded')) OR
        (status = 'cancelled' AND error_code = 'cancelled' AND cancel_requested_at IS NOT NULL) OR
        (status = 'timed_out' AND error_code = 'deadline_exceeded' AND finished_at >= deadline_at)
    )
);

CREATE UNIQUE INDEX uq_dar_active_document ON docx_analysis_runs(document_id)
    WHERE status IN ('queued','running','cancel_requested');
CREATE INDEX ix_dar_queue ON docx_analysis_runs(created_at, id) WHERE status = 'queued';
CREATE INDEX ix_dar_deadline ON docx_analysis_runs(deadline_at, id)
    WHERE status IN ('queued','running','cancel_requested');
CREATE INDEX ix_dar_lease ON docx_analysis_runs(lease_expires_at, id)
    WHERE status IN ('running','cancel_requested');
CREATE INDEX ix_dar_latest_success ON docx_analysis_runs(document_id, accepted_order DESC)
    WHERE status = 'succeeded';

CREATE TABLE docx_analysis_attempts (
    id UUID NOT NULL,
    document_id UUID NOT NULL,
    run_id UUID NOT NULL,
    claim_fence BIGINT NOT NULL,
    worker_instance_id UUID NOT NULL,
    request_data BYTEA NOT NULL,
    request_sha256 TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_docx_analysis_attempts PRIMARY KEY (id),
    CONSTRAINT uq_daa_run UNIQUE (run_id),
    CONSTRAINT uq_daa_scope UNIQUE (document_id, run_id, id),
    CONSTRAINT fk_daa_run FOREIGN KEY (document_id, run_id, id)
        REFERENCES docx_analysis_runs(document_id, id, attempt_id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_daa_fence CHECK (claim_fence = 1),
    CONSTRAINT ck_daa_request_hash CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_daa_request_size CHECK (octet_length(request_data) BETWEEN 1 AND 8388608),
    CONSTRAINT ck_daa_created CHECK (isfinite(created_at))
);

CREATE TABLE docx_analysis_results (
    run_id UUID NOT NULL,
    document_id UUID NOT NULL,
    attempt_id UUID NOT NULL,
    run_status TEXT NOT NULL,
    reply_data BYTEA NOT NULL,
    reply_sha256 TEXT NOT NULL,
    result_data BYTEA NOT NULL,
    result_sha256 TEXT NOT NULL,
    findings_count INTEGER NOT NULL,
    questions_count INTEGER NOT NULL,
    no_findings BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_docx_analysis_results PRIMARY KEY (run_id),
    CONSTRAINT uq_dax_digest UNIQUE (document_id, run_id, result_sha256),
    CONSTRAINT fk_dax_attempt FOREIGN KEY (document_id, run_id, attempt_id)
        REFERENCES docx_analysis_attempts(document_id, run_id, id),
    CONSTRAINT fk_dax_success FOREIGN KEY (document_id, run_id, run_status)
        REFERENCES docx_analysis_runs(document_id, id, status) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_dax_success CHECK (run_status = 'succeeded'),
    CONSTRAINT ck_dax_reply_hash CHECK (reply_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_dax_result_hash CHECK (result_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_dax_reply_size CHECK (octet_length(reply_data) BETWEEN 1 AND 4194304),
    CONSTRAINT ck_dax_result_size CHECK (octet_length(result_data) BETWEEN 1 AND 8388608),
    CONSTRAINT ck_dax_counts CHECK (findings_count BETWEEN 0 AND 10000 AND questions_count BETWEEN 0 AND 10000),
    CONSTRAINT ck_dax_no_findings CHECK (NOT no_findings OR (findings_count = 0 AND questions_count = 0)),
    CONSTRAINT ck_dax_created CHECK (isfinite(created_at))
);

ALTER TABLE docx_analysis_runs ADD CONSTRAINT fk_dar_attempt
    FOREIGN KEY (document_id, id, attempt_id)
    REFERENCES docx_analysis_attempts(document_id, run_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE docx_analysis_runs ADD CONSTRAINT fk_dar_result
    FOREIGN KEY (document_id, id, result_sha256)
    REFERENCES docx_analysis_results(document_id, run_id, result_sha256) DEFERRABLE INITIALLY DEFERRED;
