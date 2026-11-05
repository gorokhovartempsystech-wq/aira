-- Normative F2 DDL; migration installs it, runtime never executes this document.
CREATE TABLE docx_analysis_supervisor (
    slot_key SMALLINT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1,
    phase TEXT NOT NULL DEFAULT 'unprovisioned',
    installation_id UUID,
    owner_epoch UUID,
    launch_id UUID,
    document_id UUID,
    run_id UUID,
    attempt_id UUID,
    worker_instance_id UUID,
    claim_fence SMALLINT,
    CONSTRAINT pk_docx_analysis_supervisor PRIMARY KEY (slot_key),
    CONSTRAINT ck_dasv_singleton CHECK (slot_key = 1),
    CONSTRAINT ck_dasv_revision CHECK (revision > 0),
    CONSTRAINT ck_dasv_shape CHECK (
      (phase = 'unprovisioned' AND installation_id IS NULL AND owner_epoch IS NULL
       AND launch_id IS NULL AND document_id IS NULL AND run_id IS NULL
       AND attempt_id IS NULL AND worker_instance_id IS NULL AND claim_fence IS NULL)
      OR
      (phase = 'clean' AND installation_id IS NOT NULL
       AND launch_id IS NULL AND document_id IS NULL AND run_id IS NULL
       AND attempt_id IS NULL AND worker_instance_id IS NULL AND claim_fence IS NULL)
      OR
      (phase IN ('armed', 'drained') AND installation_id IS NOT NULL AND owner_epoch IS NOT NULL
       AND launch_id IS NOT NULL AND document_id IS NOT NULL AND run_id IS NOT NULL
       AND attempt_id IS NOT NULL AND worker_instance_id IS NOT NULL
       AND claim_fence IS NOT NULL AND claim_fence = 1)
    )
);
INSERT INTO docx_analysis_supervisor(slot_key) VALUES (1);
