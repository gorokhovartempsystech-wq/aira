"""Startup-only bounded recovery; no new claim, heartbeat or inference."""

from ara.docx_analysis_runs import _lifecycle as old

from . import _queries, lifecycle
from .sql_models import QueuedRun


def retire(engine):
    rows = _queries.snapshot_active(engine)
    for document_id, run_id, status in rows:
        if status == "queued":
            lifecycle.retire_queued(engine, QueuedRun(document_id, run_id))
    old.reap_expired(engine, limit=32)
    return not _queries.snapshot_active(engine)
