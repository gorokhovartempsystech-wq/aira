"""Record a sealed local decision without using SQL lease expiry as local time."""

from ara.docx_analysis_runs import _lifecycle as life
from ara.docx_analysis_runs._lifecycle_storage import locked, state

from . import _sql as db
from ._exit_authority import decision


def apply_exit(engine, authority):
    proof = decision(authority)
    summary = proof.summary
    with db.transaction(engine) as session:
        run, attempt, scope = locked(session, summary.document_id, summary.run_id)
        row = db.locked(session)
        db.owned(row, proof.owner)
        if row.phase not in ("clean", "armed", "drained"):
            db.fail("recovery_required")
        fields = (
            "document_id",
            "storage_revision",
            "source_sha256",
            "snapshot_sha256",
            "client_request_id",
            "execution_spec_sha256",
            "profile",
            "policy_version",
        )
        if (
            any(getattr(run, k) != getattr(summary, k) for k in fields)
            or run.command_sha256 != proof.command_sha256
            or (run.accepted_project_id, run.accepted_owner_id) != (proof.project_id, proof.user_id)
        ):
            db.fail("recovery_required")
        if proof.claim is None:
            if run.attempt_id is not None:
                db.fail("recovery_required")
        else:
            if not life.match(run, attempt, proof.claim) or not db.claim_metadata(
                run, attempt, proof.claim
            ):
                db.fail("recovery_required")
            if row.phase != "clean":
                db.bound(row, proof.binding)
        if run.status not in life.TERMINAL:
            now = life.clock(session)
            if scope != (run.accepted_project_id, run.accepted_owner_id):
                status, code = "failed", "ownership_changed"
            elif now >= run.deadline_at or proof.reason == "deadline":
                status, code = "timed_out", "deadline_exceeded"
                if now < run.deadline_at:
                    run.timeout_basis = "continuous"
            elif proof.reason == "user":
                status, code = "cancelled", "cancelled"
            elif proof.reason in ("child", "protocol"):
                status, code = "failed", "adapter_error"
            else:
                status, code = "failed", "interrupted"
            life.terminal(run, status, code, now)
        result = state(run)
    return result
