"""Original key/anchor retained until a scoped transaction barrier resolves admission."""

import time

from ara.docx_analysis.storage_codec import SavedCheckCommand
from ara.docx_analysis.visible_lists._models import PROFILE as LIST_PROFILE
from ara.docx_analysis.visible_outline._models import PROFILE as OUTLINE_PROFILE
from ara.docx_analysis.visible_style_lists._models import PROFILE as STYLE_LIST_PROFILE
from ara.docx_analysis.visible_word._models import PROFILE as WORD_PROFILE
from ara.docx_analysis_runs import _start, _storage
from ara.docx_analysis_runs._lifecycle_models import RunState


def drive(c):
    if c.s._lanes["admission"].busy:
        return
    for e in c.entries():
        if e.phase != "admitting" or time.monotonic() < e.retry_at:
            continue
        stage = getattr(e, "admission_stage", "new")
        if stage == "new":

            def start(e=e):
                entrypoints = _start
                if c.s._source_profile == LIST_PROFILE:
                    from ara.docx_analysis_runs import structured as entrypoints
                elif c.s._source_profile == OUTLINE_PROFILE:
                    from ara.docx_analysis_runs import outline as entrypoints
                elif c.s._source_profile == STYLE_LIST_PROFILE:
                    from ara.docx_analysis_runs import style_lists as entrypoints
                elif c.s._source_profile == WORD_PROFILE:
                    from ara.docx_analysis_runs import word as entrypoints

                kwargs = dict(client_request_id=e.key, command=e.command, execution=c.s._execution)
                if type(e.command) is SavedCheckCommand:
                    return entrypoints.start_saved(
                        c.runtime("admission"), target_provider=e.provider, **kwargs
                    )
                return entrypoints.retry_run(c.runtime("admission"), **kwargs)

            if c.submit("admission", "admit", start, e):
                e.admission_stage = "running"
        elif stage == "resolve":
            c.submit(
                "admission",
                "lookup",
                lambda e=e: _storage.lookup(c.runtime("admission"), e.command, e.key, e.encoded)[0],
                e,
            )
        return


def result(c, tag, e, cell):
    if cell.error:
        e.error = cell.error
        e.provider = None
        if tag == "lookup" and cell.error in ("not_found", "idempotency_conflict"):
            c.block("recovery_required")
            e.error = "recovery_required"
            return
        c.storage_fault()
        e.admission_stage = "resolve"
        c.retry(e)
        return
    e.provider = None
    out = cell.value
    if out is None:
        e.phase = "not_admitted"
        c.remove(e)
        return
    summary = out.summary
    e.run_id, e.state = summary.run_id, RunState(summary, None, 0, None, None, None)
    if summary.status in ("succeeded", "failed", "cancelled", "timed_out"):
        e.phase, e.terminal = "finished", True
        c.remove(e)
    elif tag == "admit" and out.replayed:
        e.error = "recovery_required"
        e.phase = "not_admitted"
        c.remove(e)
        c.block("recovery_required")
    else:
        e.phase, e.error = "queued", None
        e.retry_at = 0
