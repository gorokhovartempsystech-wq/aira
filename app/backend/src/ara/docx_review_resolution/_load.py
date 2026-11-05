"""Finite scoped SQL capture with metadata admission before extra blob loading."""

from uuid import UUID

from sqlalchemy import and_, func, select

from ara.documents.storage import DocumentError
from ara.docx_review_preferences import _codec, _reads
from ara.docx_review_preferences._models import MAX_HIDDEN, fail, require
from ara.docx_review_preferences._reads import records
from ara.models import DocxAnalysisAttempt as Attempt
from ara.models import DocxAnalysisResult as Result
from ara.models import DocxAnalysisRun as Run
from ara.models import DocxAnalysisSource as Source
from ara.models import DocxReviewDismissal as Dismissal

from ._models import DismissalRef, ResolutionInput, bounded, checked_limits, weight


def read_decisions(session, state):
    rows = session.execute(
        select(
            Dismissal.dismissal_key,
            Dismissal.source_run_id,
            Dismissal.source_result_sha256,
            Dismissal.source_finding_id,
            Dismissal.hidden_at_revision,
        )
        .where(Dismissal.document_id == state.document_id)
        .order_by(Dismissal.dismissal_key)
        .limit(MAX_HIDDEN + 1)
    ).all()
    require(len(rows) <= MAX_HIDDEN, "storage_error")
    decisions = tuple(DismissalRef(*row) for row in rows)
    require(tuple(d.key for d in decisions) == state.hidden_keys, "storage_error")
    require(
        all(
            _codec.digest(d.key, "dh-")
            and type(d.run_id) is UUID
            and _codec.digest(d.result_sha256)
            and _codec.digest(d.finding_id, "df-")
            and _codec.counter(d.hidden_at_revision)
            and 1 <= d.hidden_at_revision <= state.revision
            for d in decisions
        ),
        "storage_error",
    )
    return decisions


def record_size(session, document_id, run_id, digest):
    columns = (
        Source.source_data,
        Run.snapshot_data,
        Run.command_data,
        Run.execution_spec,
        Attempt.request_data,
        Result.reply_data,
        Result.result_data,
    )
    row = session.execute(
        select(*(func.octet_length(c) for c in columns))
        .select_from(Run)
        .join(
            Source,
            and_(Source.document_id == Run.document_id, Source.source_sha256 == Run.source_sha256),
        )
        .join(
            Attempt,
            and_(
                Attempt.id == Run.attempt_id,
                Attempt.run_id == Run.id,
                Attempt.document_id == Run.document_id,
            ),
        )
        .join(
            Result,
            and_(
                Result.run_id == Run.id,
                Result.attempt_id == Attempt.id,
                Result.document_id == Run.document_id,
            ),
        )
        .where(
            Run.id == run_id,
            Run.document_id == document_id,
            Run.status == "succeeded",
            Result.result_sha256 == digest,
            Run.result_sha256 == digest,
        )
    ).one_or_none()
    require(row is not None and all(type(v) is int and v > 0 for v in row), "storage_error")
    return sum(row)


def load_inputs(session, state, target, *, limits=None):
    limits = checked_limits(limits)
    decisions = read_decisions(session, state)
    references = {target.run_id: target.result.result_sha256}
    for decision in decisions:
        prior = references.setdefault(decision.run_id, decision.result_sha256)
        require(prior == decision.result_sha256, "storage_error")
    bounded(len(references) <= limits.max_origins)
    total = weight(target)
    bounded(total <= limits.max_record_bytes)
    sizes = {}
    # Admission examines only lengths before fetching any additional origin buffers.
    for run_id, digest in sorted(references.items()):
        if run_id != target.run_id:
            sizes[run_id] = record_size(session, state.document_id, run_id, digest)
            total += sizes[run_id]
            bounded(total <= limits.max_record_bytes)
    origins = []
    for run_id in sizes:
        origin = records(session, state.document_id, run_id, references[run_id])
        require(weight(origin) == sizes[run_id], "storage_error")
        origins.append(origin)
    return ResolutionInput(state, target, tuple(origins), decisions, limits)


def recheck_inputs(session, inputs):
    """Caller must already own the scoped transaction; never decode under locks."""
    state = _reads.snapshot(session, inputs.state.document_id)
    if state.revision != inputs.state.revision:
        fail("preferences_conflict")
    require(
        state == inputs.state and read_decisions(session, state) == inputs.decisions,
        "storage_error",
    )
    for origin in (inputs.target, *inputs.origins):
        actual = records(session, state.document_id, origin.run_id, origin.result.result_sha256)
        require(actual == origin, "storage_error")


def get_resolution(runtime, *, document_id, run_id, result_sha256, limits=None):
    from ._resolve import resolve

    limits = checked_limits(limits)
    _reads.context(runtime, document_id)
    require(type(run_id) is UUID and _codec.digest(result_sha256))
    try:
        with _reads.transaction(runtime, document_id) as session:
            state = _reads.snapshot(session, document_id)
            target = records(session, document_id, run_id, result_sha256)
            inputs = load_inputs(session, state, target, limits=limits)
        result = resolve(inputs)
        with _reads.transaction(runtime, document_id) as session:
            actual = _reads.snapshot(session, document_id)
            if actual.revision != state.revision:
                fail("preferences_conflict")
            require(
                actual == state and read_decisions(session, state) == inputs.decisions,
                "storage_error",
            )
        return result
    except DocumentError:
        raise
    except Exception:
        fail("storage_error")
